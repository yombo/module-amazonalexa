from datetime import datetime
import traceback
from uuid import uuid4

# Import twisted libraries
from twisted.internet.defer import inlineCallbacks, maybeDeferred, Deferred
from twisted.internet.task import LoopingCall

from yombo.core.exceptions import YomboWarning
from yombo.core.module import YomboModule
from yombo.core.log import get_logger
from yombo.utils import random_int
import yombo.utils.color as color_util

from yombo.constants.features import (FEATURE_BRIGHTNESS, FEATURE_SEND_UPDATES, FEATURE_EFFECT, FEATURE_PERCENT,
    FEATURE_RGB_COLOR, FEATURE_TRANSITION, FEATURE_WHITE_VALUE, FEATURE_XY_COLOR, FEATURE_NUMBER_OF_STEPS,
    FEATURE_COLOR_TEMP, FEATURE_SUPPORT_COLOR, FEATURE_POWER_CONTROL, FEATURE_HS_COLOR)
from yombo.constants.platforms import (PLATFORM_COLOR_LIGHT, PLATFORM_LIGHT, PLATFORM_FAN, PLATFORM_APPLIANCE,
    PLATFORM_SWITCH, PLATFORM_LOCK, PLATFORM_TV)

from yombo.modules.amazonalexa.web_routes import module_amazonalexa_routes
logger = get_logger("modules.amazonalexa")

API_TEMP_UNITS = {
    'f': 'FAHRENHEIT',
    'c': 'CELSIUS',
}

class AmazonAlexa(YomboModule):
    """
    Amazon Alexa allows you to control your devices through Alexa.

    .. moduleauthor:: Mitch Schwenk <mitch-gw@yombo.net>

    :copyright: Copyright 2017-2018 by Yombo.
    :license: LICENSE for details.
    """
    display_categories = {
        'fan': 'LIGHT',
        'switch': 'SWITCH',
        'appliance': 'SWITCH',
        'camera': 'CAMERA',
        'light': 'LIGHT',
        'door': 'DOOR',
        'scene': 'SCENE_TRIGGER',
        'lock': 'SMARTLOCK',
        'climate': 'THERMOSTAT',
        'activity_trigger': 'ACTIVITY_TRIGGER',
        'tv': 'OTHER',
        'relay': 'SWITCH',
        'device': 'OTHER',
    }

    def _init_(self, **kwargs):
        self.is_master = self._Configs.get('core', 'is_master', True, False)
        self.fqdn = self._Configs.get('dns', 'fqdn', None, False)
        self.port = self._Configs.get('webinterface', 'secure_port', None, False)
        self.module_enabled = self.is_master
        if self.fqdn is None:
            logger.warn("Amazon Alexa disabled, requires domain name to work.")
            self._Notifications.add({'title': 'Alexa disabled',
                                     'message': 'The Amazon Alexa module only works when a valid DNS domain exists.',
                                     'source': 'Amazon Alexa Module',
                                     'persist': False,
                                     'priority': 'high',
                                     'always_show': True,
                                     'always_show_allow_clear': True,
                                     })
            self.module_enabled = False
        if self.port is None:
            self.module_enabled = False
        self.node = None
        self.working = True
        self.discovery_loop = None
        self.response_handlers = {
            'Alexa.BrightnessController': {
                'AdjustBrightness': self.api_undefined,
                'SetBrightness': self.api_set_brightness,
            },
            'Alexa.ChannelController': {
                'ChangeChannel': self.api_change_channel,
                'DecreaseColorTemperature': self.api_undefined,
                'IncreaseColorTemperature': self.api_undefined,
            },
            'Alexa.ColorController': {
                'SetColor': self.api_set_color,
            },
            'Alexa.ColorTemperatureController': {
                'SetColorTemperature': self.api_undefined,
                'DecreaseColorTemperature': self.api_undefined,
                'IncreaseColorTemperature': self.api_undefined,
            },
            'Alexa.LockController': {
                'Lock': self.api_lock,
                'Unlock': self.api_unlock,
            },
            'Alexa.PercentageController': {
                'SetPercentage': self.api_undefined,
                'AdjustPercentage': self.api_undefined,
            },
            'Alexa.PlaybackController': {
                'Play': self.api_undefined,
                'Pause': self.api_undefined,
                'Stop': self.api_undefined,
                'Next': self.api_undefined,
                'Previous': self.api_undefined,
            },
            'Alexa.PowerController': {
                'TurnOn': self.api_turn_on,
                'TurnOff': self.api_turn_off,
            },
            'Alexa.SceneController': {
                'Activate': self.api_scene_activate,
                'Deactivate': self.api_scene_deactivate,
            },
            'Alexa.Speaker': {
                'SetVolume': self.api_undefined,
                'SetMute': self.api_undefined,
            },
            'Alexa.StepSpeaker': {
                'AdjustVolume': self.api_undefined,
                'SetMute': self.api_undefined,
            },
            'Alexa': {
                'ReportState': self.api_undefined,
            },
        }
        self.pending_commands = []

    def _load_(self, **kwargs):
        if self.is_master is False or self.module_enabled is False:
            return
        try:
            self.authkey = self._AuthKeys.get('Amazon Alexa')
            self.authkey.enable()
        except KeyError:
            self.authkey = self._AuthKeys.add_authkey({
                "label": "Amazon Alexa",
                "description": "Automatically generated by the the Amazon Alexa module."
                            " This allows Alexa to send the gateway commands and get status updates.",
                "created_by": "alexa module",
                "created_by_type": "module",
                }
            )
        self.authkey.attach_role('module_amazonalexa_api')

    @inlineCallbacks
    def _start_(self, **kwargs):
        if self.is_master is False:
            logger.warn("Amazon Alexa disabled, only works on the master gateway of a cluster.")
            self._Notifications.add({'title': 'Alexa disabled',
                                     'message': 'The Amazon Alexa module can only be used on a master gateway node.',
                                     'source': 'Amazon Alexa Module',
                                     'persist': False,
                                     'priority': 'high',
                                     'always_show': True,
                                     'always_show_allow_clear': True,
                                     })
            return
        if self.module_enabled is False:
            return

        self.gwid = self._Gateways.local_id

        nodes = self._Nodes.search({'node_type': 'module_amazonalexa'})
        if len(nodes) == 0:
            logger.info("alexa creating new node...")
            self.node = yield self._Nodes.create(label='Module Amazon Alexa',
                                                 machine_label='module_amazonalexa',
                                                 node_type='module_amazonalexa',
                                                 data={'scenes': {}, 'devices': {}, 'config': {}, 'alexa': {}},
                                                 data_content_type='json',
                                                 gateway_id=self.gwid,
                                                 destination='gw')
            if isinstance(self.node, dict) and self.node['status'] != 'success':
                self.working = False
                self._Notifications.add({'title': 'Alexa unable to create node',
                                         'message': 'The Amazon Alexa module was unable to create a new node to save'
                                                    ' configuration in. Reason: \n %s' % self.node['msg'],
                                         'source': 'Amazon Alexa Module',
                                         'persist': False,
                                         'priority': 'high',
                                         'always_show': True,
                                         'always_show_allow_clear': True,
                                         })


        elif nodes is not None and len(nodes) > 1:
            logger.warn("Too many node instances. Taking the first one and dropping old ones: {count}", count=len(nodes))

        for node_id, node in nodes.items():
            # print("amazon alex has node: %s - %s" % (node_id, node.data))
            # print("amazon alex has node: %s - %s" % (node_id, type(node.data)))
            self.node = node
            if 'alexa' not in self.node.data:
                self.node.data['alexa'] = {}
            if 'devices' not in self.node.data:
                self.node.data['devices'] = {}
            if 'allowed' not in self.node.data['devices']:
                self.node.data['devices']['allowed'] = []
            if 'configs' not in self.node.data:
                self.node.data['configs'] = {}
            if 'scenes' not in self.node.data:
                self.node.data['scenes'] = {}
            if 'allowed' not in self.node.data['scenes']:
                self.node.data['scenes']['allowed'] = []
            break

        self.discovery_loop = LoopingCall(self.discovery)
        self.discovery_loop.start(random_int(60 * 60 * 12, .25))

    def _event_types_(self, **kwargs):
        """
        Add Alexa usage instrumentation.

        :param kwargs:
        :return:
        """
        return {
            'module_alexa': {
                'control': {
                    'description': "Tracks device control usage.",
                    'attributes': (
                        'command',
                        'item_type',
                        'item_id',
                    ),
                    'expires': 0,
                },
            },
        }

    def _webinterface_add_routes_(self, **kwargs):
        """
        Add web interface routes.

        :param kwargs:
        :return:
        """
        if self.is_master is True and self._States['loader.operating_mode'] == 'run' and self.module_enabled is True:
            return {
                'nav_side': [
                    {
                        'label1': 'Module Settings',
                        'label2': 'Amazon Alexa',
                        'priority1': 2100,  # Even with a value, 'Tools' is already defined and will be ignored.
                        'priority2': 100,
                        'icon': 'fa fa-cog fa-fw',
                        'url': '/module_settings/amazonalexa/index',
                        'tooltip': '',
                        'opmode': 'run',
                    },
                ],
                'routes': [
                    module_amazonalexa_routes,
                ],
                'configs': {
                    'settings_link': '/module_settings/amazonalexa/index',
                },
            }

    def _auth_platforms_(self, **kwargs):
        """
        Add new auth platform type: module_amazonalexa

        :param kwargs:
        :return:
        """
        if self.module_enabled is True:
            return {
                'module_amazonalexa': {
                    'description': "Used by Amazon Alexa module to authenticate Alexa requests.",
                    'actions': ['api', 'control', 'manage'],
                },
            }

    def _roles_(self, **kwargs):
        """
        Add some roles. This is used to restrict the Auth Key to only be used by the alexa callback.

        :param kwargs:
        :return:
        """
        if self.module_enabled is True:
            return {
                'module_amazonalexa_api': {
                    'label': "Amazon Alexa - API",
                    'description': "Used by Amazon Alexa to make requests to this module. No one else should have this role.",
                    'permissions': [
                        {
                            'platform': 'module_amazonalexa',
                            'item': '*',
                            'action': 'api',
                            'access': 'allow',
                        },
                        {
                            'platform': 'device',
                            'item': '*',
                            'action': 'control',
                            'access': 'allow',
                        },
                    ],
                },
                'module_amazonalexa_module_configs': {
                    'label': "Amazon Alexa - Configuration",
                    'description': "Allows users to select which devices Alexa can control. Used to access alexa module module configs.",
                    'permissions': [
                        {
                            'platform': 'module_amazonalexa',
                            'item': '*',
                            'action': 'manage',
                            'access': 'allow',
                        },
                    ],
                }
            }

    def discovery(self, save=None):
        """
        Discovers all device within the current cluster and sends them to Yombo. Alexa will periodically fetch from
        Yombo servers, even if this gateway is offline or not accessible when Alexa asks for devices.

        This doesn't build the entire response struture, only the endpoint sections. Yombo will
        combine multiple master nodes and create a single response to Alexa.

        If for some reason someone decides to mangle this, Alexa will get a managed response and not smart home
        devices will work through Alexa.

        :return:
        """
        if self.module_enabled is False:
            return

        endpoints = {}
        for device_id, device in self._Devices.devices.items():
            # print("alexa: doing device: %s - %s" % (device.label, device.enabled_status))
            if device_id not in self.node.data['devices']['allowed'] or device.enabled_status != 1:
                continue
            # print("alexa device has good status: %s" % device.label)
            try:
                endpoints[device_id] = self.generate_device_endpoint(device)
            except YomboWarning as e:
                logger.warn("{e}", e=e)

        for scene_id, scene in self._Scenes.scenes.items():
            if scene_id not in self.node.data['scenes']['allowed'] or scene.effective_status() != 1:
                continue
            # print("alexa device has good status: %s" % device.label)
            try:
                endpoints[scene_id] = self.generate_scene_endpoint(scene)
            except YomboWarning as e:
                logger.warn("{e}", e=e)

        # print("alexa endpoints: %s" % json.dumps(endpoints))
        self.node.data['alexa'] = endpoints
        if save is not False:
            self.node.save()

    def generate_device_endpoint(self, device):
        """
        Generates a dictionary to be added to the list of endpoints to be send to Yombo.

        :param device:
        :return:
        """
        def endpoint_health():
            return {
                "type": "AlexaInterface",
                "interface": "Alexa.EndpointHealth",
                "version": "3",
                "properties": {
                    "supported": [
                        {
                            "name": "connectivity"
                        }
                    ],
                    "proactivelyReported": False,
                    "retrievable": False
                }
            }

        if device.PLATFORM in self.display_categories:
            display_category = self.display_categories[device.PLATFORM]
        else:
            display_category = 'OTHER'

        endpoint = {
            "endpointId": device.device_id,
            "manufacturerName": device.device_mfg,
            "friendlyName": device.full_label,
            "description": device.description,
            "displayCategories": [
                display_category,
            ],
            "cookie": {
                "endpoint_type": "device",
                "gwid": device.gateway_id,
                "authkey": self.authkey.auth_id,
                "uri": "https://e.%s:%s" % (self.fqdn, self.port)
            },
            "capabilities": None,
        }

        capabilities = [
            {
                "type": "AlexaInterface",
                "interface": "Alexa",
                "version": "3"
            },
        ]

        # print("device (%s-%s-%s) features: %s" % (device.label, device.PLATFORM, device.SUB_PLATFORM, device.features))
        if device.PLATFORM == "climate":
            supported = [
                {"name": "thermostatMode"}
                ]
            if 'dual_setpoints' in device.FEATURES:
                if 'dual_setpoitns' in device.FEATURES and device.FEATURES['dual_setpoints'] is True:
                    supported.append({"name":"upperSetpoint"})
                    supported.append({"name":"lowerSetpoint"})
                else:
                    supported.append({"name":"targetSetpoint"})
                supported.append({"name":"thermostatMode"})


            capabilities.append({
                "type": "AlexaInterface",
                "interface": "Alexa.PercentageController",
                "version": "3",
                "properties": {
                    "supported": supported,
                    "proactivelyReported": False,
                    "retrievable": False,
                }
            })

        elif device.PLATFORM == 'scene':
                capabilities.append({
                "type": "AlexaInterface",
                "interface": "Alexa.SceneController",
                "version": "3",
                "properties": {
                    "supportsDeactivation": False,
                    "proactivelyReported": False,
                }
            })

        elif device.PLATFORM == 'camera':
            capabilities.append({
                "type": "AlexaInterface",
                "interface": "Alexa.CameraStreamController",
                "version": "3",
                "cameraStreamConfigurations": [
                    {
                        "protocols": [
                            "RTSP"
                        ],
                        "resolutions": [
                            {
                                "width": 1280,
                                "height": 720
                            }
                        ],
                        "authorizationTypes": [
                            "NONE"
                        ],
                        "videoCodecs": [
                            "H264"
                        ],
                        "audioCodecs": [
                            "AAC"
                        ]
                    }
                ]
                })

        elif device.PLATFORM == 'tv':
            capabilities.append({
                "type": "AlexaInterface",
                "interface": "Alexa.ChannelController",
                "version": "3",
                "properties": {
                    "supported": [
                        {"name": "channel"}
                    ],
                    "proactivelyReported": False,
                    "retrievable": False,
                }
            })
            if 'channel_control' in device.FEATURES and device.FEATURES['channel_control'] == True:
                capabilities.append({
                    "type": "AlexaInterface",
                    "interface": "Alexa.InputController",
                    "version": "3",
                    "properties": {
                        "supported": [
                            {"name": "input"}
                        ],
                        "proactivelyReported": False,
                        "retrievable": False,
                    }
                })
                if 'input_control' in device.FEATURES and device.FEATURES['input_control'] == True:
                    capabilities.append({
                    "type": "AlexaInterface",
                    "interface": "Alexa.Speaker",
                    "version": "3",
                    "properties": {
                        "supported": [
                            {"name": "volume"},
                            {"name": "muted"}
                        ],
                        "proactivelyReported": False,
                        "retrievable": False,
                    }
                })

        elif device.PLATFORM == 'lock':
            capabilities.append({
                "type": "AlexaInterface",
                "interface": "Alexa.LockController",
                "version": "3",
                "properties": {
                    "supported": [
                        {"name": "lockState"}
                    ],
                    "proactivelyReported": False,
                    "retrievable": False,
                }
            })


        else:
            for feature, value in device.FEATURES.items():
                if feature == FEATURE_POWER_CONTROL and value is True:
                    capabilities.append({
                        "type": "AlexaInterface",
                        "interface": "Alexa.PowerController",
                        "version": "3",
                        "properties": {
                            "supported": [
                                {"name": "powerState"}
                            ],
                            "proactivelyReported": False,
                            "retrievable": False,
                        }
                    })

                if feature == FEATURE_BRIGHTNESS and value is True:
                    # endpoint['capabilites'].append({
                    capabilities.append({
                        "type": "AlexaInterface",
                        "interface": "Alexa.BrightnessController",
                        "version": "3",
                        "properties": {
                            "supported": [
                                {"name": "brightness"}
                            ],
                            "proactivelyReported": False,
                            "retrievable": False,
                        }
                    })
                    capabilities.append({
                        "type": "AlexaInterface",
                        "interface": "Alexa.PowerLevelController",
                        "version": "3",
                        "properties": {
                            "supported": [
                                {"name": "powerLevel"}
                            ],
                            "proactivelyReported": False,
                            "retrievable": False,
                        }
                    })
                    capabilities.append({
                        "type": "AlexaInterface",
                        "interface": "Alexa.PercentageController",
                        "version": "3",
                        "properties": {
                            "supported": [
                                {"name": "percentage"}
                            ],
                            "proactivelyReported": False,
                            "retrievable": False,
                        }
                    })
                if feature == FEATURE_COLOR_TEMP and value is True:
                    # endpoint['capabilites'].append({
                    capabilities.append({
                        "type": "AlexaInterface",
                        "interface": "Alexa.ColorTemperatureController",
                        "version": "3",
                        "properties": {
                            "supported": [
                                {"name": "colorTemperatureInKelvin"}
                            ],
                            "proactivelyReported": False,
                            "retrievable": False,
                        }
                    })
                if (feature == FEATURE_RGB_COLOR and value is True) or (feature == FEATURE_XY_COLOR and value is True):
                        capabilities.append({
                        "type": "AlexaInterface",
                        "interface": "Alexa.ColorController",
                        "version": "3",
                        "properties": {
                            "supported": [
                                {"name": "color"}
                            ],
                            "proactivelyReported": False,
                            "retrievable": False,
                        }
                    })

        capabilities.append(endpoint_health())
        endpoint['capabilities'] = capabilities
        return endpoint

    def generate_scene_endpoint(self, scene):
        """
        Generates a scene endpoint to be added to the list of items sent back to Yombo which will
        be sent to Amazon Alexa when polled.

        :param device:
        :return:
        """
        return {
            "endpointId": scene.scene_id,
            "manufacturerName": "Yombo",
            "friendlyName": scene.label,
            "description": scene.label,
            "displayCategories": [
                "SCENE_TRIGGER"
            ],
            "cookie": {
                "endpoint_type": "scene",
                "gwid": scene.gateway_id,
                "authkey": self.authkey.auth_id,
                "uri": "https://e.%s:%s" % (self.fqdn, self.port)
            },
            "capabilities": [
                {
                    "type": "AlexaInterface",
                    "interface": "Alexa",
                    "version": "3"
                },
                {
                    "type": "AlexaInterface",
                    "interface": "Alexa.SceneController",
                    "version": "3",
                    "supportsDeactivation": True,
                    "proactivelyReported": False
                },
                {
                    "type": "AlexaInterface",
                    "interface": "Alexa.EndpointHealth",
                    "version": "3",
                    "properties": {
                        "supported": [
                            {
                                "name": "connectivity"
                            }
                        ],
                        "proactivelyReported": True,
                        "retrievable": True
                    }
                }
            ]
        }

    @inlineCallbacks
    def read_node(self):
        """
        Reads a previous built node.

        :return:
        """
        pass

    @inlineCallbacks
    def get_api_response(self, request):
        namespace = request['header']['namespace']
        name = request['header']['name']

        endpoint_type = request['endpoint']['cookie']['endpoint_type']
        if endpoint_type == 'device':
            item_id = request['endpoint']['endpointId']
            # logger.info("getting device for: {item_id}", item_id=item_id)
            yombo_device = self._Devices[item_id]
        if endpoint_type == 'scene':
            item_id = request['endpoint']['endpointId']
            # logger.info("getting scene for: {item_id}", item_id=item_id)
            yombo_device = self._Scenes[item_id]

        if namespace in self.response_handlers:
            if name in self.response_handlers[namespace]:
                handler = self.response_handlers[namespace][name]
                logger.info("Found handler for: {namespace} - {name} = {handler}", namespace=namespace, name=name, handler=handler)
                d = Deferred()
                # print("b : 55: %s" % handler)
                d.addCallback(lambda ignored: maybeDeferred(handler, request, yombo_device))
                d.callback(1)
                results = yield d
                # print("may be deferred results...%s" % json.dumps(results))
                return results
        # logger.warn("Cannot find handler for: {namespace} - {name}", namespace=namespace, name=name)
        return "failed..."

    def api_message(self,
                    request,
                    name='Response',
                    namespace='Alexa',
                    payload=None,
                    context=None):
        """
        Generate a response to Alexa API.
        """
        payload = payload or {}

        response = {
            'alexaresponse': {
                'event': {
                    'header': {
                        'namespace': namespace,
                        'name': name,
                        'messageId': str(uuid4()),
                        'payloadVersion': '3',
                    },
                    'payload': payload,
                }
            },
            'meta': {
            }
        }

        # If a correlation token exists, add it to header / Need by Async requests
        token = request['header'].get('correlationToken')
        if token:
            response['alexaresponse']['event']['header']['correlationToken'] = token

        # Extend event with endpoint object / Need by Async requests
        if 'endpoint' in request:
            response['alexaresponse']['event']['endpoint'] = request['endpoint'].copy()

        if context is not None:
            response['alexaresponse']['context'] = context
        return response

############################################
###  Start various api control responses ###
############################################

    # @inlineCallbacks
    def api_set_brightness(self, request, device):
        percent = request['payload']['brightness']
        # we call the set_percent method since alexa actually sends a percentage.
        request_id = device.set_percent(percent,
                                        auth=self.authkey,
                                        )
        context = self.find_interface(device).serialize_properties(values={'brightness': percent})
        return self.api_message(request, context=context)

    def api_scene_activate(self, request, scene):
        scene.start()
        return _AlexaSceneController(scene, request, "ActivationStarted")

    def api_scene_deactivate(self, request, scene):
        scene.stop()
        return _AlexaSceneController(scene, request, "DeactivationStarted")

    # @inlineCallbacks
    def api_turn_on(self, request, device):
        try:
            device.turn_on(auth=self.authkey)
        except Exception as e:
            print("Error: %s" % e)
            logger.error("{trace}", trace=traceback.format_exc())
            raise e
        controller = _AlexaPowerController(device)
        context = self.find_interface(device).serialize_properties(
            controllers=controller,
            values={'powerState': 'ON'})
        return self.api_message(request, context=context)

    # @inlineCallbacks
    def api_turn_off(self, request, device):
        request_id = device.turn_off(auth=self.authkey)
        controller = _AlexaPowerController(device)
        context = self.find_interface(device).serialize_properties(
            controllers=controller,
            values={'powerState': 'OFF'},)
        # print("After waiting 2 = %s" % context)
        return self.api_message(request, context=context)

    # Untested!!
    def api_change_channel(self, request, device):
        channel_number = int(request['payload']['channel']['number'])
        call_sign = int(request['payload']['channel']['callSign'])
        affiliate_call_sign = int(request['payload']['channel']['affiliateCallSign'])
        uri = int(request['payload']['channel']['uri'])

        request_id = device.set_channel(channel_number, inputs={
            'call_sign': call_sign,
            'affiliate_call_sign': affiliate_call_sign.bit_length(),
            'uri': uri,
            }
        )
        controller = _AlexaChannelController(device)
        context = self.find_interface(device).serialize_properties(
            controllers=controller,
            values={
                'color': {
                    'number': request['payload']['color']['number'],
                    'callSign': request['payload']['color']['callSign'],
                    'affiliateCallSign': request['payload']['color']['affiliateCallSign']
                }
            }
        )
        return self.api_message(request, context=context)

    @inlineCallbacks
    def api_lock(self, request, device):
        request_id = device.lock(auth=self.authkey)
        yield self._Devices.wait_for_command_to_finish(request_id, timeout=5)
        controller = _AlexaLockController(device)
        context = self.find_interface(device).serialize_properties(
            controllers=controller,
            values={'lockState': 'LOCKED'},)
        return self.api_message(request, context=context)

    @inlineCallbacks
    def api_unlock(self, request, device):
        request_id = device.unlock(auth=self.authkey)
        yield self._Devices.wait_for_command_to_finish(request_id, timeout=5)
        controller = _AlexaLockController(device)
        context = self.find_interface(device).serialize_properties(
            controllers=controller,
            values={'lockState': 'UNLOCKED'},)
        # print("After waiting 2 = %s" % context)
        return self.api_message(request, context=context)

    # @inlineCallbacks
    def api_set_color(self, request, device):
        rgb = color_util.color_hsb_to_RGB(
            float(request['payload']['color']['hue']),
            float(request['payload']['color']['saturation']),
            float(request['payload']['color']['brightness'])
        )
        request_id = device.set_color(rgb, auth=self.authkey)
        controller = _AlexaColorController(device)
        context = self.find_interface(device).serialize_properties(
            controllers=controller,
            values={
                'color': {
                    'hue': request['payload']['color']['hue'],
                    'saturation': request['payload']['color']['saturation'],
                    'brightness': request['payload']['color']['brightness']
                }
            }
        )
        # print("alexa context: %s" % context)
        return self.api_message(request, context=context)

    @inlineCallbacks
    def api_undefined(self, request, device):
        return "failed..."

    def find_interface(self, device):
        # print("find_interface type: %s" % device)
        # print("find_interface type: %s" % device.PLATFORM)
        if device.PLATFORM in (PLATFORM_SWITCH, PLATFORM_APPLIANCE):
            return _SwitchInterface(self, device)
        if device.PLATFORM in (PLATFORM_LIGHT, PLATFORM_COLOR_LIGHT, PLATFORM_FAN):
            return _LightInterface(self, device)
        if device.PLATFORM in (PLATFORM_LOCK):
            return _LockInterface(self, device)
        # Items below this line are untested by Yombo.
        if device.PLATFORM in (PLATFORM_TV):
            return _ChannelInterface(self, device)

class _UnsupportedInterface(Exception):
    """This entity does not support the requested Smart Home API interface."""


class _UnsupportedProperty(Exception):
    """This entity does not support the requested Smart Home API property."""

class _AlexaController(object):
    def __init__(self, device):
        self.device = device

    def properties_retrievable(self):
        return self.device.has_feature('pollable')

    @staticmethod
    def properties_supported():
        """Return what properties this entity supports."""
        return []

    @staticmethod
    def properties_proactively_reported():
        """Return True if properties asynchronously reported."""
        return False

    @staticmethod
    def properties_retrievable():
        """Return True if properties can be retrieved."""
        return False

    @staticmethod
    def get_property(name):
        """Read and return a property.

        Return value should be a dict, or raise _UnsupportedProperty.

        Properties can also have a timeOfSample and uncertaintyInMilliseconds,
        but returning those metadata is not yet implemented.
        """
        raise _UnsupportedProperty(name)

    @staticmethod
    def supports_deactivation():
        """Applicable only to scenes."""
        return None


class _AlexaBrightnessController(_AlexaController):
    def name(self):
        return 'Alexa.BrightnessController'

    def properties_supported(self):
        return [{'name': 'brightness'}]

    def get_property(self, name):
        if name != 'brightness':
            raise _UnsupportedProperty(name)
        try:
            return self.device.percent
        except:
            return 0

class _AlexaColorController(_AlexaController):
    def name(self):
        return 'Alexa.ColorController'

    def properties_supported(self):
        return [{'name': 'color'}]
        # return [{'name': 'hue'}, {'name': 'saturation'}, {'name': 'brightness'}]

    def get_property(self, name):
        if name != 'color':
            raise _UnsupportedProperty(name)
        try:
            hs = self.device.hs_color
            # print("hs color: ")
            # print(hs)
            return {
                "hue": hs[0],
                "saturation": hs[1],
                "brightness": hs[2]
            }
            # hs[1] = hs[1]/100
            # hs[2] = hs[2]/100
            # hs = self.device.hs_color
            # hs[1] = hs[1]/100
            # hs[2] = hs[2]/100
            return hs
        except Exception as e:
            print("Error with getting alexa her HS property. : %s" % e)
            return 0


class _AlexaLockController(_AlexaController):
    def name(self):
        return 'Alexa.LockController'

    def properties_supported(self):
        return [{'name': 'lockState'}]

    def properties_retrievable(self):
        return True

    def get_property(self, name):
        if name != 'lockState':
            raise _UnsupportedProperty(name)

        if self.device.is_locked is True:
            return 'LOCKED'
        elif self.device.is_locked is False:
            return 'UNLOCKED'
        return 'JAMMED'

# Untested!!
class _AlexaChannelController(_AlexaController):
    def name(self):
        return 'Alexa.ChannelController'

    def properties_supported(self):
        return [{'name': 'channel'}]

    def properties_retrievable(self):
        return True

    def get_property(self, name):
        if name != 'channel':
            raise _UnsupportedProperty(name)

        if self.device.is_on is True:
            return 'ON'
        return 'OFF'


class _AlexaPowerController(_AlexaController):
    def name(self):
        return 'Alexa.PowerController'

    def properties_supported(self):
        return [{'name': 'powerState'}]

    def properties_retrievable(self):
        return True

    def get_property(self, name):
        if name != 'powerState':
            raise _UnsupportedProperty(name)

        if self.device.is_on is True:
            return 'ON'
        return 'OFF'


def _AlexaSceneController(scene, request, response_type):
    response = {
        "alexaresponse": {
            "context": {
                "properties": [
                    {
                        "namespace": "Alexa.EndpointHealth",
                        "name": "connectivity",
                        "value": {
                            "value": "OK"
                        },
                        "timeOfSample": str(datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.00Z")),
                        "uncertaintyInMilliseconds": 200
                    }
                ]
            },
            "event": {
                "header": {
                    "namespace": "Alexa.SceneController",
                    "name": response_type,
                    "payloadVersion": "3",
                    "messageId": str(uuid4()),
                    # "correlationToken": "", filled in later by api_message()
                },
                "endpoint": {
                    "endpointId": scene.scene_id
                },
                "payload": {
                    "cause": {
                        "type": "VOICE_INTERACTION"
                    },
                    "timestamp": str(datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.00Z"))
                }
            }
        }
    }
    token = request['header'].get('correlationToken')
    if token:
        response['alexaresponse']['event']['header']['correlationToken'] = token
    return response

class _AlexaInterface(object):
    def __init__(self, parent, device):
        self.parent = parent
        self.device = device

    @staticmethod
    def interfaces():
        return []

    def serialize_properties(self, controllers=None, values=None):
        """Return properties serialized for an API response. Goes into the context section."""
        if values is None or isinstance(values, dict) is False:
            values = {}
        properties = []
        if controllers is None:
            controllers = self.controllers()
        elif isinstance(controllers, list) is False:
            controllers = [controllers]

        for controller in controllers:
            properties_supported = controller.properties_supported()
            for property_supported in properties_supported:
                if property_supported['name'] in values:
                    value = values[property_supported['name']]
                else:
                    value = controller.get_property(property_supported['name'])
                properties.append({
                    'name': property_supported['name'],
                    'namespace': controller.name(),
                    'value': value,
                    'timeOfSample': str(datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.00Z")),
                    'uncertaintyInMilliseconds': 200,
                })

        properties.append({
            "namespace": "Alexa.EndpointHealth",
            "name": "connectivity",
            "value": {
                "value": "OK"
            },
            "timeOfSample": str(datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.00Z")),
            "uncertaintyInMilliseconds": 200
        })
        return {'properties': properties}

    def controllers(self):
        return []


class _LightInterface(_AlexaInterface):
    def controllers(self, controller_name=None):
        has_device_feature = self.device.has_device_feature
        controllers = []
        # controllers.append(_AlexaPowerController(self.device))
        if has_device_feature(FEATURE_BRIGHTNESS):
            controllers.append(_AlexaBrightnessController(self.device))
        if has_device_feature(FEATURE_RGB_COLOR) or has_device_feature(FEATURE_XY_COLOR) or \
                has_device_feature(FEATURE_HS_COLOR):
            controllers.append(_AlexaColorController(self.device))
        # if has_device_feature(FEATURE_COLOR_TEMP):
        #     yield _AlexaColorTemperatureController(self.entity)
        return controllers


# Untested.
class _ChannelInterface(_AlexaInterface):
    def controllers(self):
        return [_AlexaChannelController(self.device),]


class _LockInterface(_AlexaInterface):
    def controllers(self):
        return [_AlexaLockController(self.device),]


class _SwitchInterface(_AlexaInterface):
    def controllers(self):
        return [_AlexaPowerController(self.device),]


class _SceneInterface(_AlexaInterface):
    def controllers(self):
        return [_AlexaPowerController(self.device),]
