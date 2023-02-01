"""\
Setup Kubernetes on cloud
"""

import logging
import os
import sys
import time

from infrastructure import ansible


def add_options(_config):
    """Add config options for a particular module

    Args:
        config (ConfigParser): ConfigParser object

    Returns:
        list(list()): Options to add
    """
    settings = [["cache_worker", bool, lambda x: x in [True, False], False, False]]
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
        or config["infrastructure"]["endpoint_nodes"] < 1
    ):
        parser.error("ERROR: Kubernetes requires #clouds>=2, #edges=0, #endpoints>=1")
    elif (config["infrastructure"]["cloud_nodes"] - 1) % config["infrastructure"][
        "endpoint_nodes"
    ] != 0:
        parser.error("ERROR: Kubernetes requires (#clouds-1) %% #endpoints == 0 (-1 for control)")


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

    # Setup cloud worker
    commands.append(
        [
            "ansible-playbook",
            "-i",
            os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_vms"),
            os.path.join(config["infrastructure"]["base_path"], ".continuum/cloud/install.yml"),
        ]
    )

    results = machines[0].process(config, commands)

    # Check playbooks
    for command, (output, error) in zip(commands, results):
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


def cache_worker(config, machines, app_vars):
    """Start Kube applications for caching, so the real app doesn't need to load images

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
        app_vars (dict): Dictionary of variables for a specific app
    """
    logging.info("Cache subscriber pods on %s", config["mode"])

    # Set parameters based on mode
    if config["mode"] == "cloud":
        worker_apps = config["infrastructure"]["cloud_nodes"] - 1
        cores = config["infrastructure"]["cloud_cores"]
    elif config["mode"] == "edge":
        worker_apps = config["infrastructure"]["edge_nodes"]
        cores = config["infrastructure"]["edge_cores"]

    # Global variables for each applications
    # cpu_req = cores - 0.4
    #   Kubernetes services take up some CPU space, and we do not want to oversubscribe
    global_vars = {
        "app_name": config["benchmark"]["application"].replace("_", "-"),
        "image": "%s/%s" % (config["registry"], config["images"]["worker"].split(":")[1]),
        "memory_req": int(config["benchmark"]["application_worker_memory"] * 1000),
        "cpu_req": cores - 0.4,
        "replicas": worker_apps - 1,  # 0 indexed comparison
        "pull_policy": "IfNotPresent",
    }

    # Merge the two var dicts
    all_vars = {**global_vars, **app_vars}

    # Parse to string
    vars_str = ""
    for k, v in all_vars.items():
        vars_str += str(k) + "=" + str(v) + " "

    # Launch applications on cloud/edge
    command = 'ansible-playbook -i %s --extra-vars "%s" %s' % (
        os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_vms"),
        vars_str[:-1],
        os.path.join(config["infrastructure"]["base_path"], ".continuum/launch_benchmark.yml"),
    )

    ansible.check_output(machines[0].process(config, command, shell=True)[0])

    # This only creates the file we need, now launch the benchmark
    command = (
        "kubectl apply --kubeconfig=/home/cloud_controller/.kube/config "
        + "-f /home/cloud_controller/job-template.yaml"
    )
    output, error = machines[0].process(config, command, shell=True, ssh=config["cloud_ssh"][0])[0]

    if not output or not ("job.batch" in output[0] and "created" in output[0]):
        logging.error("Could not deploy pods: %s", "".join(output))
        sys.exit()
    if error and not all("[CONTINUUM]" in l for l in error):
        logging.error("Could not deploy pods: %s", "".join(error))
        sys.exit()

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
                sys.exit()

        line = output[i + 1].rstrip().split(" ")
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
            sys.exit()

    # All apps have succesfully been executed, now kill them
    command = [
        "kubectl",
        "delete",
        "--kubeconfig=/home/cloud_controller/.kube/config",
        "-f",
        "/home/cloud_controller/job-template.yaml",
    ]
    output, error = machines[0].process(config, command, ssh=config["cloud_ssh"][0])[0]

    if not output or not ("job.batch" in output[0] and "deleted" in output[0]):
        logging.error('Output does not contain "job.batch" and "deleted": %s', "".join(output))
        sys.exit()
    elif error and not all("[CONTINUUM]" in l for l in error):
        logging.error("".join(error))

    time.sleep(10)


def start_worker(config, machines, app_vars, get_starttime=False):
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

    # Set parameters based on mode
    if config["mode"] == "cloud":
        worker_apps = (config["infrastructure"]["cloud_nodes"] - 1) * config["benchmark"][
            "applications_per_worker"
        ]
    elif config["mode"] == "edge":
        worker_apps = (
            config["infrastructure"]["edge_nodes"] * config["benchmark"]["applications_per_worker"]
        )

    # Global variables for each applications
    global_vars = {
        "app_name": config["benchmark"]["application"].replace("_", "-"),
        "image": os.path.join(config["registry"], config["images"]["worker"].split(":")[1]),
        "memory_req": int(config["benchmark"]["application_worker_memory"] * 1000),
        "cpu_req": config["benchmark"]["application_worker_cpu"],
        "replicas": worker_apps - 1,  # 0 indexed comparison
        "pull_policy": "Never",
    }

    # Application-specific variables
    if config["benchmark"]["application"] == "image_classification":
        app_vars = {
            "container_port": 1883,
            "mqtt_logs": True,
            "endpoint_connected": int(config["infrastructure"]["endpoint_nodes"] / worker_apps),
            "cpu_threads": max(1, int(config["benchmark"]["application_worker_cpu"])),
        }

    # Merge the two var dicts
    all_vars = {**global_vars, **app_vars}

    # Parse to string
    vars_str = ""
    for k, v in all_vars.items():
        vars_str += str(k) + "=" + str(v) + " "

    # Launch applications on cloud/edge
    command = 'ansible-playbook -i %s --extra-vars "%s" %s' % (
        os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_vms"),
        vars_str[:-1],
        os.path.join(config["infrastructure"]["base_path"], ".continuum/launch_benchmark.yml"),
    )

    ansible.check_output(machines[0].process(config, command, shell=True)[0])

    if get_starttime:
        starttime = 0.0
        # TODO: Remove this part, use first print in kubectl itself instead
        # TODO: Move this application specific code properly to the app folders
        #       with classes etc.
        # This only creates the file we need, now launch the benchmark
        command = (
            "\"date +'%s.%N'; kubectl apply --kubeconfig=/home/cloud_controller/.kube/config "
            + '-f /home/cloud_controller/job-template.yaml"'
        )
        output, error = machines[0].process(
            config, command, shell=True, ssh=config["cloud_ssh"][0]
        )[0]

        if len(output) < 2 or "job.batch/empty created" not in output[1]:
            logging.error("Could not deploy pods: %s", "".join(output))
            sys.exit()
        if error and not all("[CONTINUUM]" in l for l in error):
            logging.error("Could not deploy pods: %s", "".join(error))
            sys.exit()

        starttime = float(output[0])

    # Waiting for the applications to fully initialize (includes scheduling)
    time.sleep(10)
    logging.info("Deployed %i %s applications", worker_apps, config["mode"])
    logging.info("Wait for subscriber applications to be scheduled and running")

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
                # TODO: Application specific filter again, move to application code
                logging.error("".join(error))
                sys.exit()

        line = output[i + 1].rstrip().split(" ")
        app_name = line[0]
        app_status = line[-1]

        # Check status of app
        if app_status == "Pending":
            time.sleep(5)
            pending = True
        elif app_status == "Running":
            i += 1
            pending = False
        else:
            logging.error(
                'Container on cloud/edge %s has status %s, expected "Pending" or "Running"',
                app_name,
                app_status,
            )
            sys.exit()

    if get_starttime:
        return starttime


def start_endpoint(config, machines):
    """Start running the endpoint containers using Docker.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines

    Returns:
        list(list(str)): Names of docker containers launched per machine
    """
    logging.info("Deploy Docker containers on endpoints with publisher application")

    commands = []
    sshs = []
    container_names = []

    # Calc endpoints per worker
    workers = config["infrastructure"]["cloud_nodes"] + config["infrastructure"]["edge_nodes"]
    if config["mode"] == "cloud" or config["mode"] == "edge":
        # If there is a control machine, dont count that one in
        controllers = [m.cloud_controller for m in machines]
        workers -= controllers

        # Calculate number of endpoints per worker
        end_per_work = int(config["infrastructure"]["endpoint_nodes"] / workers)
        worker_ips = config["cloud_ips_internal"] + config["edge_ips_internal"]
        off = 1
    else:
        end_per_work = 1
        worker_ips = [""]
        off = 10000000

    # For each worker (cloud or edge), connect to end_per_work endpoints.
    for worker_i, worker_ip in enumerate(worker_ips):
        for endpoint_i, endpoint_ssh in enumerate(
            config["endpoint_ssh"][worker_i * end_per_work : (worker_i + off) * end_per_work]
        ):
            # Docker container name and variables depends on deployment mode
            cont_name = "endpoint%i" % (worker_i * end_per_work + endpoint_i)

            # TODO Move this to arguments to make it more flexible
            env = ["FREQUENCY=%i" % (config["benchmark"]["frequency"])]

            if config["mode"] == "cloud" or config["mode"] == "edge":
                cont_name = "%s%i_" % (config["mode"], worker_i) + cont_name
                env.append("MQTT_LOCAL_IP=%s" % (endpoint_ssh.split("@")[1]))
                env.append("MQTT_REMOTE_IP=%s" % (worker_ip))
                env.append("MQTT_LOGS=True")

                if config["control_ips"]:
                    env.append("CLOUD_CONTROLLER_IP=%s" % (config["control_ips"][0]))
            else:
                env.append("CPU_THREADS=%i" % (config["infrastructure"]["endpoint_cores"]))

            logging.info("Launch %s", cont_name)

            # Decide wether to use the endpoint or combined image
            image = "endpoint"
            if config["mode"] == "endpoint":
                image = "combined"

            command = (
                [
                    "docker",
                    "container",
                    "run",
                    "--detach",
                    "--cpus=%i" % (config["benchmark"]["application_endpoint_cpu"]),
                    "--memory=%ig" % (config["benchmark"]["application_endpoint_memory"]),
                    "--network=host",
                ]
                + ["--env %s" % (e) for e in env]
                + [
                    "--name",
                    cont_name,
                    os.path.join(
                        config["registry"],
                        config["images"][image].split(":")[1],
                    ),
                ]
            )

            commands.append(command)
            sshs.append(endpoint_ssh)
            container_names.append(cont_name)

    results = machines[0].process(config, commands, ssh=sshs)

    # Checkout process output
    for ssh, (output, error) in zip(sshs, results):
        logging.debug("Check output of endpoint start in ssh [%s]", ssh)

        if error and "Your kernel does not support swap limit capabilities" not in error[0]:
            logging.error("".join(error))
            sys.exit()
        elif not output:
            logging.error("No output from docker container")
            sys.exit()

    return container_names


def wait_endpoint_completion(config, machines, sshs, container_names):
    """Wait for all containers to be finished running the benchmark on endpoints
    OR for all mist containers, which also use docker so this function can be reused

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
        sshs (list(str)): SSH addresses to edge or endpoint VMs
        container_names (list(str)): Names of docker containers launched
    """
    logging.info("Wait on all endpoint or mist containers to finish")
    time.sleep(10)

    for ssh, cont_name in zip(sshs, container_names):
        logging.info("Wait for container to finish: %s on VM %s", cont_name, ssh.split("@")[0])
        finished = False

        while not finished:
            # Get list of docker containers
            command = 'docker container ls -a --format \\"{{.ID}}: {{.Status}} {{.Names}}\\"'
            ssh_entry = ssh
            if config["infrastructure"]["provider"] == "baremetal":
                command = 'docker container ls -a --format "{{.ID}}: {{.Status}} {{.Names}}"'
                ssh_entry = None

            output, error = machines[0].process(config, command, shell=True, ssh=ssh_entry)[0]

            if error:
                logging.error("".join(error))
                sys.exit()
            elif not output:
                logging.error("No output from docker container")
                sys.exit()

            # Get status of docker container
            status_line = None
            for line in output:
                if cont_name in line:
                    status_line = line

            if status_line is None:
                logging.error(
                    "ERROR: Could not find status of container %s running in VM %s: %s",
                    cont_name,
                    ssh.split("@")[0],
                    "".join(output),
                )
                sys.exit()

            parsed = status_line.rstrip().split(" ")

            # Check status
            if parsed[1] == "Up":
                time.sleep(5)
            elif parsed[1] == "Exited" and parsed[2] == "(0)":
                finished = True
            else:
                logging.error(
                    'ERROR: Container %s failed in VM %s with status "%s"',
                    cont_name,
                    ssh.split("@")[0],
                    status_line,
                )
                sys.exit()

    logging.info("All endpoint or mist containers have finished")


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
        controllers = [m.cloud_controller for m in machines]
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
                # TODO: Application specific filter
                logging.error("".join(error))
                sys.exit()

        # Parse list, get status of app i
        line = output[i + 1].rstrip().split(" ")
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
            sys.exit()


def get_worker_output(config, machines):
    """Get the output of worker cloud / edge applications

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines

    Returns:
        list(list(str)): Output of each container ran on the cloud / edge
    """
    logging.info("Gather output from subscribers")

    # Get list of pods
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
        sys.exit()

    # Gather commands to get logs
    commands = []
    for line in output[1:]:
        container = line.split(" ")[0]
        command = ["kubectl", "logs", "--timestamps=true", container]
        commands.append(command)

    # Get the logs
    results = machines[0].process(config, commands, ssh=config["cloud_ssh"][0])

    # Get the output
    worker_output = []
    for i, (output, error) in enumerate(results):
        if (error and not all("[CONTINUUM]" in l for l in error)) or not output:
            logging.error("Container %i: %s", i, "".join(error))
            sys.exit()

        output = [line.rstrip() for line in output]
        worker_output.append(output)

    return worker_output
