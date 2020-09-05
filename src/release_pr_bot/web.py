import logging

from sanic import Sanic, response
import aiohttp
from gidgethub import sansio
from gidgethub.apps import get_installation_access_token
from gidgethub import aiohttp as gh_aiohttp
import cachetools
from sanic.log import logger

from . import config
from .github import create_router


def create_app():

    app = Sanic(__name__)
    app.config.from_object(config)
    # app.logger = logging.getLogger(__name__)
    # if app.debug:
    # app.logger.setLevel(logging.DEBUG)

    app.cache = cachetools.LRUCache(maxsize=500)
    app.github_router = create_router()

    @app.listener("before_server_start")
    async def init(app, loop):
        logger.debug("Creating aiohttp session")
        app.aiohttp_session = aiohttp.ClientSession(loop=loop)

    @app.route("/")
    async def index(request):
        return response.text("hallo")

    @app.route("/webhook", methods=["POST"])
    async def github(request):
        logger.debug("Webhook received")
        event = sansio.Event.from_http(
            request.headers, request.body, secret=app.config.WEBHOOK_SECRET
        )

        if event.event == "ping":
            return response.empty(200)

        assert "installation" in event.data
        installation_id = event.data["installation"]["id"]
        logger.debug("Installation id: %s", installation_id)

        gh_pre = gh_aiohttp.GitHubAPI(app.aiohttp_session, __name__)
        access_token_response = await get_installation_access_token(
            gh_pre,
            installation_id=installation_id,
            app_id=app.config.APP_ID,
            private_key=app.config.PRIVATE_KEY,
        )

        token = access_token_response["token"]

        gh = gh_aiohttp.GitHubAPI(
            app.aiohttp_session, __name__, oauth_token=token, cache=app.cache
        )

        logger.debug("Dispatching event %s", event.event)
        await app.github_router.dispatch(event, gh, app=app)

        return response.empty(200)

    return app
