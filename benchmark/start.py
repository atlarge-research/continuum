"""\
Execute the benchmark and get raw output
"""

import logging
import sys
import time
import os

# pylint: disable=wrong-import-position

sys.path.append(os.path.abspath(".."))
import main

# pylint: enable=wrong-import-position

from . import output as out


def cache_worker(config, machines):
    """Start Kube applications for caching, so the real app doesn't need to load images

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
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

    # Application-specific variables
    if config["benchmark"]["application"] == "image_classification":
        app_vars = {
            "container_port": 1883,
            "mqtt_logs": True,
            "endpoint_connected": int(config["infrastructure"]["endpoint_nodes"] / worker_apps),
            "cpu_threads": max(1, int(config["benchmark"]["application_worker_cpu"])),
        }
    elif config["benchmark"]["application"] == "empty":
        app_vars = {
            "sleep_time": 30,
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

    main.ansible_check_output(machines[0].process(config, command, shell=True)[0])

    # This only creates the file we need, now launch the benchmark
    command = (
        "kubectl apply --kubeconfig=/home/cloud_controller/.kube/config "
        + "-f /home/cloud_controller/job-template.yaml"
    )
    output, error = machines[0].process(config, command, shell=True, ssh=config["cloud_ssh"][0])[0]

    if not output or "job.batch/empty created" not in output[0]:
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
        logging.error('Output does not container job.batch "empty" deleted: %s', "".join(output))
        sys.exit()
    elif error and not all("[CONTINUUM]" in l for l in error):
        logging.error("".join(error))

    time.sleep(10)


def start_worker(config, machines):
    """Start the MQTT subscriber application on cloud / edge workers.
    Submit the job request to the cloud controller, which automatically starts it on the cluster.
    Every cloud / edge worker will only have 1 application running taking up all resources.
    Multiple subscribers per node won't work, they all read the same messages from the MQTT bus.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines

    Returns:
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
    elif config["benchmark"]["application"] == "empty":
        app_vars = {
            "sleep_time": config["benchmark"]["sleep_time"],
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

    main.ansible_check_output(machines[0].process(config, command, shell=True)[0])

    starttime = 0.0
    if config["benchmark"]["application"] == "empty":
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

    return starttime


def start_worker_mist(config, machines):
    """Start running the mist worker subscriber containers using Docker.
    Wait for them to finish, and get their output.
    Every edge worker will only have 1 application running taking up all resources.
    Multiple subscribers per node won't work, they all read the same messages from the MQTT bus.

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

    for worker_ssh in config["edge_ssh"]:
        cont_name = worker_ssh.split("@")[0]
        worker_ip = worker_ssh.split("@")[1]

        # Set variables for the application
        env = [
            "MQTT_LOCAL_IP=%s" % (worker_ip),
            "MQTT_LOGS=True",
            "CPU_THREADS=%i" % (config["infrastructure"]["edge_cores"]),
            "ENDPOINT_CONNECTED=%i"
            % (
                int(
                    config["infrastructure"]["endpoint_nodes"]
                    / config["infrastructure"]["edge_nodes"]
                )
            ),
        ]

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
    logging.info("Wait for Mist appilcations to be deployed")
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
        if config["benchmark"]["resource_manager"] != "mist":
            workers -= 1

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
            env = ["FREQUENCY=%i" % (config["benchmark"]["frequency"])]

            if config["mode"] == "cloud" or config["mode"] == "edge":
                cont_name = "%s%i_" % (config["mode"], worker_i) + cont_name
                env.append("MQTT_LOCAL_IP=%s" % (endpoint_ssh.split("@")[1]))
                env.append("MQTT_REMOTE_IP=%s" % (worker_ip))
                env.append("MQTT_LOGS=True")
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
            output, error = machines[0].process(config, command, shell=True, ssh=ssh)[0]

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
        workers -= 1

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


def start(config, machines):
    """Run the benchmark

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines

    Returns:
        list(str): Raw output from the benchmark
    """
    starttime = 0.0
    if config["mode"] == "cloud" or config["mode"] == "edge":
        if config["benchmark"]["resource_manager"] != "mist":
            if config["benchmark"]["cache_worker"]:
                cache_worker(config, machines)

            if config["infrastructure"]["provider"] == "baremetal":
                starttime = start_worker_baremetal(config, machines)
            else:
                starttime = start_worker(config, machines)
        else:
            container_names_mist = start_worker_mist(config, machines)

    container_names = []
    if config["infrastructure"]["endpoint_nodes"]:
        if config["infrastructure"]["provider"] == "baremetal":
            container_names = start_endpoint_baremetal(config, machines)
            wait_endpoint_completion_baremetal(
                config, machines, config["endpoint_ssh"], container_names
            )
        else:
            container_names = start_endpoint(config, machines)
            wait_endpoint_completion(config, machines, config["endpoint_ssh"], container_names)

    # Wait for benchmark to finish
    if config["mode"] == "cloud" or config["mode"] == "edge":
        if config["infrastructure"]["provider"] == "baremetal":
            wait_worker_completion_baremetal(config, machines)
        else:
            if config["benchmark"]["resource_manager"] != "mist":
                wait_worker_completion(config, machines)
            else:
                wait_endpoint_completion(config, machines, config["edge_ssh"], container_names_mist)

    # Now get raw output
    endpoint_output = []
    if config["infrastructure"]["endpoint_nodes"]:
        # TODO: Even this is specific right? Use endpoints or not? Or leave as general?
        logging.info("Benchmark has been finished, prepare results")
        endpoint_output = out.get_endpoint_output(config, machines, container_names)

    worker_output = []
    if config["mode"] == "cloud" or config["mode"] == "edge":
        if config["benchmark"]["resource_manager"] != "mist":
            worker_output = out.get_worker_output(config, machines)
        else:
            worker_output = out.get_worker_output_mist(config, machines, container_names_mist)

    # Parse output into dicts, and print result
    worker_metrics, endpoint_metrics = out.gather_metrics(
        machines, config, worker_output, endpoint_output, container_names, starttime
    )
    out.format_output(config, worker_metrics, endpoint_metrics)


"""
TODO

Create functions to support bare-metal deployment, which uses docker on bare-metal
- Create new functions if too many code changes are required
    - Example: 
        - Launch cloud/edge app, as we no longer use Kubernetes
        - Get output from cloud/edge app, as we no longer have Kubernetes
            - Mimic the endpoint function instead, that one uses Docker
- Add if/else if only little changes are required
    - Endpoint deployment, but just without the ssh (just execute natively)

Files that need to be changed
- start.py (this file)
- output.py
- config files in /experiment_provider
- replicate_paper.py


Instructions for starting/stopping/installing mosquitto on bare-metal (only requirement)
- sudo apt install mosquitto=1.6.9-1
- mosquitto -d -p 1883
- sudo systemctl start mosquitto.service
- sudo systemctl stop mosquitto.service
"""
