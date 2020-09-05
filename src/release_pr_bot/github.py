import typing

from gidgethub.routing import Router
from sanic.log import logger

from sanic import Sanic
from gidgethub.abc import GitHubAPI
from gidgethub.sansio import Event


def create_router():
  router = Router()

  @router.register("pull_request")
  async def on_pr(event: Event, gh: GitHubAPI, app: Sanic):
    logger.debug("Received pull_request event")

    if event.data["action"] == "opened":
      # pr_id = event.data["pull_request"]["id"]
      issue_url = event.data["pull_request"]["issue_url"]
      logger.debug("Posting comment on %s", issue_url)
      await gh.post(f"{issue_url}/comments", data={"body": "Hello there!"})

  return router