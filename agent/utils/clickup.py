"""ClickUp API utilities."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os

import httpx

logger = logging.getLogger(__name__)

CLICKUP_API_TOKEN = os.environ.get("CLICKUP_API_TOKEN", "")
CLICKUP_WEBHOOK_SECRET = os.environ.get("CLICKUP_WEBHOOK_SECRET", "")


def verify_clickup_signature(body: bytes, signature: str, secret: str) -> bool:
    """Verify the ClickUp webhook signature.

    ClickUp signs webhooks with HMAC-SHA256 using the webhook secret.
    """
    if not secret:
        logger.warning("CLICKUP_WEBHOOK_SECRET is not configured — rejecting webhook")
        return False

    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


async def comment_on_clickup_task(task_id: str, comment_body: str) -> bool:
    """Post a comment to a ClickUp task.

    Args:
        task_id: The ClickUp task ID.
        comment_body: Plain text or markdown comment to post.

    Returns:
        True if successful, False otherwise.
    """
    if not CLICKUP_API_TOKEN:
        logger.warning("CLICKUP_API_TOKEN not set, cannot post comment")
        return False

    url = f"https://api.clickup.com/api/v2/task/{task_id}/comment"
    headers = {
        "Authorization": CLICKUP_API_TOKEN,
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                url,
                headers=headers,
                json={"comment_text": comment_body},
                timeout=15,
            )
            if response.status_code == 200:
                logger.info("Posted comment to ClickUp task %s", task_id)
                return True
            logger.warning(
                "ClickUp comment API returned %d: %s",
                response.status_code,
                response.text[:200],
            )
            return False
        except Exception:
            logger.exception("Failed to post comment to ClickUp task %s", task_id)
            return False


async def fetch_clickup_task(task_id: str) -> dict | None:
    """Fetch full task details from ClickUp.

    Returns the task dict or None on failure.
    """
    if not CLICKUP_API_TOKEN:
        logger.warning("CLICKUP_API_TOKEN not set, cannot fetch task")
        return None

    url = f"https://api.clickup.com/api/v2/task/{task_id}"
    headers = {"Authorization": CLICKUP_API_TOKEN}

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, timeout=15)
            if response.status_code == 200:
                return response.json()
            logger.warning(
                "ClickUp task API returned %d for task %s",
                response.status_code,
                task_id,
            )
            return None
        except Exception:
            logger.exception("Failed to fetch ClickUp task %s", task_id)
            return None


async def fetch_clickup_task_comments(task_id: str) -> list[dict]:
    """Fetch comments on a ClickUp task.

    Returns a list of comment dicts, newest first.
    """
    if not CLICKUP_API_TOKEN:
        return []

    url = f"https://api.clickup.com/api/v2/task/{task_id}/comment"
    headers = {"Authorization": CLICKUP_API_TOKEN}

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, headers=headers, timeout=15)
            if response.status_code == 200:
                return response.json().get("comments", [])
            return []
        except Exception:
            logger.exception("Failed to fetch comments for ClickUp task %s", task_id)
            return []


async def add_clickup_reaction(comment_id: str, task_id: str) -> bool:
    """React to a ClickUp comment (ClickUp doesn't have reactions on comments,
    so we post a brief acknowledgment reply instead).
    """
    return await comment_on_clickup_task(task_id, "👀 Working on it...")
