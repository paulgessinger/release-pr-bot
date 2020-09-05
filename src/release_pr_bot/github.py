
from gidgethub.routing import Router
from sanic.log import logger
from sanic import Sanic
from gidgethub.abc import GitHubAPI
from gidgethub.sansio import Event
import aiohttp

from .semver import (
    evaluate_version_bump,
    generate_changelog,
    get_current_version,
    get_new_version,
    markdown_changelog,
)

class Commit():
  sha: str
  message: str

  def __init__(self, sha:str, message: str):
    self.sha = sha
    self.message = self._normalize(message)
  
  @staticmethod
  def _normalize(message):
    message = message.replace("\r", "\n")
    return message

def create_router():
    router = Router()

    @router.register("pull_request")
    async def on_pr(event: Event, gh: GitHubAPI, app: Sanic):

        pr = event.data["pull_request"]
        logger.debug("Received pull_request event on PR%d", pr["number"])

        repo_url = event.data["repository"]["url"]
        logger.debug("Repo url is %s", repo_url)

        action = event.data["action"]
        if action not in ("opened", "edited", "synchronize"):
            logger.debug("Ignoring action %s", action)
            return

        if action == "edited" and event.data["sender"]["type"] == "Bot":
            logger.debug("Event triggered by bot, skipping")
            return

        if pr["merged"] == True:
            logger.debug("PR is already merged")
            return

        # explicit get on PR to trigger merge commit if available
        merge_commit_sha = None
        for _ in range(app.config.PR_GET_RETRIES):
            updated_pr = await gh.getitem(pr["url"])
            if updated_pr["merge_commit_sha"] is not None:
                merge_commit_sha = updated_pr["merge_commit_sha"]
                pr = updated_pr
                break
            await aiohttp.sleep(app.config.PR_GET_SLEEP)

        if merge_commit_sha is None:
            logger.debug(
                "Unable to get merge commit sha after %d attempts, probably conflicts. Nothing we can do here",
                app.config.PR_GET_RETRIES,
            )

        logger.debug("Merge commit sha is %s", merge_commit_sha)

        base_sha = pr["base"]["sha"]
        base_ref = pr["base"]["ref"]
        logger.debug("Base sha is %s", base_sha)

        commits_iter = gh.getiter(f"{repo_url}/commits", {"sha": merge_commit_sha})

        commits = []
        async for commit in commits_iter:
            # logger.debug("%s", commit)
            if commit["sha"] == base_sha:
                break
            commit_message = commit["commit"]["message"]
            commit_hash = commit["sha"]
            commits.append(Commit(commit_hash, commit_message))
            if len(commits) > app.config.MAX_COMMIT_NUMBER:
                raise RuntimeError("Too many commits to enumerate")

        logger.debug(
            "Found %d commits between merge commit and branch base", len(commits)
        )

        bump = evaluate_version_bump(commits)

        current_version = await get_current_version(gh, repo_url, base_ref)
        logger.debug("Current version is: %s", current_version)
        logger.debug("Have bump: %s", bump)
        next_version = get_new_version(current_version, bump)
        logger.debug("Next version is: %s", next_version)

        changelog = generate_changelog(commits)
        md = markdown_changelog(
            current_version,
            changelog,
            header=False,
        )

        body = ""

        body += f"# {current_version} -> {next_version}"

        body += "\n"
        body += md

        title = f"Release: {current_version} -> {next_version}"

        logger.debug("Body:\n\n%s\n\n", body)

        await gh.post(pr["url"], data={"body": body, "title": title})

    return router
