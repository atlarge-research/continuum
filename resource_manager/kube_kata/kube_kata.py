"""\
Setup Kubernetes on cloud
This resource manager doesn't have any/many help functions, see the /kubernetes folder instead
"""

import logging
import os
import json

from datetime import datetime
from typing import Dict, List

import requests

from infrastructure import ansible
from resource_manager.kubernetes import kubernetes


def add_options(_config):
    """Add config options for a particular module

    Args:
        config (ConfigParser): ConfigParser object

    Returns:
        list(list()): Options to add
    """
    settings = [
        ["cache_worker", bool, lambda x: x in [True, False], False, False],
        [
            "kube_deployment",
            str,
            lambda x: x in ["pod", "container", "file", "call"],
            False,
            "pod",
        ],
        [
            "kube_version",
            str,
            lambda _: ["v1.27.0", "v1.26.0", "v1.25.0", "v1.24.0", "v1.23.0"],
            False,
            "v1.27.0",
        ],
        ["runtime", str, lambda x: x in ["runc", "kata-qemu", "kata-fc"], False, "runc"],
        ["runtime_filesystem", str, lambda x: x in ["overlayfs", "devmapper"], False, "devmapper"],
    ]
    return settings


def verify_options(parser, config):
    """Verify the config from the module's requirements

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
        config["benchmark"]["runtime"] == "kata-fc"
        and config["benchmark"]["runtime_filesystem"] == "overlayfs"
    ):
        parser.error(
            "ERROR: Overlay FS cannot be used with kata-fc - "
            + "use option runtime_filesystem = devmapper"
        )


def start(config, machines):
    """Setup Kubernetes on cloud VMs using Ansible.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Start Kubernetes cluster on VMs")
    commands = []

    # Setup cloud controller
    commands.append(
        [
            "ansible-playbook",
            "-i",
            os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_vms"),
            os.path.join(
                config["infrastructure"]["base_path"],
                ".continuum/cloud/control_install.yml",
            ),
        ]
    )

    # Setup worker
    commands.append(
        [
            "ansible-playbook",
            "-i",
            os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_vms"),
            os.path.join(
                config["infrastructure"]["base_path"],
                ".continuum/%s/install.yml" % (config["mode"]),
            ),
        ]
    )

    # Setup worker runtime
    runtime = config["benchmark"]["runtime"]
    use_overlayfs = (
        "true" if config["benchmark"].get("runtime_filesystem") == "overlayfs" else "false"
    )
    if "kata" in runtime:
        commands.append(
            [
                "ansible-playbook",
                "-i",
                os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_vms"),
                os.path.join(
                    config["infrastructure"]["base_path"],
                    f".continuum/{(config['mode'])}/install_kata_containers.yml",
                ),
                "-e",
                f"use_overlayfs={use_overlayfs}",
            ]
        )
        commands.append(
            [
                "ansible-playbook",
                "-i",
                os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_vms"),
                os.path.join(
                    config["infrastructure"]["base_path"],
                    ".continuum/cloud/install_kata_dev_tools.yml",
                ),
            ]
        )

    results = machines[0].process(config, commands)

    # Check playbooks
    for command, (output, error) in zip(commands, results):
        logging.debug("Check output for Ansible command [%s]", " ".join(command))
        ansible.check_output((output, error))

    kubernetes.verify_running_cluster(config, machines)

    # Start the resource metrics server
    command = [
        "ansible-playbook",
        "-i",
        os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_vms"),
        os.path.join(
            config["infrastructure"]["base_path"],
            ".continuum/cloud/resource_usage.yml",
        ),
    ]

    output, error = machines[0].process(config, command)[0]

    logging.debug("Check output for Ansible command [%s]", " ".join(command))
    ansible.check_output((output, error))

    # Now the OS server that runs on every VM
    command = [
        "ansible-playbook",
        "-i",
        os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_vms"),
        os.path.join(
            config["infrastructure"]["base_path"],
            ".continuum/cloud/resource_usage_os.yml",
        ),
    ]

    output, error = machines[0].process(config, command)[0]

    logging.debug("Check output for Ansible command [%s]", " ".join(command))
    ansible.check_output((output, error))

    # Install observability packages (Prometheus, Grafana) if configured by the user
    if config["benchmark"]["observability"]:
        command = [
            "ansible-playbook",
            "-i",
            os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_vms"),
            os.path.join(
                config["infrastructure"]["base_path"],
                ".continuum/cloud/observability.yml",
            ),
        ]

        output, error = machines[0].process(config, command)[0]

        logging.debug("Check output for Ansible command [%s]", " ".join(command))
        ansible.check_output((output, error))


def get_deployment_duration(config, machines):
    """_summary_

    Args:
        config (_type_): _description_
        machines (_type_): _description_

    Returns:
        _type_: _description_
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
    """TODO

    T0 -> T1 : create kata runtime
    T1 -> T2 : create VM
    T2 -> T3 : connect to VM
    T3 -> T4 : create container and launch

    Args:
        traces (List[List[Dict]]): _description_

    Returns:
        List[List[int]]: _description_
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
    """_summary_

    Args:
        config (_type_): _description_
        _worker_output (_type_): _description_

    Returns:
        List[List[int]]: _description_
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
