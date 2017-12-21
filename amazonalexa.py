
import json
from os import environ, path, makedirs, kill
import time

# Import twisted libraries
from twisted.internet.defer import inlineCallbacks, Deferred
from twisted.internet import protocol
from twisted.internet import reactor
from twisted.internet.task import LoopingCall

from yombo.core.exceptions import YomboWarning
from yombo.core.module import YomboModule
from yombo.core.log import get_logger
from yombo.utils import random_string, read_file, save_file, bytes_to_unicode
from twisted.internet.error import ProcessExitedAlready

logger = get_logger("modules.amazonalexa")
from yombo.modules.amazonalexa.web_routes import module_amazonalexa_routes


class AmazonAlexa(YomboModule):
    """
    Amazon Alexa allows you to control your devices through Alexa.

    .. moduleauthor:: Mitch Schwenk <mitch-gw@yombo.net>

    :copyright: Copyright 2017 by Yombo.
    :license: LICENSE for details.
    """
    @inlineCallbacks
    def _start_(self, **kwargs):
        # iterate throug modules, build a json list. Then create a node type "module_amazon_alexa". Lists
        # the gateway_id and device_id. Allows for for single or group control.
        pass

    def _webinterface_module_config_(self, **kwargs):
        """
        Add web interface routes.

        :param kwargs:
        :return:
        """
        return '/modules_settings/amazonalexa/index'

    def _webinterface_add_routes_(self, **kwargs):
        """
        Add web interface routes.

        :param kwargs:
        :return:
        """
        if self._States['loader.operating_mode'] == 'run':
            return {
                'nav_side': [
                    {
                        'label1': 'Module Settings',
                        'label2': 'Amazon Alexa',
                        'priority1': 3400,  # Even with a value, 'Tools' is already defined and will be ignored.
                        'priority2': 100,
                        'icon': 'fa fa-gear fa-fw',
                        'url': '/modules_settings/amazonalexa/index',
                        'tooltip': '',
                        'opmode': 'run',
                    },
                ],
                'routes': [
                    module_amazonalexa_routes,
                ],
            }

    @inlineCallbacks
    def build_node(self):
        """
        Builds the node to be sent to Yombo.

        :return:
        """
        pass

    @inlineCallbacks
    def read_node(self):
        """
        Reads a previous built node.

        :return:
        """
        pass
