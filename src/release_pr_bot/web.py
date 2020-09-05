from sanic import Sanic, response
import aiohttp

def create_app():
  app = Sanic(__name__)

  @app.listener('before_server_start')
  async def init(app, loop):
      app.aiohttp_session = aiohttp.ClientSession(loop=loop)
  
  @app.route("/")
  async def index(request):
    return response.text("hallo")
  
  return app