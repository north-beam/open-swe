import asyncio
import json
from typing import Any

from ..utils.datadog import (
    get_monitor_detail,
    list_dashboards,
    list_hosts,
    list_incidents,
    list_monitors,
    query_metrics,
    search_logs,
)

_RESOURCE_HANDLERS = {
    "monitors": list_monitors,
    "monitor_detail": get_monitor_detail,
    "metrics": query_metrics,
    "logs": search_logs,
    "incidents": list_incidents,
    "dashboards": list_dashboards,
    "hosts": list_hosts,
}

_VALID_TYPES = sorted(_RESOURCE_HANDLERS.keys())


def datadog_lookup(
    resource_type: str,
    query: str = "",
) -> dict[str, Any]:
    """Look up read-only Datadog observability information.

    Use this tool when you need to inspect monitors, metrics, logs, incidents,
    dashboards, or hosts in Datadog to diagnose issues, understand alerting
    state, or gather context about system health. All operations are strictly
    read-only.

    **When to use:**
    - A user asks about alerting monitors, their status, or configuration.
    - You need to check recent logs for errors in a service.
    - You need to look at metric timeseries data for a host or service.
    - You want to list incidents or dashboards for context.
    - You need host information (status, tags, agent version).

    **Important:** This tool never modifies Datadog resources.

    **GCP Cloud SQL metric examples** (use these tag formats):
    - CPU: `avg:gcp.cloudsql.database.cpu.utilization{database_id:north-beam-io:nb-prod-operational-db}`
    - Memory: `avg:gcp.cloudsql.database.memory.utilization{database_id:north-beam-io:nb-prod-operational-db}`
    - Connections: `avg:gcp.cloudsql.database.network.connections{database_id:north-beam-io:nb-prod-operational-db}`
    - Disk: `avg:gcp.cloudsql.database.disk.utilization{database_id:north-beam-io:nb-prod-operational-db}`
    - By project: `avg:gcp.cloudsql.database.cpu.utilization{project_id:north-beam-io}`

    **GCP GKE metric examples:**
    - CPU: `avg:gcp.container.cpu.core_usage_time{cluster_name:enterprise-ai}`
    - Memory: `avg:gcp.container.memory.used_bytes{cluster_name:enterprise-ai}`

    **General metric examples:**
    - System CPU: `avg:system.cpu.user{host:myhost}`
    - By tag: `avg:some.metric{env:prod,service:my-app}`

    Args:
        resource_type: The kind of Datadog resource to look up. Must be one of:
            "monitors" — list monitors (query filters by monitor tags),
            "monitor_detail" — get a single monitor (query = monitor ID),
            "metrics" — query timeseries (query = Datadog metric query, see
                examples above for GCP Cloud SQL/GKE tag formats),
            "logs" — search logs (query = log search query, e.g.
                "service:my-app status:error"),
            "incidents" — list recent incidents (query is ignored),
            "dashboards" — list dashboards (query filters results by substring),
            "hosts" — list hosts (query filters by host search string).
        query: The query or identifier string. Its meaning depends on
            resource_type — see above for details. Optional for some types.

    Returns:
        Dictionary with:
        - success (bool): Whether the lookup succeeded.
        - resource_type (str): The resource type that was queried.
        - count (int): Number of results returned.
        - results (list | dict | None): The resource data.
        - error (str | None): Error message if the lookup failed.
    """
    if resource_type not in _RESOURCE_HANDLERS:
        return {
            "success": False,
            "resource_type": resource_type,
            "count": 0,
            "results": [],
            "error": (
                f"Invalid resource_type '{resource_type}'. "
                f"Must be one of: {', '.join(_VALID_TYPES)}"
            ),
        }

    handler = _RESOURCE_HANDLERS[resource_type]

    try:
        # Build kwargs based on resource type
        if resource_type == "monitors":
            results = asyncio.run(
                asyncio.to_thread(handler, query=query or None)
            )
        elif resource_type == "monitor_detail":
            if not query:
                return {
                    "success": False,
                    "resource_type": resource_type,
                    "count": 0,
                    "results": None,
                    "error": "query must be a monitor ID for resource_type 'monitor_detail'",
                }
            result = asyncio.run(asyncio.to_thread(handler, monitor_id=query))
            if result is None:
                return {
                    "success": False,
                    "resource_type": resource_type,
                    "count": 0,
                    "results": None,
                    "error": f"Monitor {query} not found or lookup failed",
                }
            return {
                "success": True,
                "resource_type": resource_type,
                "count": 1,
                "results": result,
                "error": None,
            }
        elif resource_type == "metrics":
            if not query:
                return {
                    "success": False,
                    "resource_type": resource_type,
                    "count": 0,
                    "results": [],
                    "error": "query must be a Datadog metric query string for resource_type 'metrics'",
                }
            results = asyncio.run(asyncio.to_thread(handler, query=query))
        elif resource_type == "logs":
            if not query:
                return {
                    "success": False,
                    "resource_type": resource_type,
                    "count": 0,
                    "results": [],
                    "error": "query must be a log search query for resource_type 'logs'",
                }
            results = asyncio.run(asyncio.to_thread(handler, query=query))
        elif resource_type == "incidents":
            results = asyncio.run(asyncio.to_thread(handler))
        elif resource_type == "dashboards":
            results = asyncio.run(asyncio.to_thread(handler))
            # Apply optional substring filter for dashboards
            if query:
                query_lower = query.lower()
                results = [
                    item
                    for item in results
                    if query_lower in json.dumps(item, default=str).lower()
                ]
        elif resource_type == "hosts":
            results = asyncio.run(
                asyncio.to_thread(handler, query=query or None)
            )
        else:
            results = []
    except Exception as exc:
        return {
            "success": False,
            "resource_type": resource_type,
            "count": 0,
            "results": [],
            "error": f"Datadog lookup failed: {exc!s}",
        }

    return {
        "success": True,
        "resource_type": resource_type,
        "count": len(results) if isinstance(results, list) else 1,
        "results": results,
        "error": None,
    }
