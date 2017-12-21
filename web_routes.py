from twisted.internet.defer import inlineCallbacks

from yombo.core.exceptions import YomboWarning
from yombo.core.log import get_logger
from yombo.lib.webinterface.auth import require_auth

logger = get_logger("modules.amazonalexa.web_routes")

def module_amazonalexa_routes(webapp):
    """
    Adds routes to the webinterface module.

    :param webapp: A pointer to the webapp, it's used to setup routes.
    :return:
    """
    with webapp.subroute("/modules_settings") as webapp:

        def root_breadcrumb(webinterface, request):
            webinterface.add_breadcrumb(request, "/?", "Home")
            webinterface.add_breadcrumb(request, "/modules/index", "Modules")
            webinterface.add_breadcrumb(request, "/modules_settings/amazonalexa/index", "Amazon Alexa")

        @webapp.route("/amazonalexa", methods=['GET'])
        @require_auth()
        def page_module_amazonalexa_get(webinterface, request, session):
            return webinterface.redirect(request, '/modules/amazonalexa/index')

        @webapp.route("/amazonalexa/index", methods=['GET'])
        @require_auth()
        def page_module_amazonalexa_index_get(webinterface, request, session):
            amazonalexa = webinterface._Modules['amazonalexa']

            page = webinterface.webapp.templates.get_template('modules/amazonalexa/web/index.html')
            root_breadcrumb(webinterface, request)

            return page.render(alerts=webinterface.get_alerts(),
                               amazonalexa=amazonalexa,
                               )

