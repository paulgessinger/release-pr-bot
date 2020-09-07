import base64
from typing import Optional, List
from gidgethub.abc import GitHubAPI

from semantic_release.errors import UnknownCommitMessageStyleError
from semantic_release.history.logs import LEVELS
from semantic_release.history.parser_helpers import ParsedCommit
from sanic.log import logger

from semantic_release.history import angular_parser, get_new_version as _get_new_version
from semantic_release.changelog import current_changelog_components

_default_parser = angular_parser
get_new_version = _get_new_version



def evaluate_version_bump(commits: List["Commit"], commit_parser=_default_parser) -> Optional[str]:
    """
    Adapted from: https://github.com/relekang/python-semantic-release/blob/master/semantic_release/history/logs.py#L22
    """
    bump = None

    changes = []
    commit_count = 0

    logger.debug("Processing commits to determine bump:")
    for commit in commits:
        logger.debug("- %s", commit)
        commit_count += 1
        # Attempt to parse this commit using the currently-configured parser
        try:
            message = commit_parser(commit.message)
            changes.append(message.bump)
        except UnknownCommitMessageStyleError as err:
            logger.debug(f"Ignoring UnknownCommitMessageStyleError: {err}")
            pass

    logger.debug(f"Commits found since last release: {commit_count}")

    if changes:
        # Select the largest required bump level from the commits we parsed
        level = max(changes)
        if level in LEVELS:
            bump = LEVELS[level]
        else:
            logger.warning(f"Unknown bump level {level}")

    return bump


async def get_current_version(gh: GitHubAPI, repo_url: str, ref: str):
    path = "version_number"
    url = f"{repo_url}/contents/{path}?ref={ref}"
    res = await gh.getitem(url)
    assert res["encoding"] == "base64"
    content = base64.b64decode(res["content"]).decode("utf8").strip()
    return content


def generate_changelog(commits, commit_parser=_default_parser) -> dict:
    """
    Modified from: https://github.com/relekang/python-semantic-release/blob/48972fb761ed9b0fb376fa3ad7028d65ff407ee6/semantic_release/history/logs.py#L78
    """
    # Additional sections will be added as new types are encountered
    changes: dict = {"breaking": []}

    logger.debug("Making changelog:")
    for commit in commits:
        logger.debug("- %s", commit)
        try:
            message: ParsedCommit = commit_parser(commit.message)
            if message.type not in changes:
                logger.debug(f"Creating new changelog section for {message.type} ")
                changes[message.type] = list()

            # Capialize the first letter of the message, leaving others as they were
            # (using str.capitalize() would make the other letters lowercase)
            capital_message = (
                message.descriptions[0][0].upper() + message.descriptions[0][1:]
            )
            changes[message.type].append((commit.sha, capital_message))

            if message.breaking_descriptions:
                # Copy breaking change descriptions into changelog
                for paragraph in message.breaking_descriptions:
                    changes["breaking"].append((commit.sha, paragraph))
            elif message.bump == 3:
                # Major, but no breaking descriptions, use commit subject instead
                changes["breaking"].append((commit.sha, message.descriptions[0]))

        except UnknownCommitMessageStyleError as err:
            logger.debug(f"Ignoring UnknownCommitMessageStyleError: {err}")
            pass

    return changes


def markdown_changelog(
    version: str, changelog: dict, header: bool = False,
) -> str:
    output = f"## v{version}\n" if header else ""

    for section, items in changelog.items():
        if len(items) == 0:
            continue
        # Add a header for this section
        output += "\n### {0}\n".format(section.capitalize())

        # Add each commit from the section in an unordered list
        for item in items:
            output += "* {0} ({1})\n".format(item[1], item[0])

    return output
