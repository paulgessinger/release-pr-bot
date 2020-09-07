import asyncio
from typing import Any, Dict, List
import http
import base64
import fnmatch

from gidgethub.routing import Router
from sanic.log import logger
from sanic import Sanic
from gidgethub.abc import GitHubAPI
from gidgethub.sansio import Event
from gidgethub import BadRequest
import aiohttp
from pydantic import BaseModel
import yaml

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

  def __str__(self):
    return f"Commit(sha='{self.sha[:8]}', message='{self.message}')"

class InstallConfig(BaseModel):
    branches: List[str] = []
    labels: List[str] = ["release"]


async def get_installation_config(gh: GitHubAPI, repo_url: str) -> InstallConfig:
    url = f"{repo_url}/contents/.github/release_pr.yml?ref=master"
    logger.debug("Getting installation config from: %s", url)
    try:
      res = await gh.getitem(url)
      assert res["encoding"] == "base64"
      content = base64.b64decode(res["content"]).decode("utf8").strip()
      data = yaml.safe_load(content)
      return InstallConfig(**data)
    except BadRequest as e:
      if e.status_code == http.HTTPStatus.NOT_FOUND:
        logger.debug("No config found, use defaults")
        return InstallConfig()
      raise e

def should_act_on_pr(event: Dict[str, Any], config: InstallConfig, app: Any) -> bool:
    pr = event.data["pull_request"]
    action = event.data["action"]

    if action not in ("opened", "edited", "synchronize", "labeled"):
        logger.debug("Ignoring action %s", action)
        return False

    if action == "edited" and event.data["sender"]["type"] == "Bot" and event.data["sender"]["login"].startswith(app.app_info["slug"]):
        logger.debug("Event triggered by me, %s. Skipping!", app.app_info["slug"])
        return False

    if pr["merged"] == True:
        logger.debug("PR is already merged")
        return False

    target_branch = pr["base"]["ref"]
    branch_ok = any((fnmatch.fnmatch(target_branch, p) for p in config.branches))
    logger.debug("Target branch '%s' matches any pattern %s: %s", target_branch, config.branches, branch_ok)
    
    labels = [label["name"] for label in pr["labels"]]
    has_label = any((l in config.labels for l in labels))
    logger.debug("PR labels: %s", labels)
    logger.debug("PR has any of configured labels %s: %s", config.labels, has_label)

    if not branch_ok and not has_label:
        return False

    return True

async def post_error(gh: GitHubAPI, pr: dict, error: str) -> None:
    await gh.post(pr["url"], data={"body": f":warning: **{error}**"})

def create_router():
    router = Router()

    @router.register("pull_request")
    async def on_pr(event: Event, gh: GitHubAPI, app: Sanic):

        pr = event.data["pull_request"]
        logger.debug("Received pull_request event on PR%d", pr["number"])

        action = event.data["action"]
        logger.debug("Action: %s", action)

        repo_url = event.data["repository"]["url"]
        logger.debug("Repo url is %s", repo_url)

        config = await get_installation_config(gh, repo_url)
        logger.debug("Config: %s", config)

        if not should_act_on_pr(event, config, app):
          return



        # explicit get on PR to trigger merge commit if available
        merge_commit_sha = None
        for _ in range(app.config.PR_GET_RETRIES):
            updated_pr = await gh.getitem(pr["url"])
            if updated_pr["merge_commit_sha"] is not None:
                merge_commit_sha = updated_pr["merge_commit_sha"]
                pr = updated_pr
                break
            await asyncio.sleep(app.config.PR_GET_SLEEP)

        if merge_commit_sha is None:
            logger.debug(
                "Unable to get merge commit sha after %d attempts, probably conflicts. Nothing we can do here",
                app.config.PR_GET_RETRIES,
            )

        logger.debug("Merge commit sha is %s", merge_commit_sha)

        # base_sha = pr["base"]["sha"]
        base_ref = pr["base"]["ref"]
        logger.debug("Base ref is %s", base_ref)
        current_version = await get_current_version(gh, repo_url, base_ref)
        current_tag = f"v{current_version}"
        logger.debug("Current version is: %s", current_version)

        all_tags = await gh.getitem(f"{repo_url}/tags")
        current_version_sha = None
        for tag in all_tags:
            if tag["name"] != current_tag:
                continue
            current_version_sha = tag["commit"]["sha"]
            break

        if current_version_sha is None:
            logger.error("Failed to find sha for current tag %s", current_tag)
            await post_error(gh, pr, f"Failed to find sha for current tag '{current_tag}'")
            return

        commits_iter = gh.getiter(f"{repo_url}/commits?sha={merge_commit_sha}")

        commits = []
        did_find_last_version = False
        async for commit in commits_iter:
            # logger.debug("%s", commit)
            if commit["sha"] == current_version_sha:
                did_find_last_version = True
                break
            commit_message = commit["commit"]["message"]
            commit_hash = commit["sha"]
            commits.append(Commit(commit_hash, commit_message))
            if len(commits) > app.config.MAX_COMMIT_NUMBER:
                raise RuntimeError("Too many commits to enumerate")
              
        if not did_find_last_version:
            msg = f"Unable to find commit for last version {current_tag} [{current_version_sha[:8]}], unable to generate changelog"
            logger.error(msg)
            await post_error(gh, pr, msg)
            return

        logger.debug(
            "Found %d commits between merge commit and branch base", len(commits)
        )

        bump = evaluate_version_bump(commits)

        logger.debug("Have bump: %s", bump)
        next_version = get_new_version(current_version, bump)
        logger.debug("Next version is: %s", next_version)

        existing_release = None
        try:
            existing_release = await gh.getitem(f"{repo_url}/releases/tags/v{next_version}")
            logger.debug("Existing release found!")
        except BadRequest as e:
            if e.status_code == http.HTTPStatus.NOT_FOUND:
                pass # this is what we want
            else:
                raise e

        changelog = generate_changelog(commits)
        md = markdown_changelog(
            current_version,
            changelog,
            header=False,
        )

        body = ""

        if existing_release is not None:
          if current_version == next_version:
              body += ":no_entry_sign: Merging this will not result in a new version (no `fix`, `feat` or breaking changes). I recommend **delaying** this PR until more changes accumulate."

          else:
              body += f":warning: **WARNING: A release for {next_version} already exists [here]({existing_release['html_url']})** :warning:"
              body += "\n"
              body += ":no_entry_sign: I recommend to **NOT** merge this and double check the target branch!"
        body += "\n\n"

        body += f"# {current_version} -> {next_version}"

        body += "\n"
        body += md

        title = f"Release: {current_version} -> {next_version}"

        logger.debug("Body:\n\n%s\n\n", body)

        await gh.post(pr["url"], data={"body": body, "title": title})

    return router
