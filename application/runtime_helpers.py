"""Application-phase runtime helpers.

These helpers own benchmark-launch and non-Kubernetes worker runtime details so
resource-manager modules can stay focused on platform installation and generic
execution plumbing.
"""

import logging
import os
import sys
import time

from input.configuration import config_access


def parse_custom_kubernetes_splits(line):
    """Parse Continuum-tagged kubectl trace output into timestamp + marker text."""
    line = line.strip()
    line_split = line.split(" ")

    try:
        index = line_split.index("[CONTINUUM]")
        time_str = line_split[index - 1]
        time_str = time_str.split("=")[1][:-1]
        time_obj = float(time_str) / 10**9
    except Exception as exc:  # pylint: disable=broad-except
        logging.debug("[WARNING][%s] Could not parse line: %s", str(exc), line)
        return False, False

    return time_obj, line.split("[CONTINUUM] ")[1]


def launch_kubernetes_with_starttime(config, machines):
    """Launch Kubernetes benchmark manifests and capture kubectl timing traces."""
    if config_access.orchestrator_value(config, "kube_deployment") == "file":
        target = "/home/%s/jobs" % (machines[0].cloud_controller_names[0])
        command = "\"date +'%%s.%%N'; kubectl apply -f %s\"" % (target)
    elif config_access.orchestrator_value(config, "kube_deployment") == "call":
        target = "/home/%s/jobs/*" % (machines[0].cloud_controller_names[0])
        command = "\"date +'%%s.%%N'; for filename in %s; do kubectl apply -f $filename & done\"" % (
            target
        )
    else:
        target = "/home/%s/job-template.yaml" % (machines[0].cloud_controller_names[0])
        command = "\"date +'%%s.%%N'; kubectl apply -f %s\"" % (target)

    output, error = machines[0].process(config, command, shell=True, ssh=config["cloud_ssh"][0])[0]

    if len(output) < 2 or not any("created" in entry for entry in output):
        logging.error("Could not deploy pods: %s", "".join(output))
        sys.exit(1)

    if error and not all(
        any(
            marker in line
            for marker in (
                "[CONTINUUM]",
                "due to client-side throttling",
                "handshake timeout",
            )
        )
        for line in error
    ):
        logging.error("Could not deploy pods: %s", "".join(error))
        sys.exit(1)
    if error and not any("[CONTINUUM]" in line for line in error):
        logging.error("Could not deploy pods, expected custom [CONTINUUM] logs: %s", "".join(error))
        sys.exit(1)

    kubectl_output = []
    for line in error:
        if "[CONTINUUM]" in line:
            time_obj, parsed_line = parse_custom_kubernetes_splits(line)
            if time_obj is False:
                logging.debug("Couldn't properly parse line: %s", parsed_line)
                continue
            kubectl_output.append([time_obj, parsed_line])

    start_list = [entry for entry in kubectl_output if "0400" in entry[1]]
    end_list = [entry for entry in kubectl_output if "0402" in entry[1]]

    if len(start_list) != len(end_list):
        logging.error(
            "There are more kubectl-start statements than kubectl-end statement - should be equal"
        )
        sys.exit(1)

    send_length = len([entry for entry in kubectl_output if "0401" in entry[1]])
    if len(start_list) != send_length:
        if len(start_list) == 1 and config_access.orchestrator_value(config, "kube_deployment") == "file":
            start_list *= send_length
            end_list *= send_length
        else:
            logging.error("The number of 0400/0402 statements != the number of 0401 statements")
            sys.exit(1)

    kubectl_output_updated = []
    index = 0
    for time_obj, line in kubectl_output:
        if "0401" not in line:
            continue

        kubectl_output_updated.append([time_obj, line])
        job_string = line.split("0401")[1]

        start_time, start_line = start_list[index]
        end_time, end_line = end_list[index]
        kubectl_output_updated.append([start_time, start_line + job_string])
        kubectl_output_updated.append([end_time, end_line + job_string])
        index += 1

    return float(output[0]), kubectl_output_updated


def kubernetes_worker_app_count(config):
    """Return the number of benchmark worker app instances for the active mode."""
    apps_per_worker = config_access.benchmark_param_int(config, "applications_per_worker")
    if config["mode"] == "cloud":
        return (config["infrastructure"]["cloud_nodes"] - 1) * apps_per_worker
    if config["mode"] == "edge":
        return config["infrastructure"]["edge_nodes"] * apps_per_worker

    logging.error("Unsupported benchmark worker mode for Kubernetes launch: %s", config["mode"])
    sys.exit(1)


def mqtt_kubernetes_worker_vars(config):
    """Build shared Kubernetes worker launch vars for MQTT-style benchmark apps."""
    worker_apps = kubernetes_worker_app_count(config)
    return {
        "container_port": 1883,
        "mqtt_logs": True,
        "endpoint_connected": int(config["infrastructure"]["endpoint_nodes"] / worker_apps),
        "cpu_threads": max(
            1, int(config_access.benchmark_param_float(config, "application_worker_cpu"))
        ),
    }


def mqtt_mist_worker_env(config):
    """Build shared Mist worker env vars for MQTT-style benchmark apps."""
    return [
        "MQTT_LOGS=True",
        "CPU_THREADS=%i" % (config["infrastructure"]["edge_cores"]),
        "ENDPOINT_CONNECTED=%i"
        % (int(config["infrastructure"]["endpoint_nodes"] / config["infrastructure"]["edge_nodes"])),
    ]


def mqtt_baremetal_worker_env(config):
    """Build shared baremetal worker env vars for MQTT-style benchmark apps."""
    return [
        "MQTT_LOCAL_IP=%s" % (config["registry"].split(":")[0]),
        "MQTT_LOGS=True",
        "CPU_THREADS=%i" % (config["infrastructure"]["cloud_cores"]),
        "ENDPOINT_CONNECTED=%i"
        % (
            int(
                config["infrastructure"]["endpoint_nodes"]
                / config["infrastructure"]["cloud_nodes"]
            )
        ),
    ]


def get_kubernetes_worker_output(config, machines, get_description=False):
    """Get Kubernetes worker output in the canonical application-runtime shape."""
    logging.info("Gather output from subscribers")

    command = [
        "kubectl",
        "get",
        "pods",
        "-o=custom-columns=NAME:.metadata.name,STATUS:.status.phase",
        "--sort-by=.spec.nodeName",
    ]
    output, error = machines[0].process(config, command, ssh=config["cloud_ssh"][0])[0]

    if (error and not all("[CONTINUUM]" in line for line in error)) or not output:
        logging.error("".join(error))
        sys.exit(1)

    offset = 0
    for offset, line in enumerate(output):
        if "NAME" in line and "STATUS" in line:
            break

    commands = []
    pods = []
    for line in output[1 + offset :]:
        if "CONTINUUM" in line:
            break

        pod = line.split(" ")[0]
        sub_pods_mode = False
        sub_pods = 1
        if config_access.orchestrator_value(config, "kube_deployment") == "container":
            sub_pods_mode = True
            sub_pods = (
                (config["infrastructure"]["cloud_nodes"] - 1)
                * config_access.benchmark_param_int(config, "applications_per_worker")
            )

        if get_description:
            pod_command = ["kubectl", "get", "pod", pod, "-o", "yaml"]
            for _ in range(sub_pods):
                commands.append(pod_command)
                pods.append(pod)
            continue

        for index in range(1, sub_pods + 1):
            container = "%s empty-%i" % (pod, index) if sub_pods_mode else pod
            commands.append(["kubectl", "logs", "--timestamps=true", container])
            pods.append(container)

    batched_command = '"'
    for pod_command in commands:
        batched_command += " ".join(pod_command) + ';echo "DELIMITER01234";'
    batched_command += '"'

    output, error = machines[0].process(
        config, batched_command, ssh=config["cloud_ssh"][0], shell=True
    )[0]

    if (error and not all("[CONTINUUM]" in line for line in error)) or not output:
        logging.error("Worker log collection failed: %s", "".join(error))
        sys.exit(1)

    logging.debug("Assign output to correct pod/container")

    worker_output = []
    entry = []
    output_index = 0
    for line in output:
        line = line.rstrip()
        if "DELIMITER01234" in line:
            if get_description:
                worker_output.append(entry)
            else:
                worker_output.append([pods[output_index], entry])
                output_index += 1
            entry = []
        else:
            entry.append(line)

    return worker_output


def _wait_for_docker_workers(config, machines, ssh_targets, container_names, status_command):
    """Wait until each named worker container reports an Up status."""
    time.sleep(10)

    for worker_ssh in ssh_targets:
        deployed = False
        while not deployed:
            output, error = machines[0].process(
                config,
                status_command,
                shell=True,
                ssh=worker_ssh,
            )[0]

            if error:
                logging.error("".join(error))
                sys.exit(1)
            if not output:
                logging.error("No output from docker container")
                sys.exit(1)

            status_line = None
            for line in output:
                for container_name in container_names:
                    if container_name in line:
                        status_line = line

            if status_line is None:
                logging.error(
                    "ERROR: Could not find the status of any container running in VM %s: %s",
                    worker_ssh.split("@")[0],
                    "".join(output),
                )
                sys.exit(1)

            parsed = status_line.rstrip().split(" ")
            if parsed[1] == "Up":
                deployed = True
            else:
                time.sleep(5)


def start_worker_mist(config, machines, app_vars):
    """Start mist worker containers and return their deterministic container names."""
    logging.info("Deploy Docker containers on endpoints with publisher application")

    commands = []
    ssh_targets = []
    container_names = []

    for worker_ssh in config["edge_ssh"]:
        container_name = worker_ssh.split("@")[0]
        worker_ip = worker_ssh.split("@")[1]
        env = list(app_vars) + ["MQTT_LOCAL_IP=%s" % (worker_ip,)]

        command = (
            [
                "docker",
                "container",
                "run",
                "--detach",
                "--cpus=%s" % (config_access.benchmark_param_float(config, "application_worker_cpu")),
                "--memory=%sg" % (
                    config_access.benchmark_param_float(config, "application_worker_memory")
                ),
                "--network=host",
            ]
            + ["--env %s" % (entry,) for entry in env]
            + [
                "--name",
                container_name,
                os.path.join(config["registry"], config["images"]["worker"].split(":")[1]),
            ]
        )

        commands.append(command)
        ssh_targets.append(worker_ssh)
        container_names.append(container_name)

    results = machines[0].process(config, commands, ssh=ssh_targets)
    for ssh_target, (output, error) in zip(ssh_targets, results):
        logging.debug("Check output of mist endpoint start in ssh [%s]", ssh_target)
        if error and "Your kernel does not support swap limit capabilities" not in error[0]:
            logging.error("".join(error))
            sys.exit(1)
        if not output:
            logging.error("No output from docker container")
            sys.exit(1)

    logging.info("Wait for Mist applications to be deployed")
    _wait_for_docker_workers(
        config,
        machines,
        config["edge_ssh"],
        container_names,
        'docker container ls -a --format \\"{{.ID}}: {{.Status}} {{.Names}}\\"',
    )
    return container_names


def start_worker_baremetal(config, machines, app_vars):
    """Start baremetal worker containers and return their deterministic container names."""
    logging.info("Deploy Docker containers on endpoints with publisher application")

    if config["infrastructure"]["cloud_nodes"] != 1 and config["infrastructure"]["edge_nodes"] != 0:
        logging.error("ERROR: Baremetal currently only works with #clouds==1 and #edges==0")
        sys.exit(1)

    period_scaler = 100000
    period = int(config["infrastructure"]["cloud_cores"] * period_scaler)
    quota = int(period * config["infrastructure"]["cloud_quota"])
    container_name = config["cloud_ssh"][0].split("@")[0]

    env_list = []
    for entry in app_vars:
        env_list.extend(["--env", entry])

    command = (
        [
            "docker",
            "container",
            "run",
            "--detach",
            "--memory=%ig" % (config["infrastructure"]["cloud_memory"]),
            "--cpu-period=%i" % (period),
            "--cpu-quota=%i" % (quota),
            "--network=host",
        ]
        + env_list
        + [
            "--name",
            container_name,
            os.path.join(config["registry"], config["images"]["worker"].split(":")[1]),
        ]
    )

    output, error = machines[0].process(config, command)[0]
    logging.debug("Check output of worker container")
    if error and "Your kernel does not support swap limit capabilities" not in error[0]:
        logging.error("".join(error))
        sys.exit(1)
    if not output:
        logging.error("No output from docker container")
        sys.exit(1)

    logging.info("Wait for baremetal worker applications to be deployed")
    _wait_for_docker_workers(
        config,
        machines,
        config["cloud_ssh"],
        [container_name],
        'docker container ls -a --format "{{.ID}}: {{.Status}} {{.Names}}"',
    )
    return [container_name]


def get_docker_worker_output(config, machines, container_names):
    """Get mist/baremetal worker output in the canonical `[name, lines]` shape."""
    logging.info("Gather output from subscribers")

    commands = [["docker", "logs", "-t", container_name] for container_name in container_names]
    if config["infrastructure"]["provider"] == "baremetal":
        ssh_process_targets = None
        ssh_log_labels = config["cloud_ssh"]
    else:
        ssh_process_targets = config["edge_ssh"]
        ssh_log_labels = config["edge_ssh"]

    results = machines[0].process(config, commands, ssh=ssh_process_targets)

    worker_output = []
    for container_name, ssh_target, (output, error) in zip(container_names, ssh_log_labels, results):
        logging.info("Get output from mist worker %s on VM %s", container_name, ssh_target)
        if error:
            logging.error("".join(error))
            sys.exit(1)
        if not output:
            logging.error("Container %s output empty", container_name)
            sys.exit(1)
        worker_output.append([container_name, [line.rstrip() for line in output]])

    return worker_output


def get_worker_output(config, machines, container_names=None, get_description=False):
    """Get worker output for the current application runtime path."""
    if config_access.orchestrator_name(config) in ("mist", "baremetal"):
        return get_docker_worker_output(config, machines, container_names)

    return get_kubernetes_worker_output(config, machines, get_description=get_description)
