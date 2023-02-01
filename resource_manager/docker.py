"""\
Manage deployments and output of Docker containers, to be shared by many applications
"""

import logging
import sys


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
