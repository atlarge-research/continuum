"""\
Setup Kubernetes on cloud
This resource manager doesn't have any/many help functions, see the /kubernetes folder instead
"""

import json
import logging
import time
from datetime import datetime
from typing import Dict, List

import requests

from input.configuration import config_access
from resource_manager import orchestrator_options, plans
from resource_manager.kubernetes import kubernetes


def add_options(_config):
    """[INTERFACE] Add config options for this RM module

    Args:
        config (ConfigParser): ConfigParser object

    Returns:
        list(list()): Options to add
    """
    return (
        orchestrator_options.kubernetes_common_options(orchestrator_options.KUBE_VERSIONS_COMPAT)
        + orchestrator_options.kube_deployment_options()
        + orchestrator_options.kata_runtime_options()
    )


def verify_options(parser, config):
    """[INTERFACE] Verify config options for this RM module

    Args:
        parser (ArgumentParser): Argparse object
        config (ConfigParser): ConfigParser object
    """
    if (
        config["infrastructure"]["cloud_nodes"] < 2
        or config["infrastructure"]["edge_nodes"] != 0
        or config["infrastructure"]["endpoint_nodes"] < 0
    ):
        parser.error("ERROR: kubecontrol requires #clouds>=2, #edges=0, #endpoints>=0")
    elif (
        config["infrastructure"]["endpoint_nodes"] % (config["infrastructure"]["cloud_nodes"] - 1)
        != 0
    ):
        parser.error(r"ERROR: Kubernetes requires (#clouds-1) % #endpoints == 0 (-1 for control)")
    elif (
        config_access.orchestrator_value(config, "runtime") == "kata-fc"
        and config_access.orchestrator_value(config, "runtime_filesystem") == "overlayfs"
    ):
        parser.error(
            "ERROR: Overlay FS cannot be used with kata-fc - "
            + "use option runtime_filesystem = devmapper"
        )


def start(runner):
    """[INTERFACE] Execute kube_kata software-phase installation.

    Args:
        runner (AnsibleRunner): Shared Ansible runner with config and machine state.
    """
    from resource_manager import resource_manager

    resource_manager.start(runner)


def base_install_playbook(_config, tier):
    """[INTERFACE] Return kube_kata base-install playbook for a tier.

    Args:
        _config (dict): Parsed configuration (unused).
        tier (str): VM tier selector.

    Returns:
        str | None: K8s base-install playbook for cloud/edge tiers, else None.
    """
    if tier in ("cloud", "edge"):
        return "playbooks/resource_manager/k8s_base_install.yml"
    return None


def build_phase_plan(config):
    """[INTERFACE] Build software-phase plan entries for kube_kata RM.

    Args:
        config (dict): Parsed configuration.

    Returns:
        list[PlanEntry]: Ordered software-phase execution entries.
    """
    observability_owner = None
    if config_access.has_addon(config, "observability"):
        observability_owner = config_access.software_module_by_type(config, "observability")

    entries = [
        plans.PlanEntry(
            kind="playbook",
            playbook="playbooks/resource_manager/k8s_cluster.yml",
            extra_vars={"ignore_preflight_errors": True},
            legacy_target_groups=("cloudcontroller", "clouds", "edges"),
        )
    ]

    runtime = str(config_access.orchestrator_value(config, "runtime"))
    use_overlayfs = config_access.orchestrator_value(config, "runtime_filesystem") == "overlayfs"
    if "kata" in runtime:
        entries.append(
            plans.PlanEntry(
                kind="playbook",
                playbook="playbooks/resource_manager/kata_setup.yml",
                extra_vars={"continuum_use_overlayfs": use_overlayfs},
                legacy_target_groups=("cloudcontroller", "clouds", "edges"),
            )
        )

    entries.append(
        plans.PlanEntry(
            kind="playbook",
            playbook="playbooks/resource_manager/k8s_metrics.yml",
            legacy_target_groups=("cloudcontroller", "clouds"),
        )
    )
    if observability_owner is not None:
        entries.append(
            plans.PlanEntry(
                kind="playbook",
                playbook="playbooks/resource_manager/k8s_observability.yml",
                owner_id=observability_owner["id"],
                owner_type=observability_owner["type"],
                legacy_target_groups=("cloudcontroller",),
            )
        )
    return entries


def post_phase_hook(runner):
    """[INTERFACE] Run post-install verification for kube_kata RM.

    Args:
        runner (AnsibleRunner): Shared runner instance.
    """
    kubernetes.verify_running_cluster(runner.config, runner.machines)
    _verify_kata_runtime_install(runner.config, runner.machines)


def _verify_kata_runtime_install(config, machines):
    """Log and verify Kata runtime classes and guest runtime installation."""
    runtime = str(config_access.orchestrator_value(config, "runtime"))
    if "kata" not in runtime:
        return

    controller_ssh = config["cloud_ssh"][0]
    runtime_class_command = "kubectl get runtimeclass kata-qemu kata-fc runc -o name"
    output, error = machines[0].process(
        config, runtime_class_command, shell=True, ssh=controller_ssh
    )[0]
    if error and not _benign_kubectl_stderr(error):
        logging.error("Kata runtime-class check failed: %s", "".join(error))
        raise RuntimeError("Kata runtime-class check failed")
    logging.info("Kata runtime classes: %s", "".join(output).strip())

    expected_classes = {"runtimeclass.node.k8s.io/kata-qemu", "runtimeclass.node.k8s.io/runc"}
    observed_classes = {line.strip() for line in output if line.strip()}
    missing_classes = expected_classes - observed_classes
    if missing_classes:
        raise RuntimeError("Missing Kata runtime classes: %s" % (", ".join(sorted(missing_classes))))

    guest_command = (
        "test -e /dev/kvm && "
        "test -x /opt/kata/bin/kata-runtime && "
        "grep -q 'io.containerd.kata-qemu.v2' /etc/containerd/config.toml && "
        "curl -fsS http://127.0.0.1:16686/api/services >/dev/null && "
        "/opt/kata/bin/kata-runtime --version"
    )
    worker_ssh_targets = list(config.get("cloud_ssh", [])[1:]) + list(config.get("edge_ssh", []))
    if not worker_ssh_targets:
        raise RuntimeError("No worker SSH targets available for Kata guest runtime check")
    for ssh_target in worker_ssh_targets:
        output, error = machines[0].process(
            config, guest_command, shell=True, ssh=ssh_target
        )[0]
        if error:
            logging.error("Kata guest runtime check failed on %s: %s", ssh_target, "".join(error))
            raise RuntimeError("Kata guest runtime check failed on %s" % (ssh_target,))
        logging.info("Kata guest runtime ready on %s: %s", ssh_target, "".join(output).strip())
        _verify_jaeger_query_endpoint(ssh_target)


def _worker_ip_from_ssh_target(ssh_target):
    """Return the host/IP part from a Continuum SSH target."""
    if "@" in ssh_target:
        return ssh_target.rsplit("@", 1)[1]
    return ssh_target


def _verify_jaeger_query_endpoint(ssh_target):
    """Verify the host-side Jaeger query API used for Kata trace collection."""
    worker_ip = _worker_ip_from_ssh_target(ssh_target)
    url = "http://%s:16686/api/services" % (worker_ip,)
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(
            "Kata Jaeger query API is not reachable on %s (%s): %s"
            % (ssh_target, url, exc)
        ) from exc
    logging.info("Kata Jaeger query API ready on %s", url)


def _benign_kubectl_stderr(lines):
    """Return whether kubectl stderr only contains Continuum timing trace lines."""
    return bool(lines) and all("[CONTINUUM]" in line for line in lines)


def get_deployment_duration(config, machines):
    """Get deployment duration from stress job completion timestamps.

    Args:
        config (dict): Parsed configuration
        machines (list): List of machine objects representing physical machines

    Returns:
        float: Duration in seconds, or -1 on error.
    """
    try:
        command = "kubectl get job stress -o json"
        results = machines[0].process(config, command, shell=True, ssh=config["cloud_ssh"][0])
        results = "".join(results[0][0])

        results_json = json.loads(results)

        end, st = results_json["status"]["completionTime"], results_json["status"]["startTime"]
        duration = datetime.strptime(end, "%Y-%m-%dT%H:%M:%SZ") - datetime.strptime(
            st, "%Y-%m-%dT%H:%M:%SZ"
        )

        return duration.total_seconds()
    except Exception as e:
        logging.debug("[WARNING][%s] error in function get_deployment_duration", e)
        return -1


def _gather_kata_traces(ip: str, port: str = "16686") -> List[List[Dict]]:
    """(internal) curl request to jaeger server on `ip` to
    get the traces produced by the kata runtime.

    Args:
        ip (str): Jaeger endpoint ip
        port (str, optional): Jaeger endpoint port. Defaults to "16686".

    Returns:
        List[List[Dict]]: a sorted list of traces for each kata deployment on `ip`.
    """
    jaeger_api_url = f"http://{ip}:{port}/api/traces?service=kata&operation=rootSpan&limit=10000"
    try:
        response = requests.get(jaeger_api_url, timeout=600)
        response.raise_for_status()
        response_data = response.json()
    except requests.RequestException as exc:
        raise RuntimeError(
            "Could not fetch Kata traces from Jaeger at %s: %s" % (jaeger_api_url, exc)
        ) from exc
    except ValueError as exc:
        raise RuntimeError(
            "Jaeger returned invalid JSON for Kata traces at %s: %s" % (jaeger_api_url, exc)
        ) from exc

    try:
        traces = response_data["data"]
    except KeyError as exc:
        raise RuntimeError(
            "Jaeger response for Kata traces at %s did not contain data" % (jaeger_api_url,)
        ) from exc

    # Sort each trace's spans based on starTime and sort traces based on startTime
    traces = sorted(
        [sorted(trace["spans"], key=lambda x: x["startTime"]) for trace in traces],
        key=lambda x: x[0]["startTime"],
    )

    print(f"gather_kata_traces({ip}, {port}) -> got {len(traces)} traces")
    return traces


def get_kata_period_timestamps(
    traces: List[List[Dict]],
    log_incomplete: bool = True,
) -> List[List[int]]:
    """Extract kata period timestamps from Jaeger traces.

    T0 -> T1 : create kata runtime
    T1 -> T2 : create VM
    T2 -> T3 : connect to VM
    T3 -> T4 : create container and launch

    Args:
        traces (List[List[Dict]]): Sorted Jaeger trace spans per deployment.

    Returns:
        List[List[int]]: Per-trace lists of [T0, T1, T2, T3, T4] timestamps.
    """

    timestamps: List[List[int]] = []
    skipped_traces = 0

    for trace_index, trace in enumerate(traces):
        ts: List[int] = []
        skip_first = True
        for span in trace:
            operation_name = span["operationName"]
            # T0
            if len(ts) == 0:
                ts.append(span["startTime"])
            # T1, T2
            elif len(ts) == 1 and operation_name == "StartVM":
                ts.append(span["startTime"])  # T1
                ts.append(span["startTime"] + span["duration"])  # T2
            # T3
            elif len(ts) == 3 and operation_name == "connect":
                ts.append(span["startTime"] + span["duration"])  # T3
            # T4
            elif len(ts) == 4 and operation_name == "ttrpc.StartContainer":
                if skip_first is False:
                    ts.append(span["startTime"] + span["duration"])  # T4
                    break

                skip_first = False

        if len(ts) == 5:
            timestamps.append(ts)
        else:
            skipped_traces += 1
            operations = [span["operationName"] for span in trace]
            if log_incomplete:
                logging.warning(
                    "Skipping incomplete Kata trace %s with operations: %s",
                    trace_index,
                    operations,
                )

    if skipped_traces and log_incomplete:
        logging.warning(
            "Skipped %s incomplete Kata trace(s); retained %s complete Kata timestamp row(s)",
            skipped_traces,
            len(timestamps),
        )

    if not timestamps:
        raise RuntimeError("No complete Kata traces were available in Jaeger output")

    return timestamps


def _expected_kata_timestamp_rows(config) -> int:
    """Return expected Kata timestamp rows for the active Kubernetes benchmark."""
    apps_per_worker = config_access.benchmark_param_int(config, "applications_per_worker")
    if config["mode"] == "cloud":
        return (config["infrastructure"]["cloud_nodes"] - 1) * apps_per_worker
    if config["mode"] == "edge":
        return config["infrastructure"]["edge_nodes"] * apps_per_worker

    raise RuntimeError("Unsupported benchmark worker mode for Kata traces: %s" % (config["mode"],))


# Kata entry point.
def get_kata_timestamps(config, _worker_output) -> List[List[int]]:
    """Fetch kata period timestamps from Jaeger on worker nodes.

    Args:
        config (dict): Parsed configuration with cloud_ssh entries.
        _worker_output: Unused; worker output from benchmark run.

    Returns:
        List[List[int]]: Per-deployment kata period timestamps.
    """
    logging.info(
        "----------------------------------------------------------------------------------------"
    )
    logging.info("get_kata_timestamps")
    logging.info(
        "----------------------------------------------------------------------------------------"
    )

    _nodes_names, nodes_ips = map(list, zip(*[str.split(x, "@") for x in config["cloud_ssh"][1:]]))

    expected_rows = _expected_kata_timestamp_rows(config)
    retry_attempts = 12
    retry_delay_seconds = 15

    traces = []
    kata_ts = []
    for attempt in range(1, retry_attempts + 1):
        traces = [_gather_kata_traces(ip)[1:] for ip in nodes_ips]
        # Flatten list of lists
        traces = [a for b in traces for a in b]
        kata_ts = get_kata_period_timestamps(traces, log_incomplete=False)

        if len(kata_ts) >= expected_rows:
            logging.info(
                "Collected %s complete Kata timestamp row(s), expected %s",
                len(kata_ts),
                expected_rows,
            )
            return kata_ts

        if attempt < retry_attempts:
            logging.info(
                "Collected %s complete Kata timestamp row(s), expected %s; "
                "retrying Jaeger trace fetch in %s second(s) (%s/%s)",
                len(kata_ts),
                expected_rows,
                retry_delay_seconds,
                attempt,
                retry_attempts,
            )
            time.sleep(retry_delay_seconds)

    kata_ts = get_kata_period_timestamps(traces)
    return kata_ts
