"""Mapping of GitHub usernames to email addresses.

Falls back to checking GitHub org membership via the API when a user
isn't in the static map. Allowed orgs are read from ALLOWED_GITHUB_ORGS.
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

# Static map for any users that need explicit overrides
GITHUB_USER_EMAIL_MAP: dict[str, str] = {}

# Cache org membership checks to avoid repeated API calls
_org_member_cache: dict[str, str] = {}

_ALLOWED_ORGS: list[str] = [
    org.strip().lower()
    for org in os.environ.get("ALLOWED_GITHUB_ORGS", "").split(",")
    if org.strip()
]


async def _check_org_membership(github_login: str) -> str | None:
    """Check if a GitHub user is a member of any allowed org.

    Uses the GitHub App installation token to query the API.
    Returns a synthetic email if the user is a member, None otherwise.
    """
    # Avoid circular import
    from agent.utils.auth import get_github_app_installation_token

    if not _ALLOWED_ORGS:
        return None

    token = await get_github_app_installation_token()
    if not token:
        logger.warning("No GitHub App token available for org membership check")
        return None

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }

    async with httpx.AsyncClient() as client:
        for org in _ALLOWED_ORGS:
            try:
                resp = await client.get(
                    f"https://api.github.com/orgs/{org}/members/{github_login}",
                    headers=headers,
                    timeout=10,
                )
                if resp.status_code == 204:
                    # 204 = user is a member
                    email = f"{github_login}@{org}.github"
                    logger.info(
                        "GitHub user '%s' confirmed as member of org '%s'",
                        github_login,
                        org,
                    )
                    return email
            except Exception:
                logger.warning(
                    "Failed to check org membership for '%s' in '%s'",
                    github_login,
                    org,
                    exc_info=True,
                )

    return None


async def resolve_github_user_email(github_login: str) -> str:
    """Resolve a GitHub username to an email.

    Checks the static map first, then falls back to org membership check.
    Returns empty string if the user is not authorized.
    """
    # 1. Check static map
    email = GITHUB_USER_EMAIL_MAP.get(github_login, "")
    if email:
        return email

    # 2. Check cache
    if github_login in _org_member_cache:
        return _org_member_cache[github_login]

    # 3. Check org membership via API
    email = await _check_org_membership(github_login) or ""
    _org_member_cache[github_login] = email

    if not email:
        logger.warning(
            "GitHub user '%s' not in static map and not a member of allowed orgs",
            github_login,
        )

    return email
