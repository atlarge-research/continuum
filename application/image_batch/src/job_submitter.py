"""Submit one finite worker execution for an accepted image batch."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


LABEL_REQUEST_ID = "continuum.atlarge.nl/request-id"
LABEL_WORKLOAD = "continuum.atlarge.nl/workload"


@dataclass(frozen=True)
class JobRequest:
    request_id: str
    run_id: str
    job_name: str
    payload_url: str
    result_url: str
    payload_bytes: int
    image_count: int
    endpoint_batch_id: str | None = None
    adapter_accepted_at_unix_ns: int | None = None


def build_job_manifest(
    request: JobRequest,
    *,
    namespace: str,
    worker_image: str,
    ttl_seconds: int,
) -> dict[str, Any]:
    """Build the native Job observed later by Edward's OpenDT adapter."""
    labels = {
        "app.kubernetes.io/name": "image-batch-worker",
        LABEL_REQUEST_ID: request.request_id,
        LABEL_WORKLOAD: "image-batch",
    }
    annotations = {
        "continuum.atlarge.nl/run-id": request.run_id,
        "continuum.atlarge.nl/payload-bytes": str(request.payload_bytes),
        "continuum.atlarge.nl/image-count": str(request.image_count),
    }
    if request.endpoint_batch_id is not None:
        annotations[
            "continuum.atlarge.nl/endpoint-batch-id"
        ] = request.endpoint_batch_id
    if request.adapter_accepted_at_unix_ns is not None:
        annotations["continuum.atlarge.nl/accepted-at-unix-ns"] = str(
            request.adapter_accepted_at_unix_ns
        )
    environment = [
        {"name": "REQUEST_ID", "value": request.request_id},
        {"name": "RUN_ID", "value": request.run_id},
        {"name": "PAYLOAD_URL", "value": request.payload_url},
        {"name": "RESULT_URL", "value": request.result_url},
        {"name": "CLASSIFIER_MODE", "value": "tflite"},
    ]
    if request.endpoint_batch_id is not None:
        environment.append(
            {"name": "ENDPOINT_BATCH_ID", "value": request.endpoint_batch_id}
        )
    if request.adapter_accepted_at_unix_ns is not None:
        environment.append(
            {
                "name": "ADAPTER_ACCEPTED_AT_UNIX_NS",
                "value": str(request.adapter_accepted_at_unix_ns),
            }
        )
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": request.job_name,
            "namespace": namespace,
            "labels": labels,
            "annotations": annotations,
        },
        "spec": {
            "backoffLimit": 0,
            "ttlSecondsAfterFinished": ttl_seconds,
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "restartPolicy": "Never",
                    "containers": [
                        {
                            "name": "classifier",
                            "image": worker_image,
                            "imagePullPolicy": "IfNotPresent",
                            "env": environment,
                            "resources": {
                                "requests": {"cpu": "1", "memory": "512Mi"},
                                "limits": {"cpu": "1", "memory": "512Mi"},
                            },
                        }
                    ],
                },
            },
        },
    }


class KubernetesJobSubmitter:
    def __init__(
        self,
        *,
        namespace: str,
        worker_image: str,
        ttl_seconds: int,
        kubeconfig: str | None = None,
    ):
        try:
            from kubernetes import client, config
        except ImportError as exc:
            raise RuntimeError(
                "install the kubernetes package for Kubernetes submission"
            ) from exc

        if kubeconfig:
            config.load_kube_config(config_file=kubeconfig)
        else:
            try:
                config.load_incluster_config()
            except config.ConfigException:
                config.load_kube_config()
        self._client = client
        self._api = client.BatchV1Api()
        self.namespace = namespace
        self.worker_image = worker_image
        self.ttl_seconds = ttl_seconds

    def submit(self, request: JobRequest) -> None:
        manifest = build_job_manifest(
            request,
            namespace=self.namespace,
            worker_image=self.worker_image,
            ttl_seconds=self.ttl_seconds,
        )
        self._api.create_namespaced_job(namespace=self.namespace, body=manifest)


class LocalJobSubmitter:
    """Development submitter that runs the exact worker protocol locally."""

    def __init__(self, worker_path: str | Path, classifier_mode: str = "checksum"):
        self.worker_path = str(worker_path)
        self.classifier_mode = classifier_mode

    def submit(self, request: JobRequest) -> None:
        environment = os.environ.copy()
        environment.update(
            REQUEST_ID=request.request_id,
            RUN_ID=request.run_id,
            PAYLOAD_URL=request.payload_url,
            RESULT_URL=request.result_url,
            CLASSIFIER_MODE=self.classifier_mode,
        )
        if request.endpoint_batch_id is not None:
            environment["ENDPOINT_BATCH_ID"] = request.endpoint_batch_id
        if request.adapter_accepted_at_unix_ns is not None:
            environment["ADAPTER_ACCEPTED_AT_UNIX_NS"] = str(
                request.adapter_accepted_at_unix_ns
            )
        subprocess.Popen(
            [sys.executable, "-u", self.worker_path],
            env=environment,
            close_fds=True,
        )
