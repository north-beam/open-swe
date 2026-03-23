"""Datadog API read-only lookup utilities.

Uses the datadog-api-client Python SDK with DD_API_KEY and DD_APP_KEY
environment variables for authentication. All operations are strictly read-only.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

DD_API_KEY = os.environ.get("DD_API_KEY", "")
DD_APP_KEY = os.environ.get("DD_APP_KEY", "")
DD_SITE = os.environ.get("DD_SITE", "us5.datadoghq.com")

# Default log search window: last 1 hour
_DEFAULT_LOG_WINDOW_SECONDS = 3600


def _get_configuration():
    """Build a Datadog API client configuration from env vars."""
    from datadog_api_client import Configuration

    if not DD_API_KEY or not DD_APP_KEY:
        raise RuntimeError(
            "DD_API_KEY and DD_APP_KEY environment variables must be set"
        )

    configuration = Configuration()
    configuration.server_variables["site"] = DD_SITE
    configuration.api_key["apiKeyAuth"] = DD_API_KEY
    configuration.api_key["appKeyAuth"] = DD_APP_KEY
    return configuration


# ---------------------------------------------------------------------------
# Monitors
# ---------------------------------------------------------------------------


def list_monitors(query: str | None = None) -> list[dict[str, Any]]:
    """List monitors, optionally filtered by a query string.

    Args:
        query: Optional monitor search query (e.g. "type:metric" or a tag).

    Returns:
        List of monitor summary dicts.
    """
    from datadog_api_client import ApiClient
    from datadog_api_client.v1.api.monitors_api import MonitorsApi

    configuration = _get_configuration()

    try:
        with ApiClient(configuration) as api_client:
            api = MonitorsApi(api_client)
            kwargs: dict[str, Any] = {}
            if query:
                kwargs["monitor_tags"] = query
            monitors = api.list_monitors(**kwargs)
    except Exception:
        logger.exception("Failed to list Datadog monitors")
        return []

    results: list[dict[str, Any]] = []
    for mon in monitors:
        results.append(
            {
                "id": mon.id,
                "name": mon.name,
                "type": mon.type.value if mon.type else None,
                "query": mon.query,
                "overall_state": (
                    mon.overall_state.value if mon.overall_state else None
                ),
                "message": mon.message,
                "tags": list(mon.tags) if mon.tags else [],
                "created": mon.created.isoformat() if mon.created else None,
                "modified": mon.modified.isoformat() if mon.modified else None,
            }
        )
    return results


def get_monitor_detail(monitor_id: str) -> dict[str, Any] | None:
    """Get detailed information for a single monitor by ID.

    Args:
        monitor_id: The numeric monitor ID as a string.

    Returns:
        Monitor detail dict, or None on failure.
    """
    from datadog_api_client import ApiClient
    from datadog_api_client.v1.api.monitors_api import MonitorsApi

    configuration = _get_configuration()

    try:
        with ApiClient(configuration) as api_client:
            api = MonitorsApi(api_client)
            mon = api.get_monitor(monitor_id=int(monitor_id))
    except Exception:
        logger.exception("Failed to get Datadog monitor %s", monitor_id)
        return None

    return {
        "id": mon.id,
        "name": mon.name,
        "type": mon.type.value if mon.type else None,
        "query": mon.query,
        "overall_state": mon.overall_state.value if mon.overall_state else None,
        "message": mon.message,
        "tags": list(mon.tags) if mon.tags else [],
        "options": {
            "thresholds": (
                {
                    "critical": getattr(mon.options.thresholds, "critical", None),
                    "warning": getattr(mon.options.thresholds, "warning", None),
                }
                if mon.options and mon.options.thresholds
                else None
            ),
            "notify_no_data": (
                mon.options.notify_no_data if mon.options else None
            ),
            "evaluation_delay": (
                mon.options.evaluation_delay if mon.options else None
            ),
        },
        "created": mon.created.isoformat() if mon.created else None,
        "modified": mon.modified.isoformat() if mon.modified else None,
        "creator": (
            {"name": mon.creator.name, "email": mon.creator.email}
            if mon.creator
            else None
        ),
    }


# ---------------------------------------------------------------------------
# Metrics (timeseries query)
# ---------------------------------------------------------------------------


def query_metrics(
    query: str,
    from_seconds_ago: int = 3600,
) -> list[dict[str, Any]]:
    """Query metric timeseries data.

    Args:
        query: Datadog metric query string
            (e.g. "avg:system.cpu.user{host:myhost}").
        from_seconds_ago: How far back to query, in seconds. Defaults to 3600 (1h).

    Returns:
        List of timeseries dicts with metric name, scope, and point data.
    """
    from datadog_api_client import ApiClient
    from datadog_api_client.v1.api.metrics_api import MetricsApi

    configuration = _get_configuration()
    now = int(datetime.now(timezone.utc).timestamp())
    start = now - from_seconds_ago

    try:
        with ApiClient(configuration) as api_client:
            api = MetricsApi(api_client)
            response = api.query_metrics(
                _from=start,
                to=now,
                query=query,
            )
    except Exception:
        logger.exception("Failed to query Datadog metrics: %s", query)
        return []

    results: list[dict[str, Any]] = []
    for series in response.series or []:
        points = []
        for point in series.pointlist or []:
            points.append(
                {
                    "timestamp": point[0],
                    "value": point[1],
                }
            )
        results.append(
            {
                "metric": series.metric,
                "display_name": series.display_name,
                "scope": series.scope,
                "unit": (
                    series.unit[0].get("name") if series.unit else None
                ),
                "point_count": len(points),
                "points": points[-50:],  # Cap to last 50 points
            }
        )
    return results


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------


def search_logs(
    query: str,
    from_seconds_ago: int = _DEFAULT_LOG_WINDOW_SECONDS,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Search logs with a query string.

    Args:
        query: Datadog log search query (e.g. "service:my-app status:error").
        from_seconds_ago: How far back to search. Defaults to 3600 (1h).
        limit: Maximum number of log entries to return. Defaults to 50.

    Returns:
        List of log entry dicts.
    """
    from datadog_api_client import ApiClient
    from datadog_api_client.v2.api.logs_api import LogsApi
    from datadog_api_client.v2.model.logs_list_request import LogsListRequest
    from datadog_api_client.v2.model.logs_list_request_page import (
        LogsListRequestPage,
    )
    from datadog_api_client.v2.model.logs_query_filter import LogsQueryFilter
    from datadog_api_client.v2.model.logs_sort import LogsSort

    configuration = _get_configuration()
    now = datetime.now(timezone.utc)
    start = datetime.fromtimestamp(
        now.timestamp() - from_seconds_ago, tz=timezone.utc
    )

    body = LogsListRequest(
        filter=LogsQueryFilter(
            query=query,
            _from=start.isoformat(),
            to=now.isoformat(),
        ),
        sort=LogsSort.TIMESTAMP_DESCENDING,
        page=LogsListRequestPage(limit=min(limit, 100)),
    )

    try:
        with ApiClient(configuration) as api_client:
            api = LogsApi(api_client)
            response = api.list_logs(body=body)
    except Exception:
        logger.exception("Failed to search Datadog logs: %s", query)
        return []

    results: list[dict[str, Any]] = []
    for log in response.data or []:
        attrs = log.attributes
        results.append(
            {
                "id": log.id,
                "timestamp": (
                    attrs.timestamp.isoformat() if attrs and attrs.timestamp else None
                ),
                "host": attrs.host if attrs else None,
                "service": attrs.service if attrs else None,
                "status": attrs.status if attrs else None,
                "message": (
                    attrs.message[:2000] if attrs and attrs.message else None
                ),
                "tags": list(attrs.tags) if attrs and attrs.tags else [],
            }
        )
    return results


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------


def list_incidents() -> list[dict[str, Any]]:
    """List recent incidents.

    Returns:
        List of incident summary dicts.
    """
    from datadog_api_client import ApiClient
    from datadog_api_client.v2.api.incidents_api import IncidentsApi

    configuration = _get_configuration()
    configuration.unstable_operations["list_incidents"] = True

    try:
        with ApiClient(configuration) as api_client:
            api = IncidentsApi(api_client)
            response = api.list_incidents()
    except Exception:
        logger.exception("Failed to list Datadog incidents")
        return []

    results: list[dict[str, Any]] = []
    for incident in response.data or []:
        attrs = incident.attributes
        results.append(
            {
                "id": incident.id,
                "title": attrs.title if attrs else None,
                "status": attrs.status.value if attrs and attrs.status else None,
                "severity": (
                    attrs.severity.value if attrs and attrs.severity else None
                ),
                "created": (
                    attrs.created.isoformat() if attrs and attrs.created else None
                ),
                "modified": (
                    attrs.modified.isoformat() if attrs and attrs.modified else None
                ),
                "commander": (
                    attrs.commander.get("data", {}).get("attributes", {}).get("name")
                    if attrs and isinstance(getattr(attrs, "commander", None), dict)
                    else None
                ),
            }
        )
    return results


# ---------------------------------------------------------------------------
# Dashboards
# ---------------------------------------------------------------------------


def list_dashboards() -> list[dict[str, Any]]:
    """List all dashboards.

    Returns:
        List of dashboard summary dicts.
    """
    from datadog_api_client import ApiClient
    from datadog_api_client.v1.api.dashboards_api import DashboardsApi

    configuration = _get_configuration()

    try:
        with ApiClient(configuration) as api_client:
            api = DashboardsApi(api_client)
            response = api.list_dashboards()
    except Exception:
        logger.exception("Failed to list Datadog dashboards")
        return []

    results: list[dict[str, Any]] = []
    for dash in response.dashboards or []:
        results.append(
            {
                "id": dash.id,
                "title": dash.title,
                "description": dash.description,
                "url": dash.url,
                "layout_type": (
                    dash.layout_type.value if dash.layout_type else None
                ),
                "created_at": (
                    dash.created_at.isoformat() if dash.created_at else None
                ),
                "modified_at": (
                    dash.modified_at.isoformat() if dash.modified_at else None
                ),
                "author_handle": dash.author_handle,
            }
        )
    return results


# ---------------------------------------------------------------------------
# Hosts
# ---------------------------------------------------------------------------


def list_hosts(query: str | None = None) -> list[dict[str, Any]]:
    """List hosts, optionally filtered by a query.

    Args:
        query: Optional host filter string (e.g. "host:myhost" or "env:prod").

    Returns:
        List of host info dicts.
    """
    from datadog_api_client import ApiClient
    from datadog_api_client.v1.api.hosts_api import HostsApi

    configuration = _get_configuration()

    try:
        with ApiClient(configuration) as api_client:
            api = HostsApi(api_client)
            kwargs: dict[str, Any] = {}
            if query:
                kwargs["filter"] = query
            response = api.list_hosts(**kwargs)
    except Exception:
        logger.exception("Failed to list Datadog hosts")
        return []

    results: list[dict[str, Any]] = []
    for host in response.host_list or []:
        results.append(
            {
                "name": host.name,
                "id": host.id,
                "aliases": list(host.aliases) if host.aliases else [],
                "apps": list(host.apps) if host.apps else [],
                "is_muted": host.is_muted,
                "last_reported_time": host.last_reported_time,
                "up": host.up,
                "meta": {
                    "platform": (
                        host.meta.platform if host.meta else None
                    ),
                    "agent_version": (
                        host.meta.agent_version if host.meta else None
                    ),
                },
                "tags_by_source": (
                    {
                        src: list(tags)
                        for src, tags in host.tags_by_source.items()
                    }
                    if host.tags_by_source
                    else {}
                ),
            }
        )
    return results
