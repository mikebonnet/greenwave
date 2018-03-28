# SPDX-License-Identifier: GPL-2.0+

import json
import mock
import pprint

from greenwave.consumers import resultsdb


@mock.patch('greenwave.consumers.resultsdb.fedmsg.config.load_config')
@mock.patch('greenwave.consumers.resultsdb.fedmsg.publish')
def test_consume_new_result(
        mock_fedmsg, load_config, requests_session, greenwave_server,
        testdatabuilder, monkeypatch):
    monkeypatch.setenv('TEST', 'true')
    load_config.return_value = {'greenwave_api_url': greenwave_server + 'api/v1.0'}
    nvr = testdatabuilder.unique_nvr()
    result = testdatabuilder.create_result(item=nvr,
                                           testcase_name='dist.rpmdeplint',
                                           outcome='PASSED')
    message = {
        'body': {
            'topic': 'taskotron.result.new',
            'msg': {
                'result': {
                    'id': result['id'],
                    'outcome': 'PASSED'
                },
                'task': {
                    'item': nvr,
                    'type': 'koji_build',
                    'name': 'dist.rpmdeplint'
                }
            }
        }
    }
    hub = mock.MagicMock()
    hub.config = {
        'environment': 'environment',
        'topic_prefix': 'topic_prefix',
        'greenwave_cache': {'backend': 'dogpile.cache.null'},
    }
    handler = resultsdb.ResultsDBHandler(hub)
    assert handler.topic == ['topic_prefix.environment.taskotron.result.new']
    handler.consume(message)

    # get old decision
    data = {
        'decision_context': 'bodhi_update_push_stable',
        'product_version': 'fedora-26',
        'subject': [{'item': nvr, 'type': 'koji_build'}],
        'ignore_result': [result['id']]
    }
    r = requests_session.post(greenwave_server + 'api/v1.0/decision',
                              headers={'Content-Type': 'application/json'},
                              data=json.dumps(data))
    assert r.status_code == 200
    old_decision = r.json()
    # should have two messages published as we have two decision contexts applicable to
    # this subject.
    first_msg = {
        'policies_satisfied': False,
        'decision_context': 'bodhi_update_push_stable',
        'product_version': 'fedora-26',
        'unsatisfied_requirements': [
            {
                'testcase': 'dist.abicheck',
                'item': {
                    'item': nvr,
                    'type': 'koji_build'
                },
                'type': 'test-result-missing',
                'scenario': None,
            },
            {
                'testcase': 'dist.upgradepath',
                'item': {
                    'item': nvr,
                    'type': 'koji_build'
                },
                'type': 'test-result-missing',
                'scenario': None,
            }
        ],
        'summary': '2 of 3 required tests not found',
        'subject': [
            {
                'item': nvr,
                'type': 'koji_build'
            }
        ],
        'applicable_policies': ['taskotron_release_critical_tasks_with_blacklist',
                                'taskotron_release_critical_tasks'],
        'previous': old_decision,
    }
    mock_fedmsg.assert_any_call(topic='decision.update', msg=first_msg)
    # get the old decision for the second policy
    data = {
        'decision_context': 'bodhi_update_push_testing',
        'product_version': 'fedora-26',
        'subject': [{'item': nvr, 'type': 'koji_build'}],
        'ignore_result': [result['id']]
    }
    r = requests_session.post(greenwave_server + 'api/v1.0/decision',
                              headers={'Content-Type': 'application/json'},
                              data=json.dumps(data))
    assert r.status_code == 200
    old_decision = r.json()
    second_msg = {
        'policies_satisfied': True,
        'decision_context': 'bodhi_update_push_testing',
        'product_version': 'fedora-26',
        'unsatisfied_requirements': [],
        'summary': 'all required tests passed',
        'subject': [
            {
                'item': nvr,
                'type': 'koji_build'
            }
        ],
        'applicable_policies': ['taskotron_release_critical_tasks_for_testing'],
        'previous': old_decision,
    }
    mock_fedmsg.assert_any_call(topic='decision.update', msg=second_msg)


@mock.patch('greenwave.consumers.resultsdb.fedmsg.config.load_config')
@mock.patch('greenwave.consumers.resultsdb.fedmsg.publish')
def test_no_message_for_unchanged_decision(
        mock_fedmsg, load_config, requests_session, greenwave_server,
        testdatabuilder, monkeypatch):
    monkeypatch.setenv('TEST', 'true')
    load_config.return_value = {'greenwave_api_url': greenwave_server + 'api/v1.0'}
    nvr = testdatabuilder.unique_nvr()
    # One result gets the decision in a certain state.
    testdatabuilder.create_result(item=nvr,
                                  testcase_name='dist.rpmdeplint',
                                  outcome='PASSED')
    # Recording a new version of the same result shouldn't change our decision at all.
    new_result = testdatabuilder.create_result(
        item=nvr,
        testcase_name='dist.rpmdeplint',
        outcome='PASSED')
    message = {
        'body': {
            'topic': 'taskotron.result.new',
            'msg': {
                'result': {
                    'id': new_result['id'],
                    'outcome': 'PASSED'
                },
                'task': {
                    'item': nvr,
                    'type': 'koji_build',
                    'name': 'dist.rpmdeplint'
                }
            }
        }
    }
    hub = mock.MagicMock()
    hub.config = {
        'environment': 'environment',
        'topic_prefix': 'topic_prefix',
        'greenwave_cache': {'backend': 'dogpile.cache.null'},
    }
    handler = resultsdb.ResultsDBHandler(hub)
    assert handler.topic == ['topic_prefix.environment.taskotron.result.new']
    handler.consume(message)
    # No message should be published as the decision is unchanged since we
    # are still missing the required tests.
    mock_fedmsg.assert_not_called()


@mock.patch('greenwave.consumers.resultsdb.fedmsg.config.load_config')
@mock.patch('greenwave.consumers.resultsdb.fedmsg.publish')
def test_invalidate_new_result_with_mocked_cache(
        mock_fedmsg, load_config, requests_session, greenwave_server,
        testdatabuilder, monkeypatch):
    """ Consume a result, and ensure that `delete` is called. """
    monkeypatch.setenv('TEST', 'true')
    load_config.return_value = {'greenwave_api_url': greenwave_server + 'api/v1.0'}
    nvr = testdatabuilder.unique_nvr()
    result = testdatabuilder.create_result(
        item=nvr, testcase_name='dist.rpmdeplint', outcome='PASSED')
    message = {
        'body': {
            'topic': 'taskotron.result.new',
            'msg': {
                'result': {
                    'id': result['id'],
                    'outcome': 'PASSED'
                },
                'task': {
                    'item': nvr,
                    'type': 'koji_build',
                    'name': 'dist.rpmdeplint'
                }
            }
        }
    }
    hub = mock.MagicMock()
    hub.config = {
        'environment': 'environment',
        'topic_prefix': 'topic_prefix',
        'greenwave_cache': {'backend': 'dogpile.cache.memory'},
    }
    handler = resultsdb.ResultsDBHandler(hub)
    handler.cache = mock.MagicMock()
    assert handler.topic == [
        'topic_prefix.environment.taskotron.result.new',
        # Not ready to handle waiverdb yet.
        #'topic_prefix.environment.waiver.new',
    ]
    handler.consume(message)
    expected = ("greenwave.resources:retrieve_results|"
                "{u'item': u'%s', u'type': u'koji_build'}" % nvr)
    handler.cache.delete.assert_called_once_with(expected)


@mock.patch('greenwave.consumers.resultsdb.fedmsg.config.load_config')
@mock.patch('greenwave.consumers.resultsdb.fedmsg.publish')
def test_invalidate_new_result_with_real_cache(
        mock_fedmsg, load_config, requests_session, greenwave_server,
        testdatabuilder, monkeypatch, greenwave_cache_config):
    monkeypatch.setenv('TEST', 'true')
    load_config.return_value = {'greenwave_api_url': greenwave_server + 'api/v1.0'}
    nvr = testdatabuilder.unique_nvr()
    for testcase_name in ['dist.rpmdeplint', 'dist.upgradepath', 'dist.abicheck']:
        testdatabuilder.create_result(
            item=nvr, testcase_name=testcase_name, outcome='PASSED')

    # get first passing decision
    query = {
        'decision_context': 'bodhi_update_push_stable',
        'product_version': 'fedora-26',
        'subject': [{'item': nvr, 'type': 'koji_build'}],
    }
    r = requests_session.post(greenwave_server + 'api/v1.0/decision',
                              headers={'Content-Type': 'application/json'},
                              data=json.dumps(query))
    assert r.status_code == 200
    response = r.json()
    # Ensure it is passing...
    assert response['policies_satisfied'], pprint.pformat(response)

    # Now, insert a new result and ensure that caching has made it such that
    # even though the new result fails, our decision still passes (bad)
    testdatabuilder.create_result(
        item=nvr, testcase_name='dist.abicheck', outcome='FAILED')
    r = requests_session.post(greenwave_server + 'api/v1.0/decision',
                              headers={'Content-Type': 'application/json'},
                              data=json.dumps(query))
    assert r.status_code == 200
    response = r.json()
    # Ensure it is passing...  BUT IT SHOULDN'T BE!
    assert response['policies_satisfied'], pprint.pformat(response)

    # Now, handle a message about the new failing result
    message = {
        'body': {
            u'topic': u'taskotron.result.new',
            u'msg': {
                u'result': {
                    u'id': u'whatever',
                    u'outcome': u'doesn\'t matter',
                },
                u'task': {
                    u'item': nvr.decode('utf-8'),
                    u'type': u'koji_build',
                    u'name': u'dist.rpmdeplint'
                }
            }
        }
    }
    hub = mock.MagicMock()
    hub.config = {
        'environment': 'environment',
        'topic_prefix': 'topic_prefix',
        'greenwave_cache': greenwave_cache_config,
    }
    handler = resultsdb.ResultsDBHandler(hub)
    assert handler.topic == [
        'topic_prefix.environment.taskotron.result.new',
        # Not ready to handle waiverdb yet.
        #'topic_prefix.environment.waiver.new',
    ]
    handler.consume(message)

    # At this point, the invalidator should have invalidated the cache.  If we
    # ask again, the decision should be correct now.  It should be a stone cold
    # "no".
    r = requests_session.post(greenwave_server + 'api/v1.0/decision',
                              headers={'Content-Type': 'application/json'},
                              data=json.dumps(query))
    assert r.status_code == 200
    response = r.json()
    # Ensure it is failing -- as it should be.
    assert not response['policies_satisfied'], pprint.pformat(response)


@mock.patch('greenwave.consumers.resultsdb.fedmsg.config.load_config')
@mock.patch('greenwave.consumers.resultsdb.fedmsg.publish')
def test_invalidate_new_result_with_no_preexisting_cache(
        mock_fedmsg, load_config, requests_session, greenwave_server,
        testdatabuilder, monkeypatch):
    """ Ensure that invalidating an unknown value is sane. """
    monkeypatch.setenv('TEST', 'true')
    load_config.return_value = {'greenwave_api_url': greenwave_server + 'api/v1.0'}
    nvr = testdatabuilder.unique_nvr()
    result = testdatabuilder.create_result(
        item=nvr, testcase_name='dist.rpmdeplint', outcome='PASSED')
    message = {
        'body': {
            'topic': 'taskotron.result.new',
            'msg': {
                'result': {
                    'id': result['id'],
                    'outcome': 'PASSED'
                },
                'task': {
                    'item': nvr,
                    'type': 'koji_build',
                    'name': 'dist.rpmdeplint'
                }
            }
        }
    }
    hub = mock.MagicMock()
    hub.config = {
        'environment': 'environment',
        'topic_prefix': 'topic_prefix',
        'greenwave_cache': {'backend': 'dogpile.cache.memory'},
    }
    handler = resultsdb.ResultsDBHandler(hub)
    handler.cache.delete = mock.MagicMock()
    assert handler.topic == [
        'topic_prefix.environment.taskotron.result.new',
        # Not ready to handle waiverdb yet.
        #'topic_prefix.environment.waiver.new',
    ]
    handler.consume(message)
    handler.cache.delete.assert_not_called()


@mock.patch('greenwave.consumers.resultsdb.fedmsg.config.load_config')
@mock.patch('greenwave.consumers.resultsdb.fedmsg.publish')
def test_consume_compose_id_result(
        mock_fedmsg, load_config, requests_session, greenwave_server,
        testdatabuilder, monkeypatch):
    monkeypatch.setenv('TEST', 'true')
    load_config.return_value = {'greenwave_api_url': greenwave_server + 'api/v1.0'}
    compose_id = testdatabuilder.unique_compose_id()
    result = testdatabuilder.create_compose_result(
        compose_id=compose_id,
        testcase_name='compose.install_no_user',
        scenario='scenario1',
        outcome='PASSED')
    message = {
        'body': {
            'topic': 'taskotron.result.new',
            'msg': {
                'result': {
                    'id': result['id'],
                    'outcome': 'PASSED'
                },
                'task': {
                    "productmd.compose.id": compose_id,
                    "name": "compose.install_no_user",
                },
            }
        }
    }
    hub = mock.MagicMock()
    hub.config = {
        'environment': 'environment',
        'topic_prefix': 'topic_prefix',
        'greenwave_cache': {'backend': 'dogpile.cache.null'},
    }
    handler = resultsdb.ResultsDBHandler(hub)
    assert handler.topic == ['topic_prefix.environment.taskotron.result.new']
    handler.consume(message)

    # get old decision
    data = {
        'decision_context': 'rawhide_compose_sync_to_mirrors',
        'product_version': 'fedora-rawhide',
        'subject': [{'productmd.compose.id': compose_id}],
        'ignore_result': [result['id']]
    }
    r = requests_session.post(greenwave_server + 'api/v1.0/decision',
                              headers={'Content-Type': 'application/json'},
                              data=json.dumps(data))
    assert r.status_code == 200
    old_decision = r.json()
    msg = {
        u'applicable_policies': [u'openqa_important_stuff_for_rawhide'],
        u'decision_context': u'rawhide_compose_sync_to_mirrors',
        u'policies_satisfied': False,
        'product_version': 'fedora-rawhide',
        'subject': [{u'productmd.compose.id': compose_id}],
        u'summary': u'1 of 2 required tests not found',
        'previous': old_decision,
        u'unsatisfied_requirements': [{
            u'item': {u'productmd.compose.id': compose_id},
            u'scenario': u'scenario2',
            u'testcase': u'compose.install_no_user',
            u'type': u'test-result-missing'}
        ]
    }

    mock_fedmsg.assert_any_call(topic='decision.update', msg=msg)
