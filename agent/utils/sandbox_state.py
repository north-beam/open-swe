"""Shared sandbox state used by server and middleware."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from langgraph.config import get_config

from .sandbox import create_sandbox

logger = logging.getLogger(__name__)

# Thread ID -> SandboxBackend mapping, shared between server.py and middleware
SANDBOX_BACKENDS: dict[str, Any] = {}

# Thread ID -> last-activity epoch timestamp
SANDBOX_LAST_ACTIVE: dict[str, float] = {}

# Idle timeout in seconds (15 minutes)
SANDBOX_IDLE_TIMEOUT = 15 * 60


def touch_sandbox(thread_id: str) -> None:
    """Update last-activity timestamp for a sandbox and annotate the pod."""
    SANDBOX_LAST_ACTIVE[thread_id] = time.time()
    backend = SANDBOX_BACKENDS.get(thread_id)
    if backend and hasattr(backend, "_pod_name"):
        try:
            _annotate_pod_last_active(backend._pod_name, backend._namespace)
        except Exception:
            logger.debug("Failed to annotate sandbox pod %s", getattr(backend, "_pod_name", "?"))


def _annotate_pod_last_active(pod_name: str, namespace: str) -> None:
    """Set last-active annotation on a sandbox pod."""
    from kubernetes import client, config

    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()

    v1 = client.CoreV1Api()
    body = {"metadata": {"annotations": {"open-swe/last-active": str(int(time.time()))}}}
    v1.patch_namespaced_pod(name=pod_name, namespace=namespace, body=body)


async def get_sandbox_id_from_metadata(thread_id: str) -> str | None:
    """Fetch sandbox_id from thread metadata."""
    try:
        config = get_config()
    except Exception:
        logger.exception("Failed to read thread metadata for sandbox")
        return None
    return config.get("metadata", {}).get("sandbox_id")


async def get_sandbox_backend(thread_id: str) -> Any | None:
    """Get sandbox backend from cache, or connect using thread metadata."""
    sandbox_backend = SANDBOX_BACKENDS.get(thread_id)
    if sandbox_backend:
        touch_sandbox(thread_id)
        return sandbox_backend

    sandbox_id = await get_sandbox_id_from_metadata(thread_id)
    if not sandbox_id:
        raise ValueError(f"Missing sandbox_id in thread metadata for {thread_id}")

    sandbox_backend = await asyncio.to_thread(create_sandbox, sandbox_id)
    SANDBOX_BACKENDS[thread_id] = sandbox_backend
    touch_sandbox(thread_id)
    return sandbox_backend


def get_sandbox_backend_sync(thread_id: str) -> Any | None:
    """Sync wrapper for get_sandbox_backend."""
    return asyncio.run(get_sandbox_backend(thread_id))
