import asyncio
from typing import Any

from ..utils.clickup import comment_on_clickup_task


def clickup_comment(comment_body: str, task_id: str) -> dict[str, Any]:
    """Post a comment to a ClickUp task.

    Use this tool to communicate progress and completion to stakeholders on ClickUp.

    **When to use:**
    - After calling `commit_and_open_pr`, post a comment on the ClickUp task to let
      stakeholders know the task is complete and include the PR link.
    - When answering a question or sharing an update (no code changes needed).

    Args:
        comment_body: Plain text or markdown comment to post to the ClickUp task.
        task_id: The ClickUp task ID to post the comment to.

    Returns:
        Dictionary with 'success' (bool) key.
    """
    success = asyncio.run(comment_on_clickup_task(task_id, comment_body))
    return {"success": success}
