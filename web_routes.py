import json

from twisted.internet.defer import inlineCallbacks

from yombo.core.exceptions import YomboWarning
from yombo.lib.webinterface.routes.api_v1.__init__ import return_good, return_not_found, return_error, return_unauthorized
from yombo.core.log import get_logger
from yombo.lib.webinterface.auth import require_auth

logger = get_logger("modules.amazonalexa.web_routes")

def module_amazonalexa_routes(webapp):
    """
    Adds routes to the webinterface module.

    :param webapp: A pointer to the webapp, it's used to setup routes.
    :return:
    """
    with webapp.subroute("/module_settings") as webapp:

        def root_breadcrumb(webinterface, request):
            webinterface.add_breadcrumb(request, "/?", "Home")
            webinterface.add_breadcrumb(request, "/modules/index", "Modules")
            webinterface.add_breadcrumb(request, "/module_settings/amazonalexa/index", "Amazon Alexa")

        @webapp.route("/amazonalexa", methods=['GET'])
        @require_auth()
        def page_module_amazonalexa_get(webinterface, request, session):
            return webinterface.redirect(request, '/modules/amazonalexa/index')

        @webapp.route("/amazonalexa/index", methods=['GET'])
        @require_auth(access_platform="module_amazonalexa", access_item="*", access_action="manage")
        def page_module_amazonalexa_index_get(webinterface, request, session):
            amazonalexa = webinterface._Modules['AmazonAlexa']
            if amazonalexa.node is None:
                page = webinterface.webapp.templates.get_template(webinterface.wi_dir + '/pages/misc/stillbooting.html')
                root_breadcrumb(webinterface, request)
                return page.render(alerts=webinterface.get_alerts())

            page = webinterface.webapp.templates.get_template('modules/amazonalexa/web/index.html')
            root_breadcrumb(webinterface, request)

            return page.render(alerts=webinterface.get_alerts(),
                               amazonalexa=amazonalexa,
                               )

        @webapp.route("/amazonalexa/index", methods=['POST'])
        @require_auth(access_platform="module_amazonalexa", access_item="*", access_action="manage")
        def page_module_amazonalexa_index_post(webinterface, request, session):
            amazonalexa = webinterface._Modules['AmazonAlexa']
            if amazonalexa.node is None:
                page = webinterface.webapp.templates.get_template(webinterface.wi_dir + '/pages/misc/stillbooting.html')
                root_breadcrumb(webinterface, request)
                return page.render(alerts=webinterface.get_alerts())

            if 'json_output' in request.args:
                json_output = request.args.get('json_output', [{}])[0]
                json_output = json.loads(json_output)
                # print("json_out: %s" % json_output)
                if 'devices' not in amazonalexa.node.data:
                    amazonalexa.node.data['devices'] = {}
                if 'scenes' not in amazonalexa.node.data:
                    amazonalexa.node.data['scenes'] = {}
                devices_allowed = []
                scenes_allowed = []
                for item_id, value in json_output.items():
                    if value == '1':
                        if item_id.startswith("deviceid_"):
                            parts = item_id.split('_')
                            item_id = parts[1]
                            if item_id in amazonalexa._Devices:
                                devices_allowed.append(parts[1])
                        if item_id.startswith("sceneid_"):
                            parts = item_id.split('_')
                            item_id = parts[1]
                            if item_id in amazonalexa._Scenes:
                                scenes_allowed.append(parts[1])

                # if 'allowed' not in amazonalexa.node.data:
                #     amazonalexa.node.data['devices']['allowed'] = {}
                amazonalexa.node.data['devices']['allowed'] = devices_allowed
                amazonalexa.node.data['scenes']['allowed'] = scenes_allowed
                amazonalexa.discovery(save=False)

            page = webinterface.webapp.templates.get_template('modules/amazonalexa/web/index.html')
            root_breadcrumb(webinterface, request)

            return page.render(alerts=webinterface.get_alerts(),
                               amazonalexa=amazonalexa,
                               )

    with webapp.subroute("/api/v1/extended") as webapp:

        @webapp.route("/alexa/control", methods=['POST'])
        @require_auth(api=True)
        @inlineCallbacks
        def page_module_amazonalexa_control_post(webinterface, request, session):
            session.has_access('device', '*', 'control', raise_error=True)
            amazonalexa = webinterface._Modules['AmazonAlexa']
            try:
                data = json.loads(request.content.read())
            except:
                logger.info("Invalid JSON sent to us, discarding.")
                return return_error(message="invalid JSON sent", code=400)

            logger.debug("Receiving incoming request data: {data}", data=data)

            message = data['directive']
            results = yield amazonalexa.get_api_response(message)
            # print("Alex data control: %s - %s" % (type(data), data))
            print("sending results: %s" % json.dumps(results))
            return json.dumps(results)

        @webapp.route("/alexa/reportstate", methods=['POST'])
        @require_auth(api=True, access_platform="module_amazonalexa", access_item="*", access_action="api")
        def page_module_amazonalexa_reportstate_post(webinterface, request, session):
            amazonalexa = webinterface._Modules['AmazonAlexa']
            try:
                data = json.loads(request.content.read())
            except:
                return return_error(message="invalid JSON sent", code=400)

            # print("Alex data: %s - %s" % (type(data), data))
            return "yes"
