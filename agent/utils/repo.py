"""Utilities for extracting repository configuration from text."""

from __future__ import annotations

import os
import re

_DEFAULT_REPO_OWNER = os.environ.get("DEFAULT_REPO_OWNER", "langchain-ai")


def extract_repo_from_text(text: str, default_owner: str | None = None) -> dict[str, str] | None:
    """Extract owner/name repo config from text containing repo: syntax or GitHub URLs.

    Checks for explicit ``repo:owner/name`` or ``repo owner/name`` first, then
    falls back to GitHub URL extraction.

    Returns:
        A dict with ``owner`` and ``name`` keys, or ``None`` if no repo found.
    """
    if default_owner is None:
        default_owner = _DEFAULT_REPO_OWNER
    owner: str | None = None
    name: str | None = None

    # Require "repo:" with colon (not "repo " with space) to avoid matching
    # natural language like "check the repo and see..."
    repo_match = re.search(r"repo:\s*([a-zA-Z0-9_.\-]+/[a-zA-Z0-9_.\-]+)", text)
    if repo_match:
        value = repo_match.group(1).rstrip("/")
        owner, name = value.split("/", 1)
    elif "repo:" in text:
        # repo:name (without owner)
        match = re.search(r"repo:\s*([a-zA-Z0-9_.\-]+)", text)
        if match:
            owner = default_owner
            name = match.group(1)

    if not owner or not name:
        github_match = re.search(r"github\.com/([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)", text)
        if github_match:
            owner, name = github_match.group(1).split("/", 1)

    if owner and name:
        return {"owner": owner, "name": name}
    return None
