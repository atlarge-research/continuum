"""Application-phase runtime helpers.

These helpers own benchmark-launch and non-Kubernetes worker runtime details so
resource-manager modules can stay focused on platform installation and generic
execution plumbing.
"""

import logging
import os
import sys
import time

import pandas as pd

from input.configuration import config_access


def kubernetes_deployment_mode(config):
    """Return the Kubernetes launch strategy, matching the orchestrator default."""
    return config_access.orchestrator_value_optional(config, "kube_deployment", default="pod")


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
    kube_deployment = kubernetes_deployment_mode(config)
    if kube_deployment == "file":
        target = "/home/%s/jobs" % (machines[0].cloud_controller_names[0])
        command = "\"date +'%%s.%%N'; kubectl apply -f %s\"" % (target)
    elif kube_deployment == "call":
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
        if len(start_list) == 1 and kubernetes_deployment_mode(config) == "file":
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


def run_kubernetes_benchmark_playbook(config, app_vars, runner=None):
    """Run the generated benchmark launch playbook for Kubernetes workloads."""
    playbook = resolve_benchmark_launch_playbook(config, runner=runner)
    if runner is None:
        logging.error("Runner is required for Kubernetes launch benchmark orchestration")
        sys.exit(1)
    runner.run_playbook(playbook, inventory="vms", extra_vars=app_vars)


def resolve_benchmark_launch_playbook(config, runner=None):
    """Resolve the benchmark-launch playbook path for the active app/orchestrator.

    Prefer a generated ``.continuum/launch_benchmark.yml`` when present, but fall back
    to the checked-in application playbook so resumed application-only runs do not
    depend on a missing generation step.
    """
    generated_playbook = os.path.join(
        config["infrastructure"]["base_path"], ".continuum/launch_benchmark.yml"
    )
    if os.path.isfile(generated_playbook):
        return generated_playbook

    repo_root = getattr(runner, "repo_root", None) or os.path.abspath(config.get("base", "."))
    benchmark_stage_type = config_access.benchmark_primary_stage_type(config)
    orchestrator_name = config_access.orchestrator_name(config)
    kube_deployment = config_access.orchestrator_value_optional(config, "kube_deployment")

    orchestrator_tokens = []
    for token in (
        orchestrator_name,
        orchestrator_name.replace("_", "-"),
        orchestrator_name.replace("-", "_"),
    ):
        if token not in orchestrator_tokens:
            orchestrator_tokens.append(token)

    candidates = []
    for token in orchestrator_tokens:
        if kube_deployment:
            candidates.append(
                os.path.join(
                    repo_root,
                    "application",
                    benchmark_stage_type,
                    "launch_benchmark_%s_%s.yml" % (token, kube_deployment),
                )
            )
        candidates.append(
            os.path.join(
                repo_root,
                "application",
                benchmark_stage_type,
                "launch_benchmark_%s.yml" % (token),
            )
        )

    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate

    logging.error(
        "Could not resolve benchmark launch playbook. Tried generated path %s and repo candidates %s",
        generated_playbook,
        ", ".join(candidates),
    )
    sys.exit(1)


def kubernetes_worker_global_vars(config, worker_apps, cpu_req, pull_policy):
    """Build shared Kubernetes launch variables from planner/runtime handoff metadata."""
    planner_handoff = config_access.planner_runtime_handoff(config)
    benchmark_pipeline_handoffs = planner_handoff["benchmark_stages"]
    software_module_handoffs = planner_handoff["software_modules"]
    benchmark_handoff = benchmark_pipeline_handoffs[0]
    global_vars = {
        "app_name": config_access.benchmark_primary_stage_type(config).replace("_", "-"),
        "image": os.path.join(config["registry"], config["images"]["worker"].split(":")[1]),
        "memory_req": int(
            config_access.benchmark_param_float(config, "application_worker_memory") * 1000
        ),
        "cpu_req": cpu_req,
        "replicas": worker_apps,
        "pull_policy": pull_policy,
        "planner_handoff": planner_handoff,
        "benchmark_handoff": benchmark_handoff,
        "benchmark_pipeline_handoffs": benchmark_pipeline_handoffs,
        "software_module_handoffs": software_module_handoffs,
        "benchmark_stage_id": benchmark_handoff["id"],
        "benchmark_stage_type": benchmark_handoff["type"],
        "benchmark_selector_id": benchmark_handoff["selector_id"],
        "benchmark_resolved_vm_ids": benchmark_handoff["resolved_vm_ids"],
        "benchmark_resolved_resources": benchmark_handoff["resolved_resources"],
        "benchmark_scope_identities": benchmark_handoff["scope_identities"],
        "benchmark_tags": benchmark_handoff["tags"],
        "benchmark_resource_counts_by_tier": benchmark_handoff["resource_counts_by_tier"],
    }
    global_vars.update(
        config_access.orchestrator_overrides(config, ("runtime", "runtime_filesystem"))
    )
    return global_vars


def kubernetes_worker_app_count(config):
    """Return the number of benchmark worker app instances for the active mode."""
    apps_per_worker = config_access.benchmark_param_int(config, "applications_per_worker")
    return kubernetes_worker_count(config) * apps_per_worker


def kubernetes_worker_count(config):
    """Return the number of worker nodes targeted by the active mode."""
    if config["mode"] == "cloud":
        return config["infrastructure"]["cloud_nodes"] - 1
    if config["mode"] == "edge":
        return config["infrastructure"]["edge_nodes"]

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
        if kubernetes_deployment_mode(config) == "container":
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


def cache_kubernetes_workers(config, machines, app_vars, runner=None):
    """Start short-lived Kubernetes jobs to warm worker images before the real run."""
    logging.info("Cache subscriber pods on %s", config["mode"])

    if config["mode"] == "cloud":
        worker_apps = kubernetes_worker_count(config)
        cores = config["infrastructure"]["cloud_cores"]
    elif config["mode"] == "edge":
        worker_apps = kubernetes_worker_count(config)
        cores = config["infrastructure"]["edge_cores"]
    else:
        logging.error("Unsupported benchmark worker mode for Kubernetes cache: %s", config["mode"])
        sys.exit(1)

    global_vars = kubernetes_worker_global_vars(
        config,
        worker_apps,
        float(cores * 0.5),
        "IfNotPresent",
    )
    all_vars = {**global_vars, **app_vars}
    run_kubernetes_benchmark_playbook(config, all_vars, runner=runner)

    kube_deployment = kubernetes_deployment_mode(config)
    if kube_deployment == "file":
        manifest_path = "/home/%s/jobs" % (machines[0].cloud_controller_names[0])
        command = "kubectl apply -f %s" % (manifest_path)
    elif kube_deployment == "call":
        manifest_path = "/home/%s/jobs" % (machines[0].cloud_controller_names[0])
        command = "for filename in /home/%s/jobs/*; do kubectl apply -f $filename & done" % (
            machines[0].cloud_controller_names[0]
        )
        command = '"%s"' % (command)
    else:
        manifest_path = "/home/%s/job-template.yaml" % (machines[0].cloud_controller_names[0])
        command = "kubectl apply -f %s" % (manifest_path)

    output, error = machines[0].process(config, command, shell=True, ssh=config["cloud_ssh"][0])[0]
    if not output or not any("job.batch" in line and "created" in line for line in output):
        logging.error("Could not deploy pods: %s", "".join(output))
        logging.error("With error: %s", "".join(error))
        sys.exit(1)
    if error and not all("[CONTINUUM]" in line for line in error):
        logging.error("Could not deploy pods: %s", "".join(error))
        sys.exit(1)

    time.sleep(10)
    logging.info("Deployed %i %s applications", worker_apps, config["mode"])

    pending = True
    completed = 0
    while completed < worker_apps:
        if pending:
            command = [
                "kubectl",
                "get",
                "pods",
                "-o=custom-columns=NAME:.metadata.name,STATUS:.status.phase",
                "--sort-by=.spec.nodeName",
            ]
            output, error = machines[0].process(config, command, ssh=config["cloud_ssh"][0])[0]
            if error and any("couldn't find any field with path" in line for line in error):
                logging.debug("Retry getting list of kubernetes pods")
                time.sleep(5)
                pending = True
                continue
            if (error and not all("[CONTINUUM]" in line for line in error)) or not output:
                logging.error("".join(error))
                sys.exit(1)

        offset = 0
        for offset, line in enumerate(output):
            if "NAME" in line and "STATUS" in line:
                break

        line = output[completed + 1 + offset].rstrip().split(" ")
        app_name = line[0]
        app_status = line[-1]
        if app_status in ["Pending", "Running"]:
            time.sleep(5)
            pending = True
        elif app_status == "Succeeded":
            completed += 1
            pending = False
        else:
            logging.error(
                "Container on cloud/edge %s has status %s, expected Pending, Running, or Succeeded",
                app_name,
                app_status,
            )
            sys.exit(1)

    command = ["kubectl", "delete", "-f", manifest_path]
    output, error = machines[0].process(config, command, ssh=config["cloud_ssh"][0])[0]
    if not output or not any("job.batch" in line and "deleted" in line for line in output):
        logging.error('Output does not contain "job.batch" and "deleted": %s', "".join(output))
        sys.exit(1)
    if error and not all("[CONTINUUM]" in line for line in error):
        logging.error("".join(error))
    time.sleep(10)


def wait_kubernetes_workers_ready(config, machines, get_starttime):
    """Wait for benchmark worker pods to reach Running/Succeeded after submission."""
    if kubernetes_deployment_mode(config) == "container":
        worker_apps = 1
    else:
        worker_apps = kubernetes_worker_app_count(config)

    status = []
    timeout_seconds = 900
    loop_start_t = time.time()

    while True:
        command = (
            "date +'%s.%N'; kubectl get pods "
            + "-o=custom-columns=NAME:.metadata.name,STATUS:.status.phase --sort-by=.spec.nodeName"
        )
        output, error = machines[0].process(
            config, command, shell=True, ssh=config["cloud_ssh"][0]
        )[0]

        if error and any("couldn't find any field with path" in line for line in error):
            continue
        if error and not all("[CONTINUUM]" in line for line in error):
            logging.error("".join(error))
            sys.exit(1)
        if not output:
            logging.error("Could not fetch Kubernetes worker pod status")
            sys.exit(1)

        start_t = float(output[0])
        output = output[1:]

        status_entry = {
            "time_orig": start_t,
            "time": start_t,
            "Arriving": 0,
            "Pending": 0,
            "ContainerCreating": 0,
            "Running": 0,
            "Succeeded": 0,
        }

        offset = 0
        for offset, line in enumerate(output):
            if "NAME" in line and "STATUS" in line:
                break

        for line in output[1 + offset :]:
            if "CONTINUUM" in line:
                break

            line_split = line.rstrip().split(" ")
            app_name = line_split[0]
            app_status = line_split[-1]
            if app_status in ["Failed", "Unknown", "ErrImageNeverPull"]:
                logging.error(
                    'Container on cloud/edge %s has status %s, expected "Pending" or "Running"',
                    app_name,
                    app_status,
                )
                sys.exit(1)
            status_entry[app_status] += 1

        pods_in_system = (
            status_entry["Pending"]
            + status_entry["Running"]
            + status_entry["Succeeded"]
            + status_entry["ContainerCreating"]
        )
        status_entry["Arriving"] = worker_apps - pods_in_system
        status.append(status_entry)

        if status_entry["Running"] + status_entry["Succeeded"] == worker_apps:
            break
        if time.time() - loop_start_t > timeout_seconds:
            logging.error("Timeout waiting for pods to be running")
            sys.exit(1)
        time.sleep(3)

    if get_starttime:
        init_t = status[0]["time"]
        for stat in status:
            stat["time"] -= init_t
        return status
    return None


def start_kubernetes_workers(config, machines, app_vars, get_starttime=False, runner=None):
    """Render and launch Kubernetes benchmark worker jobs for the active benchmark stage."""
    logging.info("Start subscriber pods on %s", config["mode"])

    worker_apps = kubernetes_worker_app_count(config)
    pull_policy = (
        "Never"
        if config_access.orchestrator_bool_optional(config, "cache_worker", default=False)
        else "IfNotPresent"
    )
    global_vars = kubernetes_worker_global_vars(
        config,
        worker_apps,
        config_access.benchmark_param_float(config, "application_worker_cpu"),
        pull_policy,
    )
    all_vars = {**global_vars, **app_vars}
    run_kubernetes_benchmark_playbook(config, all_vars, runner=runner)

    if get_starttime:
        return launch_kubernetes_with_starttime(config, machines)
    return (None, None)


def start_worker(config, machines, app_vars, get_starttime=False, runner=None):
    """Start benchmark workers for the active orchestrator/runtime path."""
    orchestrator_name = config_access.orchestrator_name(config)
    if orchestrator_name == "mist":
        return start_worker_mist(config, machines, app_vars)
    if orchestrator_name == "baremetal":
        return start_worker_baremetal(config, machines, app_vars)

    starttime, kubectl_output = start_kubernetes_workers(
        config,
        machines,
        app_vars,
        get_starttime=get_starttime,
        runner=runner,
    )
    status = wait_kubernetes_workers_ready(config, machines, get_starttime)
    return starttime, kubectl_output, status


def get_kubernetes_control_output(config, machines, starttime, status):
    """Collect and parse Kubernetes control-plane benchmark logs for kubecontrol flows."""
    logging.info("Collect and parse output from Kubernetes controlplane components")

    command = """\"cd /var/log && \
        sudo su -c \\\"grep -ri --exclude continuum.txt '\\[continuum\\]' > continuum.txt\\\"\""""
    results = machines[0].process(config, command, shell=True, ssh=config["cloud_ssh"][0])

    if len(config["cloud_ssh"]) > 1:
        command = """\"sudo su -c \\\"journalctl -u kubelet | \
            grep -i '\\[continuum\\]' > /var/log/continuum.txt\\\"\""""
        results += machines[0].process(config, command, shell=True, ssh=config["cloud_ssh"][1:])

    for _, error in results:
        if error:
            logging.error("".join(error))
            sys.exit(1)

    command = """\"cd /var/log && \
        sudo cp -r pods pods-continuum\""""
    results = machines[0].process(config, command, shell=True, ssh=config["cloud_ssh"])
    for _, error in results:
        if error:
            logging.error("".join(error))
            sys.exit(1)

    outputs = []
    for ssh in zip(config["cloud_ssh"]):
        command = ["sudo", "cat", "/var/log/continuum.txt"]
        output, error = machines[0].process(config, command, ssh=ssh)[0]
        if error:
            logging.error("".join(error))
            sys.exit(1)
        outputs.append(output)

    components = ["kubelet", "scheduler", "apiserver", "proxy", "controller-manager"]
    parsed = {}
    for ssh, output in zip(config["cloud_ssh"], outputs):
        name = ssh.split("@")[0]
        parsed[name] = {}
        for line in output:
            line = line.strip()

            component = ""
            for candidate in components:
                if candidate in line:
                    component = candidate
                    break

            if component == "":
                logging.debug("[WARNING] No component in line: %s", line)
                continue

            parsed[name].setdefault(component, [])
            time_obj, parsed_line = parse_custom_kubernetes_splits(line)
            if time_obj is False:
                logging.debug("Couldn't properly parse line: %s", parsed_line)
                continue
            parsed[name][component].append([time_obj, parsed_line])

    endtime = status[-1]["time_orig"]
    parsed_copy = {}
    for node, output in parsed.items():
        parsed_copy[node] = {}
        for component, entries in output.items():
            parsed_copy[node][component] = []
            for entry in entries:
                seconds_per_hour = float(3600)
                while entry[0] - starttime < seconds_per_hour:
                    entry[0] += seconds_per_hour
                while entry[0] - starttime > seconds_per_hour:
                    entry[0] -= seconds_per_hour
                if entry[0] >= starttime and entry[0] <= endtime:
                    parsed_copy[node][component].append(entry)

    return parsed_copy, endtime


def start_kubernetes_resource_metrics(config, machines):
    """Start kubecontrol resource-metric collection scripts on the active cluster."""
    logging.info("Launch metric server")

    command = ["kubectl", "top", "nodes"]
    while True:
        _, error = machines[0].process(config, command, ssh=config["cloud_ssh"][0])[0]
        if error and not all("[CONTINUUM]" in line for line in error):
            logging.debug("Wait for metric-server to come online")
            time.sleep(5)
        else:
            break

    command = "\"bash -c 'nohup python3 -u resource_usage.py -v > resource_usage.txt 2>&1 &'\""
    machines[0].process(config, command, shell=True, ssh=config["cloud_ssh"][0], wait=False)

    command = (
        "\"bash -c 'nohup python3 -u resource_usage_os.py -v > resource_usage_os.txt 2>&1 &'\""
    )
    machines[0].process(config, command, shell=True, ssh=config["cloud_ssh"], wait=False)


def filter_kubernetes_resource_metrics(config, starttime, endtime):
    """Filter `kubectl top` metrics to the benchmark window and normalize timestamps."""
    logging.debug("Filter kube metric stats")
    path = os.path.join(config["infrastructure"]["base_path"], ".continuum/resource_usage.csv")
    df = pd.read_csv(path)
    df["timestamp"] = df["timestamp"] / 10**9
    pd.options.mode.chained_assignment = None
    df_filtered = df.loc[
        (df["timestamp"] > (starttime - 1.0)) & (df["timestamp"] < (endtime + 1.0))
    ]
    df_filtered["timestamp"] -= starttime
    return df_filtered


def filter_os_resource_metrics(config, starttime, endtime):
    """Filter guest OS resource metrics to the benchmark window and merge all cloud VMs."""
    logging.debug("Filter os metric stats")

    dfs = []
    for vm_name in [vm_name.split("@")[0] for vm_name in config["cloud_ssh"]]:
        path = os.path.join(
            config["infrastructure"]["base_path"],
            ".continuum/resource_usage_os-%s.csv" % (vm_name),
        )
        df = pd.read_csv(path)
        df["timestamp"] = df["timestamp"] / 10**9

        df_filtered = df.loc[
            (df["timestamp"] > (starttime - 1.0)) & (df["timestamp"] < (endtime + 1.0))
        ]
        df_filtered["timestamp"] -= starttime
        df_filtered.rename(
            columns={
                "timestamp": "Time (s)",
                "cpu-used (%)": "cpu-used %s" % (vm_name) + " (%)",
                "memory-used (%)": "memory-used %s" % (vm_name) + " (%)",
            },
            inplace=True,
        )
        dfs.append(df_filtered.copy(deep=True))

    return pd.concat(dfs)


def get_kubernetes_resource_output(config, machines, starttime, endtime, runner=None):
    """Fetch kubecontrol resource metrics from VMs and return filtered pandas dataframes."""
    logging.info("Fetch the resource utilization data from the controlplane VM")

    if runner is None:
        logging.error("Runner is required for Kubernetes resource metrics retrieval")
        sys.exit(1)
    runner.run_playbook("playbooks/resource_manager/k8s_resource_usage_back.yml")
    runner.run_playbook("playbooks/resource_manager/k8s_resource_usage_os_back.yml")

    return (
        filter_kubernetes_resource_metrics(config, starttime, endtime),
        filter_os_resource_metrics(config, starttime, endtime),
    )


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
