"""Capture calibrated workload runs on the existing cluster with preserved evidence."""

from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
from pathlib import Path
import re
import shlex
import subprocess
import time

import yaml

from closed_loop_controller import Controller
from opendc_batch import remote_input
from opendc_inputs import write_json
from opendc_kubernetes import extract_artifacts, ssh


SOURCE = Path(__file__).resolve().parent
MANIFEST = SOURCE.parent / "manifests" / "adapter.yaml"
CONTROLLER = "cloud_controller_matthijs@192.168.210.2"
ENDPOINT = "endpoint0_matthijs@192.168.210.6"
KEY = "/home/matthijs/.ssh/id_rsa_continuum"
CONTROL_NODE = "cloudcontrollermatthijs"
WORKERS = ["cloud0matthijs", "cloud1matthijs", "cloud2matthijs"]
ENDPOINT_IMAGE = "continuum/image-batch-endpoint:fns-forecast-20260907-v1"
FREEZE_SCRIPT = """import pathlib,sys,tarfile
root=pathlib.Path(sys.argv[1])
files=[(p,p.stat().st_size) for p in root.rglob('*') if p.is_file()]
with tarfile.open(fileobj=sys.stdout.buffer,mode='w|') as archive:
 for path,size in files:
  entry=tarfile.TarInfo(str(path.relative_to(root)));entry.size=size
  with path.open('rb') as stream:archive.addfile(entry,stream)
"""
NETWORK_COMMANDS = {
    "filter": ["sudo", "iptables", "-S"],
    "nat": ["sudo", "iptables", "-t", "nat", "-S"],
    "routes": ["ip", "-N", "-j", "-4", "route", "show", "table", "all"],
    "rules": ["ip", "-N", "-j", "-4", "rule"],
}


def prepare_output(output, invocation):
    """Create a new capture directory without replacing historical evidence.

    Args:
        output (Path): New directory for this invocation.
        invocation (dict): Explicit run settings to preserve.

    Raises:
        FileExistsError: The destination already exists.
    """
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "invocation.json", invocation)


def capture_manifests(original, namespace, source, *, admission_workers=None):
    """Clone the calibrated deployment into an isolated capture namespace.

    Args:
        original (dict): Retrieved live deployment, never modified.
        namespace (str): New experiment namespace beginning with fns-.
        source (dict[str, str]): Exact Python source mounted into the capture.
        admission_workers (dict or None): Explicit VM-core pool enabling namespace FIFO.

    Returns:
        list[dict]: Namespace, permissions, source, deployment and dynamic NodePort.

    Raises:
        ValueError: The namespace is unsafe or identifies the original demo.
    """
    if namespace == "fns-demo" or not re.fullmatch(r"fns-[a-z0-9-]{1,58}[a-z0-9]", namespace):
        raise ValueError("use a new fns- experiment namespace, never fns-demo")
    docs = []
    for obj in yaml.safe_load_all(MANIFEST.read_text()):
        if obj["kind"] in ("Deployment", "Service", "ClusterRole"):
            continue
        if obj["kind"] in ("Namespace", "ClusterRoleBinding"):
            obj["metadata"]["name"] = namespace
        else:
            obj["metadata"]["namespace"] = namespace
        for subject in obj.get("subjects", []):
            subject["namespace"] = namespace
        if obj["kind"] == "Role" and admission_workers is not None:
            obj["rules"][0]["verbs"].append("patch")
        docs.append(obj)
    docs.append(
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "capture-source", "namespace": namespace},
            "data": source,
        }
    )
    deployment = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": "image-batch-adapter", "namespace": namespace},
        "spec": copy.deepcopy(original["spec"]),
    }
    template = deployment["spec"]["template"]
    template.setdefault("metadata", {}).pop("annotations", None)
    spec = template["spec"]
    spec["containers"] = [item for item in spec["containers"] if item["name"] != "forecast"]
    spec.setdefault("volumes", []).append(
        {"name": "capture-source", "configMap": {"name": "capture-source"}}
    )
    for container in spec["containers"]:
        container.setdefault("volumeMounts", []).append(
            {"name": "capture-source", "mountPath": "/review", "readOnly": True}
        )
        env = {item["name"]: item for item in container.get("env", [])}
        values = {"JOB_NAMESPACE": namespace, "RUN_ID": namespace}
        if container["name"] == "adapter":
            values.update(
                WORKER_SCHEDULER_NAME="fns-packing",
                PUBLIC_BASE_URL=f"http://image-batch-adapter.{namespace}.svc.cluster.local:8080",
                JOB_TTL_SECONDS="86400",
                WORKER_ADMISSION_MODE="fifo" if admission_workers is not None else "scheduler",
            )
        for name, value in values.items():
            env[name] = {"name": name, "value": value}
        container["env"] = list(env.values())
        if container["name"] in ("adapter", "opendt-observer"):
            script = "adapter.py" if container["name"] == "adapter" else "opendt_observer.py"
            container["command"] = ["python", "-u", "/review/" + script]
    if admission_workers is not None:
        adapter = next(item for item in spec["containers"] if item["name"] == "adapter")
        spec["containers"].append(
            {
                "name": "fifo-admission",
                "image": adapter["image"],
                "imagePullPolicy": "IfNotPresent",
                "command": ["python", "-u", "/review/fifo_admission.py"],
                "env": [
                    {"name": "JOB_NAMESPACE", "value": namespace},
                    {"name": "ADMISSION_WORKERS", "value": json.dumps(admission_workers)},
                ],
                "volumeMounts": [
                    {"name": "capture-source", "mountPath": "/review", "readOnly": True}
                ],
                "resources": {
                    "requests": {"cpu": "100m", "memory": "128Mi"},
                    "limits": {"cpu": "500m", "memory": "256Mi"},
                },
            }
        )
    docs.extend(
        [
            deployment,
            {
                "apiVersion": "v1",
                "kind": "Service",
                "metadata": {"name": "image-batch-adapter", "namespace": namespace},
                "spec": {
                    "type": "NodePort",
                    "selector": {"app.kubernetes.io/name": "image-batch-adapter"},
                    "ports": [{"name": "http", "port": 8080, "targetPort": "http"}],
                },
            },
        ]
    )
    return docs


class CaptureSession:
    """Own one measured workload, its audit artifacts and reversible cluster state.

    Args:
        args (argparse.Namespace): Validated command-line capture settings.
    """

    def __init__(self, args):
        self.args = args
        self.output = args.output.resolve()
        self.namespace = args.namespace
        self.pod_name = None
        self.process = None
        self.original = None
        self.nodes = None
        self.network = None
        self.replay_was_active = None
        self.remote_source = "/tmp/" + self.namespace
        self.base_replay = ["sudo", "python3", "/home/mahimahi/continuum_replay.py"]
        self.samples = []
        self.output_created = False
        self.loop = None

    def get(self, *arguments):
        """Read Kubernetes JSON through the explicit control-plane SSH connection.

        Args:
            arguments (tuple[str]): kubectl get arguments.

        Returns:
            dict: Retrieved API objects.
        """
        return json.loads(
            ssh(
                self.args.controller,
                self.args.ssh_key,
                ["kubectl", "get", *arguments, "-o", "json"],
            )
        )

    def kubectl(self, *arguments):
        """Execute a bounded Kubernetes command for this approved experiment.

        Args:
            arguments (tuple[str]): kubectl arguments.

        Returns:
            bytes: Successful command output.
        """
        return ssh(self.args.controller, self.args.ssh_key, ["kubectl", *arguments], timeout=130)

    def network_state(self):
        """Read routing and firewall configuration.

        Returns:
            dict: Exact command outputs for restoration comparison.
        """
        return {
            name: ssh(self.args.endpoint, self.args.ssh_key, command).decode()
            for name, command in NETWORK_COMMANDS.items()
        }

    def prepare(self):
        """Archive preconditions, prepare replay and deploy an isolated source snapshot.

        Raises:
            ValueError: Other Jobs are active or requested workers are unavailable.
        """
        prepare_output(
            self.output,
            {
                name: str(value) if isinstance(value, Path) else value
                for name, value in vars(self.args).items()
            },
        )
        self.output_created = True
        jobs = self.get("jobs", "-A")["items"]
        if any(job.get("status", {}).get("active", 0) for job in jobs):
            raise ValueError("another workload is active")
        self.original = self.get("deployment", "image-batch-adapter", "-n", "fns-demo")
        self.nodes = self.get("nodes")
        write_json(self.output / "original-deployment.json", self.original)
        write_json(self.output / "nodes-before.json", self.nodes)
        observed = {node["metadata"]["name"]: node for node in self.nodes["items"]}
        for worker in self.args.workers:
            if worker not in observed or not any(
                item["type"] == "Ready" and item["status"] == "True"
                for item in observed[worker]["status"]["conditions"]
            ):
                raise ValueError(f"worker unavailable: {worker}")
        self.network = self.network_state()
        write_json(self.output / "network-before.json", self.network)
        self.replay_was_active = (
            ssh(
                self.args.endpoint,
                self.args.ssh_key,
                [
                    "sudo",
                    "sh",
                    "-c",
                    "test -e /run/continuum-mahimahi/state.json && echo active || echo stopped",
                ],
            ).strip()
            == b"active"
        )
        write_json(
            self.output / "run-state.json",
            {
                "namespace": self.namespace,
                "replay_was_active": self.replay_was_active,
                "endpoint_source": self.remote_source,
            },
        )
        if not self.replay_was_active:
            ssh(
                self.args.endpoint,
                self.args.ssh_key,
                self.base_replay
                + [
                    "start",
                    "192.168.210.6",
                    "/home/mahimahi/traces/KPN_5G.up",
                    "/home/mahimahi/traces/KPN_5G.down",
                    *[node["status"]["addresses"][0]["address"] for node in self.nodes["items"]],
                ],
            )
        (self.output / "replay-check.txt").write_bytes(
            ssh(self.args.endpoint, self.args.ssh_key, self.base_replay + ["check"])
        )
        source = {path.name: path.read_text() for path in self.args.source_dir.glob("*.py")}
        write_json(
            self.output / "source-hashes.json",
            {name: hashlib.sha256(value.encode()).hexdigest() for name, value in source.items()},
        )
        (self.output / "source").mkdir()
        for name, value in source.items():
            (self.output / "source" / name).write_text(value)
        admission = (
            {name: self.args.worker_cores for name in self.args.workers}
            if self.args.admission_mode == "fifo"
            else None
        )
        manifests = capture_manifests(
            self.original, self.namespace, source, admission_workers=admission
        )
        manifest = yaml.safe_dump_all(manifests)
        (self.output / "manifest.yaml").write_text(manifest)
        remote_input(
            self.args.controller,
            self.args.ssh_key,
            ["kubectl", "create", "-f", "-"],
            manifest.encode(),
        )
        self.kubectl(
            "rollout",
            "status",
            "deployment/image-batch-adapter",
            "-n",
            self.namespace,
            "--timeout=90s",
        )
        pod = self.get("pods", "-n", self.namespace)["items"][0]
        self.pod_name = pod["metadata"]["name"]
        write_json(self.output / "pod-start.json", pod)
        for index, worker in enumerate(self.args.workers):
            self.kubectl("uncordon" if index < self.args.active_workers else "cordon", worker)
        ssh(self.args.endpoint, self.args.ssh_key, ["mkdir", self.remote_source])
        for name in ("endpoint.py", "events.py"):
            remote_input(
                self.args.endpoint,
                self.args.ssh_key,
                ["tee", self.remote_source + "/" + name],
                source[name].encode(),
            )

    def endpoint_command(self):
        """Build the calibrated open-loop sender command.

        Returns:
            list[str]: Docker and endpoint arguments with explicit workload settings.
        """
        port = self.get("service", "image-batch-adapter", "-n", self.namespace)["spec"]["ports"][0][
            "nodePort"
        ]
        return [
            "sudo",
            "docker",
            "run",
            "--rm",
            "--name",
            self.namespace,
            "--network",
            "bridge",
            "-v",
            self.remote_source + ":/review:ro",
            self.args.endpoint_image,
            "python",
            "-u",
            "/review/endpoint.py",
            "--adapter-url",
            f"http://{self.args.adapter_address}:{port}",
            "--images",
            "/images",
            "--batch-size",
            "4",
            "--arrival-pattern",
            "periodic",
            "--period-seconds",
            str(self.args.period_seconds),
            "--arrival-cycles",
            str(self.args.cycles),
            "--minimum-rate",
            str(self.args.minimum_rate),
            "--peak-rate",
            str(self.args.peak_rate),
            "--max-concurrency",
            "16",
            "--random-seed",
            str(self.args.seed),
            "--run-id",
            self.namespace,
        ]

    def observe(self):
        """Capture run health and application occupancy without inferring completion.

        Returns:
            tuple[list[dict], dict]: Application Jobs and current occupancy sample.

        Raises:
            ValueError: Application placement or fresh capture health is invalid.
        """
        if self.args.admission_mode == "fifo":
            latest = self.kubectl(
                "logs", "-n", self.namespace, self.pod_name, "-c", "fifo-admission", "--tail=1"
            ).strip()
            if latest:
                event = json.loads(latest)
                if (
                    event.get("event") == "admission.stopped"
                    or event.get("status") == "uncertain_stop"
                ):
                    write_json(self.output / "admission-failure.json", event)
                    raise ValueError("FIFO admission stopped; preserve the failed capture")
        pods = self.get("pods", "-n", self.namespace)["items"]
        capture = next(pod for pod in pods if pod["metadata"]["name"] == self.pod_name)
        if any(item["restartCount"] for item in capture["status"].get("containerStatuses", [])):
            raise ValueError("fresh capture container restarted")
        app = [
            pod
            for pod in pods
            if pod["metadata"].get("labels", {}).get("app.kubernetes.io/name")
            == "image-batch-worker"
        ]
        if any(pod["spec"].get("nodeName") == self.args.control_node for pod in app):
            raise ValueError("application placed on the control plane")
        jobs = self.get("jobs", "-n", self.namespace)["items"]
        jobs = [
            job
            for job in jobs
            if job["metadata"].get("labels", {}).get("app.kubernetes.io/name")
            == "image-batch-worker"
        ]
        sample = {
            "timestamp_ns": time.time_ns(),
            "jobs": len(jobs),
            "completed": sum(bool(job.get("status", {}).get("succeeded")) for job in jobs),
            "failed": sum(bool(job.get("status", {}).get("failed")) for job in jobs),
            "assigned": {
                worker: sum(
                    pod["spec"].get("nodeName") == worker
                    and pod["status"]["phase"] in ("Running", "Pending")
                    for pod in app
                )
                for worker in self.args.workers
            },
        }
        self.samples.append(sample)
        with (self.output / "monitor.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(sample) + "\n")
        return jobs, sample

    def archive_observer(self, destination):
        """Collect one immutable observer prefix for forecasting or final evidence.

        Args:
            destination (Path): New extraction directory.
        """
        archive = self.kubectl(
            "exec",
            "-n",
            self.namespace,
            self.pod_name,
            "-c",
            "opendt-observer",
            "--",
            "python",
            "-c",
            FREEZE_SCRIPT,
            "/var/lib/opendt",
        )
        destination.mkdir(parents=True, exist_ok=False)
        destination.with_suffix(".tar").write_bytes(archive)
        extract_artifacts(io.BytesIO(archive), destination)

    def collect(self):
        """Preserve complete terminal inventories, logs, observer evidence and results."""
        for resource, filename in [("jobs", "jobs.json"), ("pods", "pods-final.json")]:
            write_json(self.output / filename, self.get(resource, "-n", self.namespace))
        write_json(self.output / "nodes-final.json", self.get("nodes"))
        if self.pod_name:
            containers = ["adapter", "opendt-observer"]
            if self.args.admission_mode == "fifo":
                containers.append("fifo-admission")
            for container in containers:
                (self.output / (container + ".log")).write_bytes(
                    self.kubectl("logs", "-n", self.namespace, self.pod_name, "-c", container)
                )
            self.archive_observer(self.output / "observer")
            data = self.kubectl(
                "exec",
                "-n",
                self.namespace,
                self.pod_name,
                "-c",
                "adapter",
                "--",
                "python",
                "-c",
                FREEZE_SCRIPT,
                "/data",
            )
            (self.output / "adapter-data.tar").write_bytes(data)

    def restore(self, remove_namespace):
        """Restore cordons and network, deleting the run only after evidence collection.

        Args:
            remove_namespace (bool): True only when final collection succeeded.

        Raises:
            ValueError: Network or original deployment state differs after restoration.
        """
        for node in (self.nodes or {}).get("items", []):
            name = node["metadata"]["name"]
            if name in self.args.workers:
                self.kubectl("cordon" if node["spec"].get("unschedulable") else "uncordon", name)
        if self.replay_was_active is False:
            ssh(self.args.endpoint, self.args.ssh_key, self.base_replay + ["stop"])
        if remove_namespace:
            self.kubectl("delete", "namespace", self.namespace, "--wait=true")
            self.kubectl("delete", "clusterrolebinding", self.namespace)
            ssh(self.args.endpoint, self.args.ssh_key, ["rm", "-rf", "--", self.remote_source])
        if self.network is not None:
            after = self.network_state()
            write_json(self.output / "network-after.json", after)
            if after != self.network:
                raise ValueError("endpoint network configuration changed")
        if (
            self.original is not None
            and self.get("deployment", "image-batch-adapter", "-n", "fns-demo")["spec"]
            != self.original["spec"]
        ):
            raise ValueError("original deployment changed")
        write_json(
            self.output / "cleanup.json",
            {
                "namespace_removed": remove_namespace,
                "network_restored": True,
                "original_deployment_preserved": True,
            },
        )

    def run(self):
        """Run and collect one capture, preserving failed attempts for diagnosis.

        Raises:
            RuntimeError: Endpoint execution or collection fails.
            ValueError: Capture health or placement is invalid.
        """
        self.prepare()
        if self.args.control_arm != "none":
            self.loop = Controller(self)
            self.loop.prepare()
        command = self.endpoint_command()
        write_json(self.output / "endpoint-command.json", command)
        with (self.output / "endpoint.jsonl").open("wb") as stdout, (
            self.output / "endpoint-stderr.txt"
        ).open("wb") as stderr:
            # Explicit lifetime permits health polling and collection before cleanup.
            self.process = subprocess.Popen(  # pylint: disable=consider-using-with
                [
                    "ssh",
                    "-o",
                    "BatchMode=yes",
                    "-i",
                    self.args.ssh_key,
                    self.args.endpoint,
                    shlex.join(command),
                ],
                stdout=stdout,
                stderr=stderr,
            )
            deadline = time.monotonic() + self.args.period_seconds * self.args.cycles + 600
            while time.monotonic() < deadline:
                _, sample = self.observe()
                print(json.dumps(sample), flush=True)
                if self.loop is not None:
                    self.loop.maybe_tick()
                if self.process.poll() is not None:
                    if self.process.returncode:
                        raise RuntimeError("endpoint failed; preserve capture resources")
                    if sample["completed"] + sample["failed"] == sample["jobs"]:
                        break
                time.sleep(5)
            else:
                write_json(
                    self.output / "censored.json",
                    {"reason": "follow-up limit", "last_sample": sample},
                )
        # Completed profiles lag Job completion; wait on actual emission identities.
        expected = {
            job["metadata"]["uid"]
            for job in self.get("jobs", "-n", self.namespace)["items"]
            if job["metadata"].get("labels", {}).get("app.kubernetes.io/name")
            == "image-batch-worker"
        }
        deadline = time.monotonic() + 180
        while True:
            raw = self.kubectl(
                "exec",
                "-n",
                self.namespace,
                self.pod_name,
                "-c",
                "opendt-observer",
                "--",
                "cat",
                "/var/lib/opendt/observer-events.jsonl",
            )
            recorded = set()
            for line in raw.splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event["event_type"] in ("task.emitted", "job.failed"):
                    recorded.add(event["details"]["kubernetes_job_uid"])
            missing = sorted(expected - recorded)
            if not missing or time.monotonic() >= deadline:
                write_json(
                    self.output / "observer-drain.json",
                    {
                        "expected": len(expected),
                        "recorded": len(expected & recorded),
                        "missing_uids": missing,
                    },
                )
                break
            time.sleep(5)
        if self.loop is not None:
            self.loop.close()
        self.collect()
        self.restore(remove_namespace=not missing)
        print("CAPTURE_COLLECTED", flush=True)


def main():
    """Run a calibrated capture using new evidence and namespace destinations."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--period-seconds", type=int, default=240)
    parser.add_argument("--cycles", type=int, default=6)
    parser.add_argument("--minimum-rate", type=float, default=0.02)
    parser.add_argument("--peak-rate", type=float, default=0.30)
    parser.add_argument("--active-workers", type=int, default=3)
    parser.add_argument("--admission-mode", choices=("scheduler", "fifo"), default="scheduler")
    parser.add_argument(
        "--control-arm", choices=("none", "fixed", "reactive", "forecast"), default="none"
    )
    parser.add_argument("--warmup-cycles", type=int, default=3)
    parser.add_argument("--worker-cores", type=int, default=4)
    parser.add_argument("--worker-memory-mib", type=int, default=16384)
    parser.add_argument("--minimum-workers", type=int, default=1)
    parser.add_argument("--maximum-workers", type=int, default=3)
    parser.add_argument("--native-image", default="continuum/opendc:fns-loop-20260925-122a859")
    parser.add_argument("--workers", nargs="+", default=WORKERS)
    parser.add_argument("--controller", default=CONTROLLER)
    parser.add_argument("--endpoint", default=ENDPOINT)
    parser.add_argument("--ssh-key", default=KEY)
    parser.add_argument("--control-node", default=CONTROL_NODE)
    parser.add_argument("--adapter-address", default="192.168.210.3")
    parser.add_argument("--endpoint-image", default=ENDPOINT_IMAGE)
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=SOURCE,
        help="frozen application source directory for matched comparisons",
    )
    args = parser.parse_args()
    if not 1 <= args.active_workers <= len(args.workers):
        parser.error("active worker count must fit the worker inventory")
    if (
        args.control_arm != "none"
        and not 1
        <= args.minimum_workers
        <= args.active_workers
        <= args.maximum_workers
        <= len(args.workers)
    ):
        parser.error("controller worker bounds must contain the initial accepting pool")
    if args.control_arm != "none" and (args.warmup_cycles < 1 or args.warmup_cycles >= args.cycles):
        parser.error("warmup must contain complete cycles and leave evaluation cycles")
    session = CaptureSession(args)
    try:
        session.run()
    except Exception as exc:
        if session.output_created:
            write_json(
                session.output / "failure.json",
                {
                    "type": type(exc).__name__,
                    "error": str(exc),
                    "namespace": args.namespace,
                    "preserve_resources": True,
                },
            )
        raise


if __name__ == "__main__":
    main()
