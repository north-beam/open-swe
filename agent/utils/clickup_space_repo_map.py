"""Map ClickUp spaces/folders/lists to GitHub repositories.

Configure CLICKUP_SPACE_TO_REPO with your space/folder/list names
pointing to the GitHub owner/name that open-swe should work in.

When no mapping is found, falls back to searching the forge-context
index in north-beam/nb-forge for a matching repo based on task text.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

CLICKUP_SPACE_TO_REPO: dict[str, dict[str, Any] | dict[str, str]] = {
    # Add your space→repo mappings here. Example:
    # "Engineering": {
    #     "folders": {
    #         "Backend": {"owner": "north-beam", "name": "backend"},
    #         "Frontend": {"owner": "north-beam", "name": "frontend"},
    #     },
    #     "default": {"owner": "north-beam", "name": "monorepo"},
    # },
}

# GitHub org for forge-context lookup
_FORGE_CONTEXT_OWNER = "north-beam"
_FORGE_CONTEXT_REPO = "nb-forge"
_FORGE_CONTEXT_PATH = "forge-context"

# Cache the forge-context index so we only fetch it once per process
_forge_context_cache: list[dict[str, str]] | None = None


async def _fetch_forge_context_index() -> list[dict[str, str]]:
    """Fetch the list of forge-context files from GitHub.

    Returns a list of dicts with 'name' (filename without .md) and 'download_url'.
    """
    global _forge_context_cache
    if _forge_context_cache is not None:
        return _forge_context_cache

    github_token = os.environ.get("GITHUB_TOKEN", "")
    # Try GitHub App installation token from the environment
    if not github_token:
        from .github_app import get_github_app_installation_token

        try:
            github_token = await get_github_app_installation_token()
        except Exception:
            logger.warning("Could not get GitHub token for forge-context lookup")

    url = f"https://api.github.com/repos/{_FORGE_CONTEXT_OWNER}/{_FORGE_CONTEXT_REPO}/contents/{_FORGE_CONTEXT_PATH}"
    headers = {"Accept": "application/vnd.github.v3+json"}
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, timeout=15)
            if response.status_code != 200:
                logger.warning("Failed to fetch forge-context index: %d", response.status_code)
                _forge_context_cache = []
                return []

            entries = []
            for item in response.json():
                if item.get("name", "").endswith(".md"):
                    entries.append({
                        "name": item["name"].removesuffix(".md").lower(),
                        "download_url": item.get("download_url", ""),
                    })

            _forge_context_cache = entries
            logger.info("Loaded %d forge-context entries", len(entries))
            return entries
        except Exception:
            logger.exception("Error fetching forge-context index")
            _forge_context_cache = []
            return []


async def resolve_repo_from_forge_context(
    task_text: str, default_owner: str = "north-beam"
) -> dict[str, str] | None:
    """Try to match task text against forge-context filenames.

    Performs a simple keyword match — if the task mentions a project name
    that corresponds to a forge-context file, returns that as the repo.

    Args:
        task_text: The task title + description to match against.
        default_owner: GitHub org owner for matched repos.

    Returns:
        A dict with 'owner' and 'name', or None if no match.
    """
    entries = await _fetch_forge_context_index()
    if not entries:
        return None

    text_lower = task_text.lower()

    # Score each entry by how well its name matches the task text
    best_match = None
    best_score = 0

    for entry in entries:
        name = entry["name"]
        # Skip very short names to avoid false positives
        if len(name) < 3:
            continue

        # Check if the forge-context name appears in the task text
        # Use the raw name and common variations (with hyphens replaced by spaces)
        variations = [name, name.replace("-", " "), name.replace("-", "")]
        for variant in variations:
            if variant in text_lower:
                score = len(variant)  # Longer matches are better
                if score > best_score:
                    best_score = score
                    best_match = name
                    break

    if best_match:
        logger.info("Forge-context match: '%s' for task text", best_match)
        return {"owner": default_owner, "name": best_match}

    return None
