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
    if config["benchmark"]["resource_manager"] == "mist":
        return start_worker_mist(config, machines, app_vars)
    if config["benchmark"]["resource_manager"] == "baremetal":
        return start_worker_baremetal(config, machines, app_vars)

    return start_worker_kube(config, machines, app_vars, get_starttime)


def launch_with_starttime(config, machines):
    """Launch the application by hand using kubectl to time how long the invocation takes

    TODO This is actually specific for the empty app - can we somehow move it to there?

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines

    Returns:
        (float): Time needed to start the application with kubectl
    """
    starttime = 0.0

    # This only creates the file we need, now launch the benchmark
    command = (
        "\"date +'%s.%N'; kubectl apply --kubeconfig=/home/cloud_controller/.kube/config "
        + '-f /home/cloud_controller/job-template.yaml"'
    )
    output, error = machines[0].process(config, command, shell=True, ssh=config["cloud_ssh"][0])[0]

    if len(output) < 2 or "created" not in output[1]:
        logging.error("Could not deploy pods: %s", "".join(output))
        sys.exit()
    if error and not all("[CONTINUUM]" in l for l in error):
        logging.error("Could not deploy pods: %s", "".join(error))
        sys.exit()

    starttime = float(output[0])
    return starttime


def start_worker_kube(config, machines, app_vars, get_starttime):
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
        starttime = launch_with_starttime(config, machines)

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
    logging.info("Deploy Docker containers on endpoints with publisher application")

    commands = []
    sshs = []
    container_names = []

    for worker_ssh in config["edge_ssh"]:
        cont_name = worker_ssh.split("@")[0]
        worker_ip = worker_ssh.split("@")[1]

        # Set variables for the application
        # TODO: MQTT_LOCAL_IP is app specific, but we only have this info here. Better solution?
        env = app_vars + ["MQTT_LOCAL_IP=%s" % (worker_ip)]

        command = (
            [
                "docker",
                "container",
                "run",
                "--detach",
                "--cpus=%i" % (config["benchmark"]["application_worker_cpu"]),
                "--memory=%ig" % (config["benchmark"]["application_worker_memory"]),
                "--network=host",
            ]
            + ["--env %s" % (e) for e in env]
            + [
                "--name",
                cont_name,
                os.path.join(config["registry"], config["images"]["worker"].split(":")[1]),
            ]
        )

        commands.append(command)
        sshs.append(worker_ssh)
        container_names.append(cont_name)

    results = machines[0].process(config, commands, ssh=sshs)

    # Checkout process output
    for ssh, (output, error) in zip(sshs, results):
        logging.debug("Check output of mist endpoint start in ssh [%s]", ssh)

        if error and "Your kernel does not support swap limit capabilities" not in error[0]:
            logging.error("".join(error))
            sys.exit()
        elif not output:
            logging.error("No output from docker container")
            sys.exit()

    # Wait for containers to be succesfully deployed
    logging.info("Wait for Mist applications to be deployed")
    time.sleep(10)

    for worker_ssh in config["edge_ssh"]:
        deployed = False

        while not deployed:
            command = 'docker container ls -a --format \\"{{.ID}}: {{.Status}} {{.Names}}\\"'
            output, error = machines[0].process(config, command, shell=True, ssh=worker_ssh)[0]

            if error:
                logging.error("".join(error))
                sys.exit()
            elif not output:
                logging.error("No output from docker container")
                sys.exit()

            # Get status of docker container
            status_line = None
            for line in output:
                for cont_name in container_names:
                    if cont_name in line:
                        status_line = line

            if status_line is None:
                logging.error(
                    "ERROR: Could not find the status of any container running in VM %s: %s",
                    worker_ssh.split("@")[0],
                    "".join(output),
                )
                sys.exit()

            parsed = status_line.rstrip().split(" ")

            # If not yet up, wait
            if parsed[1] == "Up":
                deployed = True
            else:
                time.sleep(5)

    return container_names


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
    logging.info("Deploy Docker containers on endpoints with publisher application")

    if config["infrastructure"]["cloud_nodes"] != 1 and config["infrastructure"]["edge_nodes"] != 0:
        logging.error("ERROR: Baremetal currently only works with #clouds==1 and #edges==0")
        sys.exit()

    period_scaler = 100000
    period = int(config["infrastructure"]["cloud_cores"] * period_scaler)
    quota = int(period * config["infrastructure"]["cloud_quota"])

    cont_name = config["cloud_ssh"][0].split("@")[0]

    env_list = []
    for e in app_vars:
        env_list.append("--env")
        env_list.append(e)

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
            cont_name,
            os.path.join(config["registry"], config["images"]["worker"].split(":")[1]),
        ]
    )

    output, error = machines[0].process(config, command)[0]

    logging.debug("Check output of worker container")
    if error and "Your kernel does not support swap limit capabilities" not in error[0]:
        logging.error("".join(error))
        sys.exit()
    elif not output:
        logging.error("No output from docker container")
        sys.exit()

    # Wait for containers to be succesfully deployed
    logging.info("Wait for baremetal worker applications to be deployed")
    time.sleep(10)

    for worker_ssh in config["cloud_ssh"]:
        deployed = False

        while not deployed:
            command = 'docker container ls -a --format "{{.ID}}: {{.Status}} {{.Names}}"'
            output, error = machines[0].process(config, command, shell=True)[0]

            if error:
                logging.error("".join(error))
                sys.exit()
            elif not output:
                logging.error("No output from docker container")
                sys.exit()

            # Get status of docker container
            status_line = None
            for line in output:
                for cont_name in [cont_name]:
                    if cont_name in line:
                        status_line = line

            if status_line is None:
                logging.error(
                    "ERROR: Could not find the status of any container running in VM %s: %s",
                    worker_ssh.split("@")[0],
                    "".join(output),
                )
                sys.exit()

            parsed = status_line.rstrip().split(" ")

            # If not yet up, wait
            if parsed[1] == "Up":
                deployed = True
            else:
                time.sleep(5)

    return [cont_name]


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


def get_worker_output(config, machines, container_names=None):
    """Select the correct function to start the worker application

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
        container_names (list(list(str))): Names of docker containers launched per machine

    Returns:
        list(list(str)): Output of each container ran on the cloud / edge
    """
    # TODO Mist doesn't use kubernetes -> remove from this file, to a mist.py file
    if config["benchmark"]["resource_manager"] in ["mist", "baremetal"]:
        return get_worker_output_mist(config, machines, container_names)

    return get_worker_output_kube(config, machines)


def get_worker_output_kube(config, machines):
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

        # Extra: Log kubernetes system components
        # - These logs are deleted after some time, so better backup them now
        command = "\"sudo su -c 'cd /var/log && grep -ri %s &> output-%s.txt'\"" % (
            container,
            container,
        )
        machines[0].process(config, command, shell=True, ssh=config["cloud_ssh"][0])

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


def get_worker_output_mist(config, machines, container_names):
    """Get the output of worker mist applications

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
        container_names (list(list(str))): Names of docker containers launched per machine

    Returns:
        list(list(str)): Output of each container ran as a worker in the mist
    """
    logging.info("Gather output from subscribers")

    # Alternatively, use docker logs -t container_name for detailed timestamps
    # Exampel: "2021-10-14T08:55:55.912611917Z Start connecting with the MQTT broker"
    commands = [["docker", "logs", "-t", cont_name] for cont_name in container_names]

    ssh_entry = config["edge_ssh"]
    ssh_entry2 = config["edge_ssh"]
    if config["infrastructure"]["provider"] == "baremetal":
        ssh_entry = None
        ssh_entry2 = config["cloud_ssh"]

    results = machines[0].process(config, commands, ssh=ssh_entry)

    worker_output = []
    for container, ssh, (output, error) in zip(container_names, ssh_entry2, results):
        logging.info("Get output from mist worker %s on VM %s", container, ssh)

        if error:
            logging.error("".join(error))
            sys.exit()
        elif not output:
            logging.error("Container %s output empty", container)
            sys.exit()

        output = [line.rstrip() for line in output]
        worker_output.append(output)

    return worker_output
