"""\
Setup Kubernetes on cloud
This resource manager doesn't have any/many help functions, see the /kubernetes folder instead
"""

import json
import logging
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
            )
        )

    entries.append(
        plans.PlanEntry(kind="playbook", playbook="playbooks/resource_manager/k8s_metrics.yml")
    )
    if observability_owner is not None:
        entries.append(
            plans.PlanEntry(
                kind="playbook",
                playbook="playbooks/resource_manager/k8s_observability.yml",
                owner_id=observability_owner["id"],
                owner_type=observability_owner["type"],
            )
        )
    return entries


def post_phase_hook(runner):
    """[INTERFACE] Run post-install verification for kube_kata RM.

    Args:
        runner (AnsibleRunner): Shared runner instance.
    """
    kubernetes.verify_running_cluster(runner.config, runner.machines)


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
    response = requests.get(jaeger_api_url, timeout=600)
    response_data = response.json()

    traces = response_data["data"]

    # Sort each trace's spans based on starTime and sort traces based on startTime
    traces = sorted(
        [sorted(trace["spans"], key=lambda x: x["startTime"]) for trace in traces],
        key=lambda x: x[0]["startTime"],
    )

    print(f"gather_kata_traces({ip}, {port}) -> got {len(traces)} traces")
    return traces


def get_kata_period_timestamps(traces: List[List[Dict]]) -> List[List[int]]:
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

    for trace in traces:
        ts: List[int] = []
        skip_first = True
        for span in trace:
            assert len([span for span in trace if span["operationName"] == "StartVM"]) == 2
            assert len([span for span in trace if span["operationName"] == "connect"]) == 1
            # T0
            if len(ts) == 0:
                ts.append(span["startTime"])
            # T1, T2
            elif len(ts) == 1 and span["operationName"] == "StartVM":
                ts.append(span["startTime"])  # T1
                ts.append(span["startTime"] + span["duration"])  # T2
            # T3
            elif len(ts) == 3 and span["operationName"] == "connect":
                ts.append(span["startTime"] + span["duration"])  # T3
            # T4
            elif len(ts) == 4 and span["operationName"] == "ttrpc.StartContainer":
                if skip_first is False:
                    ts.append(span["startTime"] + span["duration"])  # T4
                    break

                skip_first = False

        assert len(ts) == 5
        timestamps.append(ts)

    return timestamps


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

    traces = [_gather_kata_traces(ip)[1:] for ip in nodes_ips]
    # Flatten list of lists
    traces = [a for b in traces for a in b]

    kata_ts = get_kata_period_timestamps(traces)
    return kata_ts
