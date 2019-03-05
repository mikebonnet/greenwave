# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-2.0+
"""
The fedora-messaging consumer.

This module is responsible consuming messages sent to the fedora message bus via
fedora-messaging.
It will get all the messages and pass them onto their appropriate fedmsg
consumers to re-use the same code path.
"""

import logging

from greenwave.consumers.resultsdb import ResultsDBHandler
from greenwave.consumers.waiverdb import WaiverDBHandler

from fedora_messaging.config import conf


log = logging.getLogger(__name__)


class Dummy(object):
    """ Dummy object only storing a dictionary named "config" that can be passed
    onto the fedmsg consumer.
    """

    def __init__(self, config):
        self.config = config


def fedora_messaging_callback(message):
    """
    Callback called when messages from fedora-messaging are received.
    It then passes them onto their appropriate fedmsg handler for code
    portability.

    Args:
        message (fedora_messaging.message.Message): The message we received
            from the queue.
    """
    log.info(
        'Received message from fedora-messaging with topic: %s', message.topic)
    consumer_config = conf["consumer_config"]
    if message.topic.endswith("taskotron.result.new"):
        # New resultsdb results
        config = {
            "topic_prefix": consumer_config["topic_prefix"],
            "environment": consumer_config["environment"],
            "resultsdb_topic_suffix": consumer_config["resultsdb_topic_suffix"]
        }
        hub = Dummy(config)
        handler = ResultsDBHandler(hub)
        msg = {"body": {'msg': message.body}}
        log.info('Sending message received to: ResultsDBHandler')
        handler.consume(msg)

    elif message.topic.endswith('waiver.new'):
        # New waiver submitted
        config = {
            "topic_prefix": consumer_config["topic_prefix"],
            "environment": consumer_config["environment"],
            "waiverdb_topic_suffix": consumer_config["waiverdb_topic_suffix"]
        }
        hub = Dummy(config)
        handler = WaiverDBHandler(hub)
        msg = {"body": {'msg': message.body}}
        log.info('Sending message received to: WaiverDBHandler')
        handler.consume(msg)
