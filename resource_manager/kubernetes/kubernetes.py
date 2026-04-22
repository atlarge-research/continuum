"""\
Setup Kubernetes on cloud
"""

import logging
import os
import sys
import time

import pandas as pd

from application import runtime_helpers as application_runtime_helpers
from input.configuration import config_access
from resource_manager import orchestrator_options, plans


def add_options(_config):
    """[INTERFACE] Add config options for this RM module

    Args:
        config (ConfigParser): ConfigParser object

    Returns:
        list(list()): Options to add
    """
    return (
        orchestrator_options.kubernetes_common_options(
            orchestrator_options.KUBE_VERSIONS_CURRENT
        )
        + orchestrator_options.kube_deployment_options()
    )


def verify_options(parser, config):
    """[INTERFACE] Verify config options for this RM module

    Args:
        parser (ArgumentParser): Argparse object
        config (ConfigParser): ConfigParser object
    """
    if (
        config["infrastructure"]["cloud_nodes"] < 1
        or config["infrastructure"]["edge_nodes"] != 0
        or config["infrastructure"]["endpoint_nodes"] < 0
    ):
        parser.error("ERROR: Kubernetes requires #clouds>=1, #edges=0, #endpoints>=0")
    elif config["infrastructure"]["cloud_nodes"] > 1 and (
        config["infrastructure"]["endpoint_nodes"] % (config["infrastructure"]["cloud_nodes"] - 1)
        != 0
    ):
        parser.error(r"ERROR: Kubernetes requires (#clouds-1) % #endpoints == 0 (-1 for control)")


def start(runner):
    """[INTERFACE] Execute Kubernetes software-phase installation.

    Args:
        runner (AnsibleRunner): Shared Ansible runner with config and machine state.
    """
    from resource_manager import resource_manager

    resource_manager.start(runner)


def base_install_playbook(_config, tier):
    """[INTERFACE] Return Kubernetes base-install playbook for a tier.

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
    """[INTERFACE] Build software-phase plan entries for Kubernetes RM.

    Args:
        config (dict): Parsed configuration.

    Returns:
        list[PlanEntry]: Ordered software-phase execution entries.
    """
    observability_owner = None
    if config_access.has_addon(config, "observability"):
        observability_owner = config_access.software_module_by_type(config, "observability")

    entries = [
        plans.PlanEntry(kind="playbook", playbook="playbooks/resource_manager/k8s_cluster.yml")
    ]
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
    """[INTERFACE] Run post-install verification for Kubernetes RM.

    Args:
        runner (AnsibleRunner): Shared runner instance.
    """
    verify_running_cluster(runner.config, runner.machines)


def _stderr_has_real_error(err_lines):
    """Check if the stderr contains a real error or a transient error we can retry

    Args:
        err_lines (list(str)): List of error lines

    Returns:
        bool: True if the stderr contains a real error, False otherwise
    """
    if not err_lines:
        return False

    # Keep your existing behavior but don't ignore real errors that contain [CONTINUUM]
    s = "".join(err_lines)

    # Strip prefix for detection (cheap and good enough)
    s = s.replace("[CONTINUUM]", "")
    s_lower = s.lower()

    return any(
        x in s_lower
        for x in [
            "error from server:",
            "etcdserver: request timed out",
            "unable to connect to the server",
            "the connection to the server",
            "context deadline exceeded",
            "i/o timeout",
            "connection refused",
        ]
    )


def verify_running_cluster(config, machines):
    """Verify that all nodes in the cluster have status Ready
    If not, either wait until they are ready or stop the framework

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Verify if all nodes in the cluster are connected")

    max_retries = 5
    sleep_time = 5

    cmd_wait = ["kubectl", "wait", "--for=condition=Ready", "node", "--all", "--timeout=10m"]

    for attempt in range(max_retries):
        out, err = machines[0].process(config, cmd_wait, ssh=config["cloud_ssh"][0])[0]
        if not _stderr_has_real_error(err) and out:
            logging.info("All nodes are Ready")
            return

        # Treat as transient unless it's the last attempt
        msg = ("".join(err) or "".join(out) or "").strip()
        logging.warning("kubectl wait failed (attempt %d/%d): %s", attempt, max_retries, msg)

        if attempt < max_retries:
            time.sleep(sleep_time)

    logging.error("Cluster did not become Ready after %d attempts", max_retries)
    sys.exit(1)


def _run_launch_benchmark_playbook(config, _machines, app_vars, runner=None):
    """Run the generated benchmark launch playbook for Kubernetes workloads.

    Args:
        config (dict): Parsed configuration.
        _machines (list[Machine]): Physical machine objects (unused).
        app_vars (dict): Resolved playbook variables.
        runner (AnsibleRunner|None): Shared runner, if available.
    """
    playbook = os.path.join(
        config["infrastructure"]["base_path"], ".continuum/launch_benchmark.yml"
    )
    if runner is None:
        logging.error("Runner is required for Kubernetes launch benchmark orchestration")
        sys.exit(1)
    runner.run_playbook(playbook, inventory="vms", extra_vars=app_vars)


def _worker_global_vars(config, worker_apps, cpu_req, pull_policy):
    """Build shared launch variables for Kubernetes worker workloads."""
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


def cache_worker(config, machines, app_vars, runner=None):
    """Start Kube applications for caching, so the real app doesn't need to load images

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
        app_vars (dict): Dictionary of variables for a specific app
    """
    logging.info("Cache subscriber pods on %s", config["mode"])

    if config["mode"] == "cloud":
        worker_apps = config["infrastructure"]["cloud_nodes"] - 1
        cores = config["infrastructure"]["cloud_cores"]
    elif config["mode"] == "edge":
        worker_apps = config["infrastructure"]["edge_nodes"]
        cores = config["infrastructure"]["edge_cores"]

    global_vars = _worker_global_vars(
        config,
        worker_apps,
        float(cores * 0.5),
        "IfNotPresent",
    )

    all_vars = {**global_vars, **app_vars}
    _run_launch_benchmark_playbook(config, machines, all_vars, runner=runner)

    # This only creates the file we need, now launch the benchmark
    if config_access.orchestrator_value(config, "kube_deployment") == "file":
        # Option "file" launches a kubectl command on an entire directory
        file = "/home/%s/jobs" % (machines[0].cloud_controller_names[0])
        command = "kubectl apply -f %s" % (file)
    elif config_access.orchestrator_value(config, "kube_deployment") == "call":
        # Option "call" launches one kubectl command per job file
        file = "/home/%s/jobs" % (machines[0].cloud_controller_names[0])
        command = "for filename in /home/%s/jobs/*; do kubectl apply -f $filename & done" % (
            machines[0].cloud_controller_names[0]
        )
        command = '"%s"' % (command)
    else:
        file = "/home/%s/job-template.yaml" % (machines[0].cloud_controller_names[0])
        command = "kubectl apply -f %s" % (file)

    output, error = machines[0].process(config, command, shell=True, ssh=config["cloud_ssh"][0])[0]

    if not output or not any("job.batch" in o and "created" in o for o in output):
        logging.error("Could not deploy pods: %s", "".join(output))
        logging.error("With error: %s", "".join(error))
        sys.exit(1)
    if error and not all("[CONTINUUM]" in l for l in error):
        logging.error("Could not deploy pods: %s", "".join(error))
        sys.exit(1)

    # Waiting for the applications to fully initialize
    time.sleep(10)
    logging.info("Deployed %i %s applications", worker_apps, config["mode"])

    pending = True
    i = 0

    while i < worker_apps:
        # Get the list of deployed pods
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

            if (error and not all("[CONTINUUM]" in l for l in error)) or not output:
                logging.error("".join(error))
                sys.exit(1)

        # The first couple of lines may have custom prints
        offset = 0
        for offset, o in enumerate(output):
            if "NAME" in o and "STATUS" in o:
                break

        line = output[i + 1 + offset].rstrip().split(" ")
        app_name = line[0]
        app_status = line[-1]

        # Check status of app
        if app_status in ["Pending", "Running"]:
            time.sleep(5)
            pending = True
        elif app_status == "Succeeded":
            i += 1
            pending = False
        else:
            logging.error(
                "Container on cloud/edge %s has status %s, expected Pending, Running, or Succeeded",
                app_name,
                app_status,
            )
            sys.exit(1)

    # All apps have succesfully been executed, now kill them
    command = ["kubectl", "delete", "-f", file]
    output, error = machines[0].process(config, command, ssh=config["cloud_ssh"][0])[0]

    if not output or not any("job.batch" in o and "deleted" in o for o in output):
        logging.error('Output does not contain "job.batch" and "deleted": %s', "".join(output))
        sys.exit(1)
    elif error and not all("[CONTINUUM]" in l for l in error):
        logging.error("".join(error))

    time.sleep(10)


def start_worker(config, machines, app_vars, get_starttime=False, runner=None):
    """Select the correct function to start the worker application

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
        app_vars (dict OR list): Dictionary or list of variables for a specific app
        get_starttime (bool, optional): Measure invocation time. Defaults to False.

    Returns:
        (datetime): Invocation time of the kubectl apply command that launches the benchmark
        OR
        (list(list(str))): Names of docker containers launched per machine
    """
    if config_access.orchestrator_name(config) == "mist":
        return start_worker_mist(config, machines, app_vars)

    if config_access.orchestrator_name(config) == "baremetal":
        return start_worker_baremetal(config, machines, app_vars)

    # For non-mist/baremetal deployments
    starttime, kubectl_output = start_worker_kube(
        config, machines, app_vars, get_starttime, runner=runner
    )
    status = wait_worker_ready(config, machines, get_starttime)
    return starttime, kubectl_output, status


def wait_worker_ready(config, machines, get_starttime):
    """Wait for the Kubernetes pods to be running

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
        get_starttime (bool, optional): Measure invocation time. Defaults to False.

    Returns (optional):
        (list(dict)): Status of all pods every second
    """
    # Determine number of workers
    # In container mode, all applications are gathered in 1 pod, so we only have 1 worker
    if config_access.orchestrator_value(config, "kube_deployment") == "container":
        worker_apps = 1
    else:
        apps_per_worker = config_access.benchmark_param_int(config, "applications_per_worker")
        if config["mode"] == "cloud":
            worker_apps = (config["infrastructure"]["cloud_nodes"] - 1) * apps_per_worker
        elif config["mode"] == "edge":
            worker_apps = config["infrastructure"]["edge_nodes"] * apps_per_worker

    status = []
    TIMEOUT = 900
    loop_start_t = time.time()

    while True:
        # Get the list of all pods
        command = (
            "\"date +'%s.%N'; kubectl get pods "
            + '-o=custom-columns=NAME:.metadata.name,STATUS:.status.phase --sort-by=.spec.nodeName"'
        )
        output, error = machines[0].process(
            config, command, shell=True, ssh=config["cloud_ssh"][0]
        )[0]

        start_t = float(output[0])
        output = output[1:]

        # No pods are yet shown in the 'kubectl get pods' command
        if error and any("couldn't find any field with path" in line for line in error):
            continue

        # Real crash
        if (error and not all("[CONTINUUM]" in l for l in error)) or not output:
            logging.error("".join(error))
            sys.exit(1)

        # Loop over all pods, check status, and create a list of all current statuses
        # Possible status:
        # - Pending
        # - Running
        # - Succeeded
        # - Failed
        # - Unknown
        # - ContainerCreating
        # - Arriving (not yet shown up in kubectl)
        status_entry = {
            "time_orig": start_t,
            "time": start_t,
            "Arriving": 0,
            "Pending": 0,
            "ContainerCreating": 0,
            "Running": 0,
            "Succeeded": 0,
        }

        # The first couple of lines may have custom prints
        offset = 0
        for offset, o in enumerate(output):
            if "NAME" in o and "STATUS" in o:
                break

        for line in output[1 + offset :]:
            # Some custom output may appear afterwards - ignore
            if "CONTINUUM" in line:
                break

            l = line.rstrip().split(" ")
            app_name = l[0]
            app_status = l[-1]

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

        # Stop if all statuses are running or succeeded
        if status_entry["Running"] + status_entry["Succeeded"] == worker_apps:
            break

        if time.time() - loop_start_t > TIMEOUT:
            logging.error("Timeout waiting for pods to be running")
            sys.exit(1)

        time.sleep(3)

    if get_starttime:
        # Normalize time
        init_t = status[0]["time"]
        for stat in status:
            stat["time"] -= init_t

        return status

    return None


def launch_with_starttime(config, machines):
    """Launch the application by hand using kubectl to time how long the invocation takes

    TODO This is actually specific for the empty app - can we somehow move it to there?

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines

    Returns:
        tuple[float, list[list[object]]]: Invocation timestamp and parsed kubectl trace output.
    """
    return application_runtime_helpers.launch_kubernetes_with_starttime(config, machines)


def start_worker_kube(config, machines, app_vars, get_starttime, runner=None):
    """Start the MQTT subscriber application on cloud / edge workers.
    Submit the job request to the cloud controller, which automatically starts it on the cluster.
    Every cloud / edge worker will only have 1 application running taking up all resources.
    Multiple subscribers per node won't work, they all read the same messages from the MQTT bus.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
        app_vars (dict): Dictionary of variables for a specific app
        get_starttime (bool, optional): Measure invocation time. Defaults to False.

    Returns (optional):
        (datetime): Invocation time of the kubectl apply command that launches the benchmark
    """
    logging.info("Start subscriber pods on %s", config["mode"])

    apps_per_worker = config_access.benchmark_param_int(config, "applications_per_worker")
    if config["mode"] == "cloud":
        worker_apps = (config["infrastructure"]["cloud_nodes"] - 1) * apps_per_worker
    elif config["mode"] == "edge":
        worker_apps = config["infrastructure"]["edge_nodes"] * apps_per_worker

    # Global variables for each applications
    global_vars = _worker_global_vars(
        config,
        worker_apps,
        config_access.benchmark_param_float(config, "application_worker_cpu"),
        "Never",
    )

    all_vars = {**global_vars, **app_vars}
    _run_launch_benchmark_playbook(config, machines, all_vars, runner=runner)

    if get_starttime:
        return application_runtime_helpers.launch_kubernetes_with_starttime(config, machines)

    return (None, None)


def start_worker_mist(config, machines, app_vars):
    """Start running the mist worker subscriber containers using Docker.
    Wait for them to finish, and get their output.
    Every edge worker will only have 1 application running taking up all resources.
    Multiple subscribers per node won't work, they all read the same messages from the MQTT bus.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
        app_vars (list): Dictionary of variables for a specific app

    Returns:
        list(list(str)): Names of docker containers launched per machine
    """
    return application_runtime_helpers.start_worker_mist(config, machines, app_vars)


def start_worker_baremetal(config, machines, app_vars):
    """Start running the endpoint containers using Docker.

    Assumptions for now:
    - You can only have one worker
    - The worker is a cloud node

    Instructions for starting/stopping/installing mosquitto on bare-metal (only requirement)
    - sudo apt install mosquitto=1.6.9-1
    - mosquitto -d -p 1883
    - sudo systemctl start mosquitto.service
    - sudo systemctl stop mosquitto.service

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
        app_vars (list): Dictionary of variables for a specific app

    Returns:
        list(list(str)): Names of docker containers launched per machine
    """
    return application_runtime_helpers.start_worker_baremetal(config, machines, app_vars)


def wait_worker_completion(config, machines):
    """Wait for all containers to be finished running the benchmark on cloud/edge workers

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Wait for pods on cloud/edge workers to finish")
    get_list = True
    i = 0

    workers = config["infrastructure"]["cloud_nodes"] + config["infrastructure"]["edge_nodes"]
    if config["mode"] == "cloud" or config["mode"] == "edge":
        # If there is a control machine, dont count that one in
        controllers = sum(m.cloud_controller for m in machines)
        workers -= controllers

    # On the cloud controller, check the status of each pod, and wait until finished
    while i < workers:
        # Get the list of deployed pods
        if get_list:
            command = [
                "kubectl",
                "get",
                "pods",
                "-o=custom-columns=NAME:.metadata.name,STATUS:.status.phase",
                "--sort-by=.spec.nodeName",
            ]
            output, error = machines[0].process(config, command, ssh=config["cloud_ssh"][0])[0]

            if (error and not all("[CONTINUUM]" in l for l in error)) or not output:
                logging.error("".join(error))
                sys.exit(1)

        # The first couple of lines may have custom prints
        offset = 0
        for offset, o in enumerate(output):
            if "NAME" in o and "STATUS" in o:
                break

        # Parse list, get status of app i
        line = output[i + 1 + offset].rstrip().split(" ")
        app_name = line[0]
        app_status = line[-1]

        # Check status of app i
        if app_status == "Running":
            time.sleep(5)
            get_list = True
        elif app_status == "Succeeded":
            i += 1
            get_list = False
        else:
            logging.error(
                "ERROR: Container on cloud/edge %s has status %s, expected Running or Succeeded",
                app_name,
                app_status,
            )
            sys.exit(1)


def get_worker_output(config, machines, container_names=None, get_description=False):
    """Select the correct function to start the worker application

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
        container_names (list(list(str))): Names of docker containers launched per machine

    Returns:
        list(list(str)): Output of each container ran on the cloud / edge
    """
    return application_runtime_helpers.get_worker_output(
        config,
        machines,
        container_names=container_names,
        get_description=get_description,
    )


def get_worker_output_kube(config, machines, get_description):
    """Get the output of worker cloud / edge applications

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
        get_description (bool): Also output an extensive description of all pod properties

    Returns:
        list(list(str)): Output of each container ran on the cloud / edge
    """
    return application_runtime_helpers.get_kubernetes_worker_output(
        config,
        machines,
        get_description=get_description,
    )


def get_worker_output_mist(config, machines, container_names):
    """Get the output of worker mist applications

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
        container_names (list(list(str))): Names of docker containers launched per machine

    Returns:
        list(list(str)): Output of each container ran as a worker in the mist
    """
    return application_runtime_helpers.get_docker_worker_output(config, machines, container_names)


def get_control_output(config, machines, starttime, status):
    """Get output from Kubernetes control plane components, used to create detailed timeline

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
        starttime (datetime): Invocation time of kubectl apply command that launches the benchmark
        status (list(list(str))): Status of started Kubernetes pods over time
        worker_description (list(list(str))): Extensive description of each container

    Returns:
        dict: Parsed output from control plane components
    """
    logging.info("Collect and parse output from Kubernetes controlplane components")

    # Save custom output in file so you can read it later if needed
    # For control plane
    command = """\"cd /var/log && \
        sudo su -c \\\"grep -ri --exclude continuum.txt '\\[continuum\\]' > continuum.txt\\\"\""""
    results = machines[0].process(config, command, shell=True, ssh=config["cloud_ssh"][0])

    # For worker nodes
    if len(config["cloud_ssh"]) > 1:
        command = """\"sudo su -c \\\"journalctl -u kubelet | \
            grep -i '\\[continuum\\]' > /var/log/continuum.txt\\\"\""""
        results += machines[0].process(config, command, shell=True, ssh=config["cloud_ssh"][1:])

    for _, error in results:
        if error:
            logging.error("".join(error))
            sys.exit(1)

    # Save pods output - it may get overwritten later on
    command = """\"cd /var/log && \
        sudo cp -r pods pods-continuum\""""
    results = machines[0].process(config, command, shell=True, ssh=config["cloud_ssh"])

    for _, error in results:
        if error:
            logging.error("".join(error))
            sys.exit(1)

    # Get output from each cloud node
    outputs = []
    for ssh in zip(config["cloud_ssh"]):
        command = ["sudo", "cat", "/var/log/continuum.txt"]
        output, error = machines[0].process(config, command, ssh=ssh)[0]

        if error:
            logging.error("".join(error))
            sys.exit(1)

        outputs.append(output)

    # Parse output, filter per component, get timestamp and custom output
    components = ["kubelet", "scheduler", "apiserver", "proxy", "controller-manager"]
    parsed = {}

    for ssh, output in zip(config["cloud_ssh"], outputs):
        name = ssh.split("@")[0]
        parsed[name] = {}

        for line in output:
            line = line.strip()

            # Split per Kubernetes controlplane component
            comp = ""
            for c in components:
                if c in line:
                    comp = c
                    break

            if comp == "":
                logging.debug("[WARNING] No component in line: %s", line)
                continue

            if comp not in parsed[name]:
                parsed[name][comp] = []

            time_obj, line = parse_custom_kubernetes_splits(line)
            if time_obj is False:
                logging.debug("Couldn't properly parse line: %s", line)
                continue

            parsed[name][comp].append([time_obj, line])

    # Now filter out everything before starttime and after endtime
    # Starttime and endtime are both in 192031029309.1230910293 format
    endtime = status[-1]["time_orig"]
    parsed_copy = {}
    for node, output in parsed.items():
        parsed_copy[node] = {}
        for component, out in output.items():
            parsed_copy[node][component] = []
            for entry in out:
                # There may be time zone differences between timestamps
                # We assume no 2 prints differ by more than 1 hour
                seconds_per_hour = float(3600)
                while entry[0] - starttime < seconds_per_hour:
                    entry[0] += seconds_per_hour

                while entry[0] - starttime > seconds_per_hour:
                    entry[0] -= seconds_per_hour

                # Now check for time interval
                if entry[0] >= starttime and entry[0] <= endtime:
                    parsed_copy[node][component].append(entry)

    return parsed_copy, endtime


def parse_custom_kubernetes_splits(line):
    """Parse lines from Kubernetes custom output, like:
    I0824 22:23:21.269974    5026 kubectl.go:32] %!s(int64=1692908601269961032) [CONTINUUM] 0400\n

    To: 1692908601.269961032, 0400

    Args:
        line (str): Line to parse

    Returns:
        (float, str): timestamp, output line
    """
    return application_runtime_helpers.parse_custom_kubernetes_splits(line)


def start_resource_metrics(config, machines):
    """Start the resource metrics server by hand

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Launch metric server")

    # First wait for metrics api to be available
    command = ["kubectl", "top", "nodes"]
    while True:
        _, error = machines[0].process(config, command, ssh=config["cloud_ssh"][0])[0]

        if error and not all("[CONTINUUM]" in l for l in error):
            logging.debug("Wait for metric-server to come online")
            time.sleep(5)
        else:
            break

    # Now that the api server is up, launch the script to gather data
    command = "\"bash -c 'nohup python3 -u resource_usage.py -v > resource_usage.txt 2>&1 &'\""
    machines[0].process(config, command, shell=True, ssh=config["cloud_ssh"][0], wait=False)

    # Now launch the other scripts to get OS resource usage -> on all machines
    command = (
        "\"bash -c 'nohup python3 -u resource_usage_os.py -v > resource_usage_os.txt 2>&1 &'\""
    )
    machines[0].process(config, command, shell=True, ssh=config["cloud_ssh"], wait=False)


def get_resource_output(config, machines, starttime, endtime, runner=None):
    """Get the resource usage data from .csv files from VMs and parse it

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
        starttime (datetime): Invocation time of kubectl apply command that launches the benchmark
        endtime (datetime): Time at which the final application is deployed

    Returns:
        (dataframe): Pandas dataframe with resource utilization metrics during our benchmrak deploym
    """
    logging.info("Fetch the resource utilization data from the controlplane VM")

    if runner is None:
        logging.error("Runner is required for Kubernetes resource metrics retrieval")
        sys.exit(1)
    runner.run_playbook("playbooks/resource_manager/k8s_resource_usage_back.yml")
    runner.run_playbook("playbooks/resource_manager/k8s_resource_usage_os_back.yml")

    df1 = filter_metrics_kube(config, starttime, endtime)
    df2 = filter_metrics_os(config, starttime, endtime)

    return df1, df2


def filter_metrics_kube(config, starttime, endtime):
    """Filter the metrics gathered via kubectl top

    Args:
        config (dict): Parsed configuration
        starttime (datetime): Invocation time of kubectl apply command that launches the benchmark
        endtime (datetime): Time at which the final application is deployed

    Returns:
        (dataframe): Pandas dataframe with resource utilization metrics during our benchmrak deploym
    """
    logging.debug("Filter kube metric stats")

    # Now read the file via pandas and:
    # - Only take the timestamps between the start and end of the benchmark
    # - Offset these values compared to the start time of the benchmark (so row 1 starts near 0.0s)
    path = os.path.join(config["infrastructure"]["base_path"], ".continuum/resource_usage.csv")
    df = pd.read_csv(path)
    df["timestamp"] = df["timestamp"] / 10**9

    # Disable warning generated by the lines below
    pd.options.mode.chained_assignment = None

    # Take 1.0 second more on both ends so we can plot the t=0 and t=endtime points
    df_filtered = df.loc[
        (df["timestamp"] > (starttime - 1.0)) & (df["timestamp"] < (endtime + 1.0))
    ]
    df_filtered["timestamp"] -= starttime
    return df_filtered


def filter_metrics_os(config, starttime, endtime):
    """Filter the metrics gathered via OS tools

    Args:
        config (dict): Parsed configuration
        starttime (datetime): Invocation time of kubectl apply command that launches the benchmark
        endtime (datetime): Time at which the final application is deployed

    Returns:
        (dataframe): Pandas dataframe with resource utilization metrics during our benchmrak deploym
    """
    logging.debug("Filter os metric stats")

    # Gather all data from each VM first
    dfs = []
    for vm_name in [vm_name.split("@")[0] for vm_name in config["cloud_ssh"]]:
        path = os.path.join(
            config["infrastructure"]["base_path"], ".continuum/resource_usage_os-%s.csv" % (vm_name)
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

        # Save with deep copy just to be safe
        dfs.append(df_filtered.copy(deep=True))

    # Now save in one big dataframe
    df_final = pd.concat(dfs)
    return df_final
