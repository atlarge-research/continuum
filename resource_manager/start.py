"""\
Select the correct resource manager, install required software and set them up.
"""

import logging
import sys


def docker_worker_registry(machines):
    """Upload the application docker image, already stored in the cloud/edge, to the local
    registries running inside each worker VM.

    Args:
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Push application images into registries on worker machines")
    for machine in machines:
        print("machine")
        print(machine.cloud_names + machine.edge_names)
        print(machine.cloud_ips + machine.edge_ips)
        for name, ip in zip(machine.cloud_names + machine.edge_names, machine.cloud_ips + machine.edge_ips):
            # Get the name of the image we want to push to the registry
            output, error = machines[0].process(
                ["docker", "images"],
                ssh=True,
                ssh_target=name + "@" + ip,
            )

            if output == [] or len(output) <= 2:
                logging.error("No Docker images in the machines - shouldn't be the case")
            elif error != []:
                logging.error("".join(error))
                sys.exit()

            image = output[2].split(' ')[0]

            # Now push the image to the registry
            dest = "localhost:%i/%s" % (5000, image.split("/")[1])
            commands = [
                ["docker", "tag", image, dest],
                ["docker", "push", dest],
                ["docker", "image", "remove", image],
                ["docker", "image", "remove", dest],
            ]

            for command in commands:
                output, error = machines[0].process(
                    command,
                    ssh=True,
                    ssh_target=name + "@" + ip,
                )

                if error != []:
                    logging.error("".join(error))
                    sys.exit()


def start(config, machines):
    """Create and manage resource managers

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    from .endpoint import start as endpoint

    if "resource_manager" in config["benchmark"]:
        if config["benchmark"]["resource_manager"] in ["kubeedge", "mist"]:
            from .kubeedge import start
        elif config["benchmark"]["resource_manager"] == "kubernetes":
            from .kubernetes import start

    # Install RM software on cloud/edge nodes
    if config["mode"] == "cloud" or config["mode"] == "edge":
        start.start(config, machines)
        docker_worker_registry(machines)

    if config["infrastructure"]["endpoint_nodes"]:
        # Start RM software on endpoints
        endpoint.start(config, machines)
