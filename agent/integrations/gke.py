"""GKE Pod-based sandbox backend.

Creates a long-running Kubernetes Pod per sandbox and executes commands
via the Kubernetes exec API. Designed for self-hosted deployments on GKE
where sandboxes run as isolated Pods in the cluster.
"""

from __future__ import annotations

import logging
import os
import time
import uuid

from deepagents.backends.protocol import (
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
    SandboxBackendProtocol,
    WriteResult,
)
from deepagents.backends.sandbox import BaseSandbox

logger = logging.getLogger(__name__)

# Configuration via environment variables
GKE_SANDBOX_NAMESPACE = os.getenv("GKE_SANDBOX_NAMESPACE", "open-swe-sandboxes")
GKE_SANDBOX_IMAGE = os.getenv(
    "GKE_SANDBOX_IMAGE",
    "us-central1-docker.pkg.dev/nb-registry-16db/images/open-swe-sandbox:latest",
)
GKE_SANDBOX_SERVICE_ACCOUNT = os.getenv("GKE_SANDBOX_SERVICE_ACCOUNT", "open-swe-sandbox")
GKE_SANDBOX_CPU_REQUEST = os.getenv("GKE_SANDBOX_CPU_REQUEST", "500m")
GKE_SANDBOX_CPU_LIMIT = os.getenv("GKE_SANDBOX_CPU_LIMIT", "2")
GKE_SANDBOX_MEMORY_REQUEST = os.getenv("GKE_SANDBOX_MEMORY_REQUEST", "2Gi")
GKE_SANDBOX_MEMORY_LIMIT = os.getenv("GKE_SANDBOX_MEMORY_LIMIT", "4Gi")
GKE_SANDBOX_STARTUP_TIMEOUT = int(os.getenv("GKE_SANDBOX_STARTUP_TIMEOUT", "120"))


def _get_k8s_client():
    """Get a Kubernetes API client, loading in-cluster config."""
    from kubernetes import client, config

    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()

    return client.CoreV1Api()


def _create_sandbox_pod(
    k8s_client,
    pod_name: str,
    namespace: str,
) -> None:
    """Create a long-running sandbox Pod."""
    from kubernetes.client import (
        V1Container,
        V1ObjectMeta,
        V1Pod,
        V1PodSpec,
        V1ResourceRequirements,
        V1SecurityContext,
    )

    pod = V1Pod(
        metadata=V1ObjectMeta(
            name=pod_name,
            namespace=namespace,
            labels={
                "app": "open-swe-sandbox",
                "sandbox-id": pod_name,
            },
        ),
        spec=V1PodSpec(
            service_account_name=GKE_SANDBOX_SERVICE_ACCOUNT,
            restart_policy="Never",
            containers=[
                V1Container(
                    name="sandbox",
                    image=GKE_SANDBOX_IMAGE,
                    command=["/bin/bash", "-c", "trap 'exit 0' SIGTERM; sleep infinity & wait"],
                    working_dir="/workspace",
                    resources=V1ResourceRequirements(
                        requests={
                            "cpu": GKE_SANDBOX_CPU_REQUEST,
                            "memory": GKE_SANDBOX_MEMORY_REQUEST,
                        },
                        limits={
                            "cpu": GKE_SANDBOX_CPU_LIMIT,
                            "memory": GKE_SANDBOX_MEMORY_LIMIT,
                        },
                    ),
                    security_context=V1SecurityContext(
                        run_as_user=0,
                    ),
                ),
            ],
            node_selector={"karpenter.sh/capacity-type": "on-demand"},
            tolerations=[],
            # 4-hour active deadline to prevent runaway sandbox pods
            active_deadline_seconds=14400,
        ),
    )

    k8s_client.create_namespaced_pod(namespace=namespace, body=pod)
    logger.info("Created sandbox pod %s in namespace %s", pod_name, namespace)


def _wait_for_pod_ready(
    k8s_client,
    pod_name: str,
    namespace: str,
    timeout: int = GKE_SANDBOX_STARTUP_TIMEOUT,
) -> None:
    """Wait for the sandbox Pod to be in Running phase."""
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        pod = k8s_client.read_namespaced_pod(name=pod_name, namespace=namespace)
        if pod.status.phase == "Running":
            # Also check container is ready
            if pod.status.container_statuses:
                cs = pod.status.container_statuses[0]
                if cs.ready:
                    logger.info("Sandbox pod %s is ready", pod_name)
                    return
        time.sleep(2)

    raise TimeoutError(f"Sandbox pod {pod_name} not ready within {timeout}s")


def _exec_in_pod(
    k8s_client,
    pod_name: str,
    namespace: str,
    command: str,
    timeout: int = 300,
) -> ExecuteResponse:
    """Execute a command in a running Pod via the Kubernetes exec API."""
    from kubernetes.stream import stream

    # Wrap in bash to get proper exit code handling
    wrapped_command = [
        "/bin/bash",
        "-c",
        command,
    ]

    try:
        resp = stream(
            k8s_client.connect_get_namespaced_pod_exec,
            pod_name,
            namespace,
            command=wrapped_command,
            container="sandbox",
            stderr=True,
            stdout=True,
            stdin=False,
            tty=False,
            _preload_content=False,
        )

        # Read output with timeout
        output_parts = []
        resp.run_forever(timeout=timeout)

        stdout = resp.read_stdout() or ""
        stderr = resp.read_stderr() or ""
        exit_code = resp.returncode if hasattr(resp, "returncode") and resp.returncode is not None else 0

        output = stdout
        if stderr:
            output = output + "\n" + stderr if output else stderr

        resp.close()

        return ExecuteResponse(
            output=output,
            exit_code=exit_code,
            truncated=False,
        )
    except Exception as e:
        logger.exception("Failed to exec in pod %s", pod_name)
        return ExecuteResponse(
            output=f"Error executing command: {e}",
            exit_code=1,
            truncated=False,
        )


class GKEBackend(BaseSandbox):
    """GKE Pod-based sandbox backend.

    Creates a long-running Pod and executes commands via kubectl exec.
    Inherits file operations from BaseSandbox (which delegates to execute()).
    """

    def __init__(self, k8s_client, pod_name: str, namespace: str) -> None:
        self._k8s_client = k8s_client
        self._pod_name = pod_name
        self._namespace = namespace
        self._default_timeout = 300  # 5 minutes

    @property
    def id(self) -> str:
        return self._pod_name

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        effective_timeout = timeout if timeout is not None else self._default_timeout
        return _exec_in_pod(
            self._k8s_client,
            self._pod_name,
            self._namespace,
            command,
            timeout=effective_timeout,
        )

    def write(self, file_path: str, content: str) -> WriteResult:
        """Write file content via base64 to avoid shell escaping issues."""
        import base64

        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        # Use printf to avoid echo interpretation, pipe through base64 -d
        result = self.execute(
            f'mkdir -p "$(dirname {file_path})" && printf "%s" "{encoded}" | base64 -d > {file_path}'
        )
        if result.exit_code != 0:
            return WriteResult(error=f"Failed to write file '{file_path}': {result.output}")
        return WriteResult(path=file_path, files_update=None)

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        responses: list[FileDownloadResponse] = []
        for path in paths:
            result = self.execute(f"cat {path}")
            if result.exit_code == 0:
                responses.append(
                    FileDownloadResponse(path=path, content=result.output.encode(), error=None)
                )
            else:
                responses.append(
                    FileDownloadResponse(path=path, content=b"", error=result.output)
                )
        return responses

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        responses: list[FileUploadResponse] = []
        for path, content in files:
            write_result = self.write(path, content.decode("utf-8", errors="replace"))
            error = write_result.error if hasattr(write_result, "error") else None
            responses.append(FileUploadResponse(path=path, error=error))
        return responses


class GKEProvider:
    """Manages GKE sandbox Pod lifecycle."""

    def __init__(self) -> None:
        self._k8s_client = _get_k8s_client()
        self._namespace = GKE_SANDBOX_NAMESPACE

    def get_or_create(
        self,
        sandbox_id: str | None = None,
    ) -> GKEBackend:
        if sandbox_id:
            # Try to connect to existing pod
            try:
                pod = self._k8s_client.read_namespaced_pod(
                    name=sandbox_id, namespace=self._namespace
                )
                if pod.status.phase == "Running":
                    logger.info("Connected to existing sandbox pod %s", sandbox_id)
                    return GKEBackend(self._k8s_client, sandbox_id, self._namespace)
                else:
                    logger.warning(
                        "Sandbox pod %s exists but is in phase %s, creating new",
                        sandbox_id,
                        pod.status.phase,
                    )
            except Exception:
                logger.warning("Failed to find sandbox pod %s, creating new", sandbox_id)

        # Create a new sandbox pod
        pod_name = f"sandbox-{uuid.uuid4().hex[:12]}"
        _create_sandbox_pod(self._k8s_client, pod_name, self._namespace)
        _wait_for_pod_ready(self._k8s_client, pod_name, self._namespace)

        return GKEBackend(self._k8s_client, pod_name, self._namespace)

    def delete(self, sandbox_id: str) -> None:
        try:
            self._k8s_client.delete_namespaced_pod(
                name=sandbox_id,
                namespace=self._namespace,
            )
            logger.info("Deleted sandbox pod %s", sandbox_id)
        except Exception:
            logger.exception("Failed to delete sandbox pod %s", sandbox_id)


def create_gke_sandbox(sandbox_id: str | None = None) -> SandboxBackendProtocol:
    """Create or reconnect to a GKE Pod sandbox.

    Args:
        sandbox_id: Optional existing pod name to reconnect to.

    Returns:
        GKEBackend implementing SandboxBackendProtocol.
    """
    provider = GKEProvider()
    return provider.get_or_create(sandbox_id=sandbox_id)
