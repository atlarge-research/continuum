"""Prepare the teaching demo on an existing Continuum cluster; never provision VMs."""

import argparse
import copy
import json
from pathlib import Path
import shlex
import subprocess
import sys
import time

import yaml

from demo_configuration import resolve_deployment, validate_live_inventory
from forecast_workload import Settings, eligible_profile


REPOSITORY = Path(__file__).resolve().parents[3]
APPLICATION = REPOSITORY / "application/image_batch"
NATIVE_IMAGE = "continuum/opendc:fns-cf10c06"
ENDPOINT_IMAGE = "continuum/image-batch-endpoint:fns-v1"
METRICS_MANIFEST = (
    "https://github.com/kubernetes-sigs/metrics-server/releases/download/v0.7.2/components.yaml"
)
PACKING_PATH = "/etc/kubernetes/fns-packing.yaml"
SCHEDULER_PATH = "/etc/kubernetes/manifests/kube-scheduler.yaml"


def run(command, *, data=None, capture=False):
    """Run one checked local command, optionally supplying or collecting text.

    Args:
        command (list[str]): Executable and literal arguments.
        data (str or None): Optional standard input.
        capture (bool): Collect stdout instead of displaying it.

    Returns:
        str or None: Captured stdout when requested.

    Raises:
        subprocess.CalledProcessError: The command failed.
    """
    return subprocess.run(
        command,
        input=data,
        text=True,
        check=True,
        stdout=subprocess.PIPE if capture else None,
        cwd=REPOSITORY,
    ).stdout


def packing_manifest(original):
    """Add the demo profile mount while preserving the existing scheduler Pod.

    Args:
        original (dict): Existing static Pod manifest, left unchanged.

    Returns:
        dict: Independent manifest with exactly one packing configuration mount.
    """
    pod = copy.deepcopy(original)
    spec = pod["spec"]
    container = next(item for item in spec["containers"] if item["name"] == "kube-scheduler")
    container["command"] = [
        arg for arg in container["command"] if not arg.startswith("--config=")
    ] + [f"--config={PACKING_PATH}"]
    name = "fns-packing-config"
    container["volumeMounts"] = [
        item for item in container.get("volumeMounts", []) if item["name"] != name
    ] + [{"name": name, "mountPath": PACKING_PATH, "readOnly": True}]
    spec["volumes"] = [item for item in spec.get("volumes", []) if item["name"] != name] + [
        {"name": name, "hostPath": {"path": PACKING_PATH, "type": "File"}}
    ]
    return pod


def check_profiles(text):
    """Require a completed execution profile usable by the teaching forecaster.

    Args:
        text (str): Observer workload JSONL from the manual service.

    Returns:
        int: Number of eligible profiles.

    Raises:
        ValueError: No eligible four-image, sampled execution profile is available.
    """
    settings = Settings(run_id="student-manual", origin_ms=0, period_seconds=600)
    count = sum(eligible_profile(json.loads(line), settings) for line in text.splitlines() if line)
    if not count:
        raise ValueError(
            "No eligible execution profile: finish a manual batch and inspect observer sampling"
        )
    return count


class Demo:
    """Own application setup and inspection for a configuration-derived cluster.

    Args:
        config (Path): Continuum configuration used to create the existing guests.
    """

    def __init__(self, config):
        self.settings = resolve_deployment(config)
        self.root = Path(config).resolve().parent
        self.setup = self.root / "setup"

    def ssh(self, command, *, endpoint=False, data=None, capture=False):
        """Run a safely quoted command on the controller or endpoint.

        Args:
            command (list[str]): Remote executable and literal arguments.
            endpoint (bool): Use the endpoint instead of the control plane.
            data (str or None): Optional standard input.
            capture (bool): Collect stdout.

        Returns:
            str or None: Captured stdout when requested.
        """
        host = self.settings["endpoint" if endpoint else "controller"]
        return run(
            ["ssh", "-i", self.settings["ssh_key"], host, shlex.join(command)],
            data=data,
            capture=capture,
        )

    def kubectl(self, *arguments, data=None, capture=False):
        """Use the controller's kubectl context without copying credentials.

        Args:
            arguments (str): Literal kubectl arguments.
            data (str or None): Optional manifest input.
            capture (bool): Collect stdout.

        Returns:
            str or None: Captured stdout when requested.
        """
        return self.ssh(["kubectl", *arguments], data=data, capture=capture)

    def get(self, *arguments):
        """Read a Kubernetes object as JSON.

        Args:
            arguments (str): Resource and selection arguments following kubectl get.

        Returns:
            dict: Parsed Kubernetes response.
        """
        return json.loads(self.kubectl("get", *arguments, "-o", "json", capture=True))

    def preflight(self):
        """Require the teaching topology, Ready nodes and an idle cluster.

        Raises:
            ValueError: Inventory, readiness, control-plane isolation or Jobs disagree.
        """
        nodes = self.get("nodes")
        validate_live_inventory(nodes, self.settings)
        if len(self.settings["workers"]) != 6 or len(nodes["items"]) != 7:
            raise ValueError("the teaching demo requires six workers and one control plane")
        control = next(
            node
            for node in nodes["items"]
            if node["metadata"]["name"] == self.settings["control_node"]
        )
        if control["spec"].get("unschedulable") or not any(
            taint["key"] == "node-role.kubernetes.io/control-plane"
            and taint["effect"] == "NoSchedule"
            for taint in control["spec"].get("taints", [])
        ):
            raise ValueError("control plane must retain its NoSchedule taint and be uncordoned")
        if any(job.get("status", {}).get("active", 0) for job in self.get("jobs", "-A")["items"]):
            raise ValueError("another Job is active; wait before preparing or checking the demo")

    def install_packing(self):
        """Back up the scheduler, replace its manifest atomically and verify the new Pod.

        Raises:
            TimeoutError: The updated scheduler does not become Ready within three minutes.
        """
        remote_backup = "/etc/kubernetes/kube-scheduler.before-student.yaml"
        self.ssh(["sudo", "cp", "-n", SCHEDULER_PATH, remote_backup])
        original = self.ssh(["sudo", "cat", SCHEDULER_PATH], capture=True)
        backup = self.setup / "kube-scheduler.original.yaml"
        backup.write_text(self.ssh(["sudo", "cat", remote_backup], capture=True), encoding="utf-8")
        print(f"Scheduler backup: {backup}", flush=True)
        self.ssh(
            ["sudo", "tee", PACKING_PATH],
            data=(APPLICATION / "manifests/scheduler-packing.yaml").read_text(),
            capture=True,
        )
        replacement = yaml.safe_dump(packing_manifest(yaml.safe_load(original)))
        self.ssh(
            ["sudo", "tee", "/etc/kubernetes/kube-scheduler.next.yaml"],
            data=replacement,
            capture=True,
        )
        self.ssh(["sudo", "mv", "/etc/kubernetes/kube-scheduler.next.yaml", SCHEDULER_PATH])
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            pods = self.get("pods", "-n", "kube-system", "-l", "component=kube-scheduler")
            for pod in pods["items"]:
                command = pod["spec"]["containers"][0].get("command", [])
                if f"--config={PACKING_PATH}" in command and any(
                    item["type"] == "Ready" and item["status"] == "True"
                    for item in pod.get("status", {}).get("conditions", [])
                ):
                    return
            time.sleep(2)
        raise TimeoutError(
            "scheduler not Ready; restore /etc/kubernetes/kube-scheduler.before-student.yaml"
        )

    def prepare(self):
        """Build and distribute pinned images, then configure and start the demo service.

        Raises:
            FileNotFoundError: The documented Continuum provisioning environment is absent.
        """
        self.preflight()
        ansible = self.root / "provision/bin/ansible"
        if not ansible.is_file():
            raise FileNotFoundError(f"missing provisioning environment: {ansible}")
        self.setup.mkdir(parents=True, exist_ok=True)
        inventory = self.settings["deployment_sources"]["inventory"]
        guests = "cloudcontroller:clouds:endpoints"
        for command in ("sudo -n true", "timedatectl status"):
            run([str(ansible), "-i", inventory, guests, "-m", "command", "-a", command])
        print("Building application and pinned OpenDC images", flush=True)
        for component in ("adapter", "worker", "endpoint", "opendc"):
            command = ["docker", "build", "-f", str(APPLICATION / f"docker/{component}.Dockerfile")]
            if component == "opendc":
                command += [
                    "--build-arg",
                    "OPENDC_COMMIT=cf10c06eb73c7e60e1076e376922b1201caf12d1",
                    "--build-arg",
                    "OPENDC_SOURCE_SHA256="
                    "b60208e517037eaeae10f5ef32f36716bda5500de9c9a89f4e8cfc240f5ccb25",
                    "--build-arg",
                    "OPENDC_RUNTIME=fns-demo",
                ]
            image = (
                NATIVE_IMAGE
                if component == "opendc"
                else f"continuum/image-batch-{component}:fns-v1"
            )
            run([*command, "-t", image, str(REPOSITORY)])
        archive = self.setup / "application-images.tar"
        run(
            [
                "docker",
                "save",
                "-o",
                str(archive),
                "continuum/image-batch-adapter:fns-v1",
                "continuum/image-batch-worker:fns-v1",
            ]
        )
        run(
            [
                str(ansible),
                "-i",
                inventory,
                "cloudcontroller:clouds",
                "-m",
                "copy",
                "-a",
                json.dumps({"src": str(archive), "dest": "/tmp/student-images.tar"}),
            ]
        )
        run(
            [
                str(ansible),
                "-i",
                inventory,
                "cloudcontroller:clouds",
                "-m",
                "command",
                "-a",
                "sudo ctr -n k8s.io images import /tmp/student-images.tar",
            ]
        )
        endpoint_archive = self.setup / "endpoint-image.tar"
        run(["docker", "save", "-o", str(endpoint_archive), ENDPOINT_IMAGE])
        run(
            [
                "scp",
                "-i",
                self.settings["ssh_key"],
                str(endpoint_archive),
                self.settings["endpoint"] + ":/tmp/student-endpoint.tar",
            ]
        )
        self.ssh(["sudo", "docker", "load", "-i", "/tmp/student-endpoint.tar"], endpoint=True)
        self.ssh(
            ["sudo", "tee", "/etc/crictl.yaml"],
            data=(
                "runtime-endpoint: unix:///run/containerd/containerd.sock\n"
                "image-endpoint: unix:///run/containerd/containerd.sock\n"
            ),
            capture=True,
        )
        print("Configuring metrics and worker packing", flush=True)
        self.kubectl("apply", "-f", METRICS_MANIFEST)
        metrics = self.get("deployment", "metrics-server", "-n", "kube-system")
        if (
            "--kubelet-insecure-tls"
            not in metrics["spec"]["template"]["spec"]["containers"][0]["args"]
        ):
            self.kubectl(
                "-n",
                "kube-system",
                "patch",
                "deployment",
                "metrics-server",
                "--type=json",
                "-p",
                json.dumps(
                    [
                        {
                            "op": "add",
                            "path": "/spec/template/spec/containers/0/args/-",
                            "value": "--kubelet-insecure-tls",
                        }
                    ]
                ),
            )
        self.kubectl(
            "-n", "kube-system", "rollout", "status", "deployment/metrics-server", "--timeout=180s"
        )
        self.kubectl(
            "wait",
            "--for=condition=Available",
            "apiservice/v1beta1.metrics.k8s.io",
            "--timeout=180s",
        )
        self.kubectl("top", "nodes")
        self.install_packing()
        self.ssh(
            ["python3", "-"], data=(APPLICATION / "src/configure_cadvisor_scrape.py").read_text()
        )
        self.kubectl("apply", "-f", "-", data=(APPLICATION / "manifests/adapter.yaml").read_text())
        self.kubectl("-n", "fns-demo", "rollout", "restart", "deployment/image-batch-adapter")
        self.kubectl(
            "-n",
            "fns-demo",
            "rollout",
            "status",
            "deployment/image-batch-adapter",
            "--timeout=180s",
        )
        self.kubectl("get", "pods,services", "-n", "fns-demo")
        print(
            f"Service: http://{self.settings['adapter_address']}:30080\n"
            "Submit a manual batch, then run the helper's check command."
        )

    def check(self):
        """Check the idle cluster, service containers, metrics and forecast profile.

        Raises:
            ValueError: Containers are missing, unready, restarted or profiles are ineligible.
        """
        self.preflight()
        self.kubectl("top", "nodes")
        pods = self.get(
            "pods", "-n", "fns-demo", "-l", "app.kubernetes.io/name=image-batch-adapter"
        )
        if len(pods["items"]) != 1:
            raise ValueError("expected exactly one adapter Pod")
        statuses = pods["items"][0].get("status", {}).get("containerStatuses", [])
        if {item["name"] for item in statuses} != {"adapter", "opendt-observer"} or any(
            not item.get("ready") or item.get("restartCount", 0) for item in statuses
        ):
            raise ValueError("adapter/observer must be Ready with zero restarts")
        profiles = self.kubectl(
            "exec",
            "-n",
            "fns-demo",
            "deployment/image-batch-adapter",
            "-c",
            "opendt-observer",
            "--",
            "cat",
            "/var/lib/opendt/workload.jsonl",
            capture=True,
        )
        count = check_profiles(profiles)
        state_command = [
            "exec",
            "-n",
            "fns-demo",
            "deployment/image-batch-adapter",
            "-c",
            "opendt-observer",
            "--",
            "tail",
            "-n",
            "1",
            "/var/lib/opendt/cluster-state.jsonl",
        ]
        before = json.loads(self.kubectl(*state_command, capture=True))["timestamp_unix_ns"]
        time.sleep(2)
        after = json.loads(self.kubectl(*state_command, capture=True))["timestamp_unix_ns"]
        if after <= before:
            raise ValueError("observer state is not advancing; inspect observer logs and retry")
        print(f"{count} eligible completed execution profile(s); demo ready for captures")


def main(argv=None):
    """Dispatch preparation or run existing tools with fixed demo defaults.

    Args:
        argv (list[str] or None): Command-line arguments; defaults to sys.argv.

    Returns:
        int: Command exit status, with failures reported on stderr.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "command", choices=("prepare", "check", "kubectl", "url", "capture", "python")
    )
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.command == "python":
        return subprocess.call([sys.executable, *args.arguments], cwd=REPOSITORY)
    if args.command == "capture":
        return subprocess.call(
            [
                sys.executable,
                "-m",
                "capture_run",
                "--continuum-config",
                str(args.config),
                "--native-image",
                NATIVE_IMAGE,
                "--endpoint-image",
                ENDPOINT_IMAGE,
                "--source-dir",
                str(APPLICATION / "src"),
                *args.arguments,
            ],
            cwd=REPOSITORY,
        )
    if args.arguments and args.command != "kubectl":
        parser.error(f"{args.command} does not accept extra arguments")
    try:
        demo = Demo(args.config)
        if args.command == "url":
            print(f"http://{demo.settings['adapter_address']}:30080")
        elif args.command == "kubectl":
            demo.kubectl(*args.arguments)
        else:
            getattr(demo, args.command)()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Demo {args.command} failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
