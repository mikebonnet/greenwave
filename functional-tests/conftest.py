# SPDX-License-Identifier: GPL-2.0+

import os
import time
import textwrap
import itertools
import json
import logging
import subprocess
import socket
import pytest
import requests
from sqlalchemy import create_engine


log = logging.getLogger(__name__)


# It's all local, and so should be fast enough.
TEST_HTTP_TIMEOUT = int(os.environ.get('TEST_HTTP_TIMEOUT', 2))


def drop_and_create_database(dbname):
    """
    Drops (if exists) and re-creates the given database on the local Postgres instance.
    """
    engine = create_engine('postgresql+psycopg2:///template1')
    with engine.connect() as connection:
        connection.execution_options(isolation_level='AUTOCOMMIT')
        connection.execute('DROP DATABASE IF EXISTS {}'.format(dbname))
        connection.execute('CREATE DATABASE {}'.format(dbname))
    engine.dispose()


def wait_for_listen(port):
    """
    Waits until something is listening on the given TCP port.
    """
    for attempt in range(5):
        try:
            s = socket.create_connection(('127.0.0.1', port), timeout=1)
            s.close()
            return
        except socket.error:
            time.sleep(1)
    raise RuntimeError('Gave up waiting for port %s' % port)


@pytest.yield_fixture(scope='session')
def resultsdb_server(tmpdir_factory):
    if 'RESULTSDB_TEST_URL' in os.environ:
        yield os.environ['RESULTSDB_TEST_URL']
    else:
        # Start ResultsDB as a subprocess
        resultsdb_source = os.environ.get('RESULTSDB', '../resultsdb')
        if not os.path.isdir(resultsdb_source):
            raise RuntimeError('ResultsDB source tree %s does not exist' % resultsdb_source)
        dbname = 'resultsdb_for_greenwave_functest'
        # Write out a config
        settings_file = tmpdir_factory.mktemp('resultsdb').join('settings.py')
        settings_file.write(textwrap.dedent("""\
            PORT = 5001
            SQLALCHEMY_DATABASE_URI = 'postgresql+psycopg2:///%s'
            DEBUG = False
            """ % dbname))
        env = dict(os.environ,
                   PYTHONPATH=resultsdb_source,
                   TEST='true',
                   RESULTSDB_CONFIG=settings_file.strpath)
        # Create and populate the database
        drop_and_create_database(dbname)
        subprocess.check_call(['python',
                               os.path.join(resultsdb_source, 'run_cli.py'),
                               'init_db'],
                              env=env)
        # Start server
        p = subprocess.Popen(['python',
                              os.path.join(resultsdb_source, 'runapp.py')],
                             env=env)
        log.debug('Started resultsdb server as pid %s', p.pid)
        wait_for_listen(5001)
        yield 'http://localhost:5001/'
        log.debug('Terminating resultsdb server pid %s', p.pid)
        p.terminate()
        p.wait()


@pytest.yield_fixture(scope='session')
def waiverdb_server(tmpdir_factory):
    if 'WAIVERDB_TEST_URL' in os.environ:
        yield os.environ['WAIVERDB_TEST_URL']
    else:
        # Start WaiverDB as a subprocess
        waiverdb_source = os.environ.get('WAIVERDB', '../waiverdb')
        if not os.path.isdir(waiverdb_source):
            raise RuntimeError('WaiverDB source tree %s does not exist' % waiverdb_source)
        dbname = 'waiverdb_for_greenwave_functest'
        # Write out a config
        settings_file = tmpdir_factory.mktemp('waiverdb').join('settings.py')
        settings_file.write(textwrap.dedent("""\
            AUTH_METHOD = 'dummy'
            DATABASE_URI = 'postgresql+psycopg2:///%s'
            """ % dbname))
        env = dict(os.environ,
                   PYTHONPATH=waiverdb_source,
                   TEST='true',
                   WAIVERDB_CONFIG=settings_file.strpath)
        # Create and populate the database
        drop_and_create_database(dbname)
        subprocess.check_call(['python3',
                               os.path.join(waiverdb_source, 'waiverdb', 'manage.py'),
                               'db', 'upgrade'],
                              env=env)
        # Start server
        p = subprocess.Popen(['python3-gunicorn',
                              '--bind=127.0.0.1:5004',
                              '--access-logfile=-',
                              'waiverdb.wsgi:app'],
                             env=env)
        log.debug('Started waiverdb server as pid %s', p.pid)
        wait_for_listen(5004)
        yield 'http://localhost:5004/'
        log.debug('Terminating waiverdb server pid %s', p.pid)
        p.terminate()
        p.wait()


# This is only a fixture because some tests want to point the fedmsg consumers
# at the same cache that the server process is using.
# I would like to refactor those tests to send real messages to real consumers,
# so this becomes unnecessary.
@pytest.fixture(scope='session')
def greenwave_cache_config(tmpdir_factory):
    cache_file = tmpdir_factory.mktemp('greenwave-cache').join('cache.dbm')
    return {
        'backend': 'dogpile.cache.dbm',
        'expiration_time': 300,
        'arguments': {'filename': cache_file.strpath},
    }


@pytest.yield_fixture(scope='session')
def greenwave_server(tmpdir_factory, resultsdb_server, waiverdb_server, greenwave_cache_config):
    if 'GREENWAVE_TEST_URL' in os.environ:
        yield os.environ['GREENWAVE_TEST_URL']
    else:
        # Start Greenwave as a subprocess
        settings_file = tmpdir_factory.mktemp('greenwave').join('settings.py')
        settings_file.write(textwrap.dedent("""\
            CACHE = %r
            """ % greenwave_cache_config))
        env = dict(os.environ,
                   PYTHONPATH='.',
                   TEST='true',
                   GREENWAVE_CONFIG=settings_file.strpath)
        p = subprocess.Popen(['gunicorn',
                              '--bind=127.0.0.1:5005',
                              '--access-logfile=-',
                              'greenwave.wsgi:app'],
                             env=env)
        log.debug('Started greenwave server as pid %s', p.pid)
        wait_for_listen(5005)
        yield 'http://localhost:5005/'
        log.debug('Terminating greenwave server pid %s', p.pid)
        p.terminate()
        p.wait()


@pytest.fixture(scope='session')
def requests_session(request):
    s = requests.Session()
    request.addfinalizer(s.close)
    return s


class TestDataBuilder(object):
    """
    Test fixture object which has helper methods for setting up test data in
    ResultsDB and WaiverDB.
    """

    def __init__(self, requests_session, resultsdb_url, waiverdb_url):
        self.requests_session = requests_session
        self.resultsdb_url = resultsdb_url
        self.waiverdb_url = waiverdb_url
        self._counter = itertools.count(1)

    def unique_nvr(self):
        return 'glibc-1.0-{}.el7'.format(self._counter.next())

    def unique_compose_id(self):
        return 'Fedora-9000-19700101.n.{}'.format(self._counter.next())

    def create_compose_result(self, compose_id, testcase_name, outcome, scenario=None):
        data = {
            'testcase': {'name': testcase_name},
            'data': {'productmd.compose.id': compose_id},
            'outcome': outcome,
        }
        if scenario:
            data['data']['scenario'] = scenario
        response = self.requests_session.post(
            self.resultsdb_url + 'api/v2.0/results',
            headers={'Content-Type': 'application/json'},
            timeout=TEST_HTTP_TIMEOUT,
            data=json.dumps(data))
        response.raise_for_status()
        return response.json()

    def create_result(self, item, testcase_name, outcome, scenario=None):
        data = {
            'testcase': {'name': testcase_name},
            'data': {'item': item, 'type': 'koji_build'},
            'outcome': outcome,
        }
        if scenario:
            data['data']['scenario'] = scenario
        response = self.requests_session.post(
            self.resultsdb_url + 'api/v2.0/results',
            headers={'Content-Type': 'application/json'},
            timeout=TEST_HTTP_TIMEOUT,
            data=json.dumps(data))
        response.raise_for_status()
        return response.json()

    def create_waiver(self, result, product_version, waived=True):
        data = {
            'subject': result['subject'],
            'testcase': result['testcase'],
            'product_version': product_version,
            'waived': waived,
        }
        # We assume WaiverDB is configured with
        # AUTH_METHOD = 'dummy' to accept Basic with any credentials.
        response = self.requests_session.post(
            self.waiverdb_url + 'api/v1.0/waivers/',
            auth=('dummy', 'dummy'),
            headers={'Content-Type': 'application/json'},
            timeout=TEST_HTTP_TIMEOUT,
            data=json.dumps(data))
        response.raise_for_status()
        return response.json()


@pytest.fixture(scope='session')
def testdatabuilder(requests_session, resultsdb_server, waiverdb_server):
    return TestDataBuilder(requests_session, resultsdb_server, waiverdb_server)
