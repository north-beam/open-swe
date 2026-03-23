import asyncio
import json
from typing import Any

from ..utils.gcp_infra import (
    DEFAULT_PROJECT_ID,
    get_project_iam_policy,
    list_cloud_run_services,
    list_compute_instances,
    list_gcs_buckets,
    list_gke_clusters,
    list_secrets,
    list_sql_instances,
    query_cloud_logs,
    query_cloud_monitoring,
)

_RESOURCE_HANDLERS = {
    "gke_clusters": list_gke_clusters,
    "sql_instances": list_sql_instances,
    "cloud_run": list_cloud_run_services,
    "iam_policy": get_project_iam_policy,
    "secrets": list_secrets,
    "buckets": list_gcs_buckets,
    "compute_instances": list_compute_instances,
    "cloud_monitoring": query_cloud_monitoring,
    "logs": query_cloud_logs,
}

_VALID_TYPES = sorted(_RESOURCE_HANDLERS.keys())


def gcp_lookup(
    resource_type: str,
    query: str = "",
    project_id: str = "",
) -> dict[str, Any]:
    """Look up read-only GCP infrastructure information.

    Use this tool when you need to inspect the team's GCP environment to answer
    questions about infrastructure, debug deployment issues, or gather context
    about the cloud setup. All operations are strictly read-only.

    **When to use:**
    - A user asks about GKE clusters, Cloud SQL databases, Cloud Run services,
      IAM roles/members, secrets (names only), GCS buckets, or Compute Engine VMs.
    - You need to understand the infrastructure context to diagnose an issue or
      plan a change.

    **Important:** This tool never exposes secret values. For secrets, only names
    and metadata are returned.

    Args:
        resource_type: The kind of GCP resource to look up. Must be one of:
            "gke_clusters", "sql_instances", "cloud_run", "iam_policy",
            "secrets", "buckets", "compute_instances", "cloud_monitoring", "logs".
            For "cloud_monitoring", pass a metric type as query (e.g.
            "cloudsql.googleapis.com/database/cpu/utilization").
            For "logs", pass a Cloud Logging filter as query (e.g.
            'severity>=ERROR', 'resource.type="cloudsql_database"').
            Both query GCP directly and work for any project.
        query: Optional filter string. When provided, results are filtered to
            items whose JSON representation contains this substring
            (case-insensitive). For example, query="prod" returns only
            resources with "prod" in their name or other fields.
        project_id: GCP project ID. Defaults to the GKE_PROJECT env var or
            "nb-enterprise-ai" if not set.

    Returns:
        Dictionary with:
        - success (bool): Whether the lookup succeeded.
        - resource_type (str): The resource type that was queried.
        - project_id (str): The GCP project that was queried.
        - count (int): Number of results returned.
        - results (list): The resource data.
        - error (str | None): Error message if the lookup failed.
    """
    if resource_type not in _RESOURCE_HANDLERS:
        return {
            "success": False,
            "resource_type": resource_type,
            "project_id": project_id or DEFAULT_PROJECT_ID,
            "count": 0,
            "results": [],
            "error": (
                f"Invalid resource_type '{resource_type}'. "
                f"Must be one of: {', '.join(_VALID_TYPES)}"
            ),
        }

    effective_project = project_id or DEFAULT_PROJECT_ID
    handler = _RESOURCE_HANDLERS[resource_type]

    try:
        if resource_type in ("cloud_monitoring", "logs"):
            if not query:
                hint = (
                    "query is required for cloud_monitoring. Pass a metric type "
                    "(e.g. 'cloudsql.googleapis.com/database/cpu/utilization') "
                    "or a filter string."
                ) if resource_type == "cloud_monitoring" else (
                    "query is required for logs. Pass a Cloud Logging filter "
                    "(e.g. 'severity>=ERROR', 'resource.type=\"cloudsql_database\"')."
                )
                return {
                    "success": False,
                    "resource_type": resource_type,
                    "project_id": effective_project,
                    "count": 0,
                    "results": [],
                    "error": hint,
                }
            results = asyncio.run(
                asyncio.to_thread(handler, query, effective_project)
            )
        else:
            results = asyncio.run(
                asyncio.to_thread(handler, effective_project)
            )
    except Exception as exc:
        return {
            "success": False,
            "resource_type": resource_type,
            "project_id": effective_project,
            "count": 0,
            "results": [],
            "error": f"GCP lookup failed: {exc!s}",
        }

    # Apply optional query filter
    if query:
        query_lower = query.lower()
        results = [
            item
            for item in results
            if query_lower in json.dumps(item, default=str).lower()
        ]

    return {
        "success": True,
        "resource_type": resource_type,
        "project_id": effective_project,
        "count": len(results),
        "results": results,
        "error": None,
    }
