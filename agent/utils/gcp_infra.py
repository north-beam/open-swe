"""GCP infrastructure read-only lookup utilities.

Uses Google Cloud Python SDK clients with Application Default Credentials
(workload identity on GKE). All operations are strictly read-only.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_PROJECT_ID = os.environ.get("GKE_PROJECT", "nb-enterprise-ai")


def _default_project(project_id: str | None) -> str:
    return project_id or DEFAULT_PROJECT_ID


# ---------------------------------------------------------------------------
# GKE Clusters
# ---------------------------------------------------------------------------


def list_gke_clusters(project_id: str | None = None) -> list[dict[str, Any]]:
    """List all GKE clusters in the project.

    Returns a list of dicts with cluster name, location, status, node count,
    and current master version.
    """
    from google.cloud import container_v1

    project = _default_project(project_id)
    client = container_v1.ClusterManagerClient()
    parent = f"projects/{project}/locations/-"

    try:
        response = client.list_clusters(parent=parent)
    except Exception:
        logger.exception("Failed to list GKE clusters for project %s", project)
        return []

    clusters: list[dict[str, Any]] = []
    for cluster in response.clusters:
        clusters.append(
            {
                "name": cluster.name,
                "location": cluster.location,
                "status": cluster.status.name,
                "current_master_version": cluster.current_master_version,
                "current_node_count": cluster.current_node_count,
                "endpoint": cluster.endpoint,
                "autopilot": cluster.autopilot.enabled if cluster.autopilot else False,
            }
        )
    return clusters


# ---------------------------------------------------------------------------
# Cloud SQL Instances
# ---------------------------------------------------------------------------


def list_sql_instances(project_id: str | None = None) -> list[dict[str, Any]]:
    """List Cloud SQL instances in the project.

    Returns a list of dicts with instance name, database version, region,
    state, and tier.
    """
    from googleapiclient.discovery import build

    project = _default_project(project_id)

    try:
        service = build("sqladmin", "v1beta4", cache_discovery=False)
        request = service.instances().list(project=project)
        response = request.execute()
    except Exception:
        logger.exception("Failed to list Cloud SQL instances for project %s", project)
        return []

    instances: list[dict[str, Any]] = []
    for item in response.get("items", []):
        instances.append(
            {
                "name": item.get("name"),
                "database_version": item.get("databaseVersion"),
                "region": item.get("region"),
                "state": item.get("state"),
                "tier": item.get("settings", {}).get("tier"),
                "ip_addresses": [
                    {"type": addr.get("type"), "ip": addr.get("ipAddress")}
                    for addr in item.get("ipAddresses", [])
                ],
            }
        )
    return instances


# ---------------------------------------------------------------------------
# Cloud Run Services
# ---------------------------------------------------------------------------


def list_cloud_run_services(project_id: str | None = None) -> list[dict[str, Any]]:
    """List Cloud Run services across all regions.

    Returns a list of dicts with service name, region, URL, and last modifier.
    """
    from google.cloud import run_v2

    project = _default_project(project_id)
    client = run_v2.ServicesClient()
    parent = f"projects/{project}/locations/-"

    try:
        services_pager = client.list_services(parent=parent)
    except Exception:
        logger.exception("Failed to list Cloud Run services for project %s", project)
        return []

    services: list[dict[str, Any]] = []
    for svc in services_pager:
        # svc.name is the full resource name; extract short name and location
        parts = svc.name.split("/")
        short_name = parts[-1] if parts else svc.name
        location = parts[3] if len(parts) > 3 else "unknown"
        services.append(
            {
                "name": short_name,
                "location": location,
                "uri": svc.uri,
                "ingress": svc.ingress.name if svc.ingress else None,
                "last_modifier": svc.last_modifier,
                "create_time": svc.create_time.isoformat() if svc.create_time else None,
                "update_time": svc.update_time.isoformat() if svc.update_time else None,
            }
        )
    return services


# ---------------------------------------------------------------------------
# IAM Policy
# ---------------------------------------------------------------------------


def get_project_iam_policy(project_id: str | None = None) -> list[dict[str, Any]]:
    """Get the IAM policy bindings for the project.

    Returns a list of dicts with role and members for each binding.
    """
    from google.cloud import resourcemanager_v3

    project = _default_project(project_id)
    client = resourcemanager_v3.ProjectsClient()

    try:
        policy = client.get_iam_policy(resource=f"projects/{project}")
    except Exception:
        logger.exception("Failed to get IAM policy for project %s", project)
        return []

    bindings: list[dict[str, Any]] = []
    for binding in policy.bindings:
        bindings.append(
            {
                "role": binding.role,
                "members": list(binding.members),
            }
        )
    return bindings


# ---------------------------------------------------------------------------
# Secret Manager (names only)
# ---------------------------------------------------------------------------


def list_secrets(project_id: str | None = None) -> list[dict[str, Any]]:
    """List secret names in Secret Manager (names only, never values).

    Returns a list of dicts with secret name, create time, and labels.
    """
    from google.cloud import secretmanager

    project = _default_project(project_id)
    client = secretmanager.SecretManagerServiceClient()
    parent = f"projects/{project}"

    try:
        secrets_pager = client.list_secrets(parent=parent)
    except Exception:
        logger.exception("Failed to list secrets for project %s", project)
        return []

    secrets: list[dict[str, Any]] = []
    for secret in secrets_pager:
        # secret.name is full resource name like projects/123/secrets/my-secret
        short_name = secret.name.split("/")[-1]
        secrets.append(
            {
                "name": short_name,
                "create_time": secret.create_time.isoformat() if secret.create_time else None,
                "labels": dict(secret.labels) if secret.labels else {},
            }
        )
    return secrets


# ---------------------------------------------------------------------------
# GCS Buckets
# ---------------------------------------------------------------------------


def list_gcs_buckets(project_id: str | None = None) -> list[dict[str, Any]]:
    """List GCS buckets in the project.

    Returns a list of dicts with bucket name, location, storage class,
    and creation time.
    """
    from google.cloud import storage

    project = _default_project(project_id)
    client = storage.Client(project=project)

    try:
        buckets_iter = client.list_buckets()
    except Exception:
        logger.exception("Failed to list GCS buckets for project %s", project)
        return []

    buckets: list[dict[str, Any]] = []
    for bucket in buckets_iter:
        buckets.append(
            {
                "name": bucket.name,
                "location": bucket.location,
                "storage_class": bucket.storage_class,
                "time_created": bucket.time_created.isoformat() if bucket.time_created else None,
                "versioning_enabled": bucket.versioning_enabled,
            }
        )
    return buckets


# ---------------------------------------------------------------------------
# Compute Engine Instances
# ---------------------------------------------------------------------------


def list_compute_instances(project_id: str | None = None) -> list[dict[str, Any]]:
    """List Compute Engine instances across all zones.

    Returns a list of dicts with instance name, zone, machine type, status,
    and network interfaces.
    """
    from google.cloud import compute_v1

    project = _default_project(project_id)
    client = compute_v1.InstancesClient()

    try:
        agg_list = client.aggregated_list(project=project)
    except Exception:
        logger.exception("Failed to list compute instances for project %s", project)
        return []

    instances: list[dict[str, Any]] = []
    for zone, scoped_list in agg_list:
        if not scoped_list.instances:
            continue
        for instance in scoped_list.instances:
            # machine_type is a full URL; extract the short name
            machine_type = instance.machine_type.split("/")[-1] if instance.machine_type else None
            zone_short = zone.split("/")[-1] if "/" in zone else zone
            network_interfaces = []
            for nic in instance.network_interfaces or []:
                network_interfaces.append(
                    {
                        "network": nic.network.split("/")[-1] if nic.network else None,
                        "internal_ip": nic.network_i_p,
                        "external_ip": (
                            nic.access_configs[0].nat_i_p
                            if nic.access_configs
                            else None
                        ),
                    }
                )
            instances.append(
                {
                    "name": instance.name,
                    "zone": zone_short,
                    "machine_type": machine_type,
                    "status": instance.status,
                    "network_interfaces": network_interfaces,
                }
            )
    return instances


# ---------------------------------------------------------------------------
# Cloud Monitoring Metrics
# ---------------------------------------------------------------------------


def query_cloud_monitoring(
    query: str,
    project_id: str | None = None,
    from_seconds_ago: int = 3600,
) -> list[dict[str, Any]]:
    """Query GCP Cloud Monitoring metrics using MQL or metric type filter.

    Args:
        query: Either a metric type (e.g. "cloudsql.googleapis.com/database/cpu/utilization")
            or a full MQL query string.
        project_id: GCP project to query. Defaults to DEFAULT_PROJECT_ID.
        from_seconds_ago: How far back to query, in seconds. Defaults to 3600 (1h).

    Returns:
        List of timeseries dicts with metric, labels, and points.
    """
    from google.cloud import monitoring_v3
    from google.protobuf.timestamp_pb2 import Timestamp

    project = _default_project(project_id)
    client = monitoring_v3.MetricServiceClient()
    project_name = f"projects/{project}"

    now = datetime.now(timezone.utc)
    start_time = datetime.fromtimestamp(now.timestamp() - from_seconds_ago, tz=timezone.utc)

    start_ts = Timestamp()
    start_ts.FromDatetime(start_time)
    end_ts = Timestamp()
    end_ts.FromDatetime(now)

    interval = monitoring_v3.TimeInterval(
        start_time=start_ts,
        end_time=end_ts,
    )

    metric_filter = query
    if "/" in query and not query.startswith("fetch"):
        metric_filter = f'metric.type = "{query}"'

    try:
        results_iter = client.list_time_series(
            request={
                "name": project_name,
                "filter": metric_filter,
                "interval": interval,
                "view": monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
            }
        )
    except Exception:
        logger.exception("Failed to query Cloud Monitoring for project %s: %s", project, query)
        return []

    results_list: list[dict[str, Any]] = []
    for ts in results_iter:
        points = []
        for point in ts.points[-50:]:
            value = None
            kind = ts.value_type.name
            if kind == "DOUBLE":
                value = point.value.double_value
            elif kind == "INT64":
                value = point.value.int64_value
            elif kind == "BOOL":
                value = point.value.bool_value
            points.append({
                "timestamp": point.interval.end_time.isoformat() if hasattr(point.interval.end_time, "isoformat") else str(point.interval.end_time),
                "value": value,
            })
        results_list.append({
            "metric": ts.metric.type,
            "labels": dict(ts.metric.labels),
            "resource_type": ts.resource.type,
            "resource_labels": dict(ts.resource.labels),
            "point_count": len(points),
            "points": points,
        })
    return results_list


# ---------------------------------------------------------------------------
# Cloud Logging
# ---------------------------------------------------------------------------


def query_cloud_logs(
    query: str,
    project_id: str | None = None,
    from_seconds_ago: int = 3600,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Query GCP Cloud Logging.

    Args:
        query: Cloud Logging filter string (e.g. 'severity>=ERROR',
            'resource.type="cloudsql_database"', 'textPayload:"connection"').
        project_id: GCP project to query. Defaults to DEFAULT_PROJECT_ID.
        from_seconds_ago: How far back to search. Defaults to 3600 (1h).
        limit: Max log entries to return. Defaults to 50.

    Returns:
        List of log entry dicts.
    """
    from google.cloud import logging as cloud_logging

    project = _default_project(project_id)
    client = cloud_logging.Client(project=project)

    now = datetime.now(timezone.utc)
    start_time = datetime.fromtimestamp(now.timestamp() - from_seconds_ago, tz=timezone.utc)
    time_filter = f'timestamp>="{start_time.isoformat()}"'

    full_filter = f"{query} {time_filter}" if query else time_filter

    try:
        entries = list(client.list_entries(
            filter_=full_filter,
            order_by=cloud_logging.DESCENDING,
            max_results=min(limit, 100),
            resource_names=[f"projects/{project}"],
        ))
    except Exception:
        logger.exception("Failed to query Cloud Logging for project %s: %s", project, query)
        return []

    log_results: list[dict[str, Any]] = []
    for entry in entries:
        payload = entry.payload
        if isinstance(payload, dict):
            message = payload.get("message", str(payload)[:2000])
        else:
            message = str(payload)[:2000] if payload else None

        log_results.append({
            "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
            "severity": entry.severity if entry.severity else None,
            "resource_type": entry.resource.type if entry.resource else None,
            "resource_labels": dict(entry.resource.labels) if entry.resource and entry.resource.labels else {},
            "log_name": entry.log_name,
            "message": message,
            "labels": dict(entry.labels) if entry.labels else {},
        })
    return log_results
