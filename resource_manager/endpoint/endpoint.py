"""\
Setup endpoints
"""

import logging
import os
import sys
import time

from infrastructure import ansible


def start(config, machines):
    """Setup endpoint VMs using Ansible.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Start setting up endpoint VMs")

    command = [
        "ansible-playbook",
        "-i",
        os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_vms"),
        os.path.join(config["infrastructure"]["base_path"], ".continuum/endpoint/install.yml"),
    ]
    ansible.check_output(machines[0].process(config, command)[0])


def start_endpoint(config, machines):
    """Select the correct function to start the worker application

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines

    Returns:
        list(list(str)): Names of docker containers launched per machine
    """
    if config["benchmark"]["resource_manager"] == "baremetal":
        return start_endpoint_baremetal(config, machines)

    return start_endpoint_default(config, machines)


def start_endpoint_default(config, machines):
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
        controllers = sum(m.cloud_controller for m in machines)
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


def start_endpoint_baremetal(config, machines):
    """Start running the endpoint containers using Docker.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines

    Returns:
        list(list(str)): Names of docker containers launched per machine
    """
    logging.info("Deploy Docker containers on endpoints with publisher application as baremetal")

    commands = []
    container_names = []

    period_scaler = 100000
    period = int(config["infrastructure"]["endpoint_cores"] * period_scaler)
    quota = int(period * config["infrastructure"]["endpoint_quota"])

    worker_ip = config["registry"].split(":")[0]

    for endpoint_i, _ in enumerate(config["endpoint_ssh"]):
        # Docker container name and variables depends on deployment mode
        cont_name = "endpoint%i" % (endpoint_i)
        cont_name = "%s0_" % (config["mode"]) + cont_name

        env = ["FREQUENCY=%i" % (config["benchmark"]["frequency"])]
        env.append("MQTT_LOCAL_IP=%s" % (worker_ip))
        env.append("MQTT_REMOTE_IP=%s" % (worker_ip))
        env.append("MQTT_LOGS=True")

        env_list = []
        for e in env:
            env_list.append("--env")
            env_list.append(e)

        logging.info("Launch %s", cont_name)

        # Decide wether to use the endpoint or combined image
        command = (
            [
                "docker",
                "container",
                "run",
                "--detach",
                "--memory=%ig" % (config["infrastructure"]["endpoint_memory"]),
                "--cpu-period=%i" % (period),
                "--cpu-quota=%i" % (quota),
                "--network=host",
            ]
            + env_list
            + [
                "--name",
                cont_name,
                os.path.join(
                    config["registry"],
                    config["images"]["endpoint"].split(":")[1],
                ),
            ]
        )

        commands.append(command)
        container_names.append(cont_name)

    results = machines[0].process(config, commands)

    # Checkout process output
    for output, error in results:
        logging.debug("Check output of endpoint baremetal")

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


def get_endpoint_output(config, machines, container_names, use_ssh=True):
    """Get the output of endpoint docker containers.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
        container_names (list(list(str))): Names of docker containers launched

    Returns:
        list(list(str)): Output of each endpoint container
    """
    logging.info("Extract output from endpoint publishers")

    # Alternatively, use docker logs -t container_name for detailed timestamps
    # Exampel: "2021-10-14T08:55:55.912611917Z Start connecting with the MQTT broker"
    commands = [["docker", "logs", "-t", cont_name] for cont_name in container_names]

    ssh_entry = None
    if use_ssh:
        ssh_entry = config["endpoint_ssh"]

    if config["infrastructure"]["provider"] == "baremetal":
        ssh_entry = None

    results = machines[0].process(config, commands, ssh=ssh_entry)

    endpoint_output = []
    for container, ssh, (output, error) in zip(container_names, config["endpoint_ssh"], results):
        logging.info("Get output from endpoint %s on VM %s", container, ssh)

        if error:
            logging.error("".join(error))
            sys.exit()
        elif not output:
            logging.error("Container %s output empty", container)
            sys.exit()

        output = [line.rstrip() for line in output]
        endpoint_output.append(output)

    return endpoint_output
