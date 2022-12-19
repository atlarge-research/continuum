"""Create infrastructure by applying a Terraform configuration"""

import sys
import logging


def start(config, machines):
    """Create and launch QEMU cloud and edge VMs

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Start VM creation using QEMU")

    # Delete old terraform setups (only if old config is still around)
    logging.info("Destroy the old Terraform configuration if the configs are still present")
    command = ["terraform", "destroy", "--auto-approve"]
    output, error = machines[0].process(config, command)[0]

    if error:
        logging.warning("Could not destroy old configuration: %s", "".join(error))
    elif not any("Destroy complete!" in out for out in output):
        logging.warning("Could not destroy the old Terraform configuration: %s", "".join(output))

    # Init, format, and validate
    commands = [["terraform", "init"], ["terraform", "fmt"], ["terraform", "validate"]]

    results = machines[0].process(config, commands)
    for command, (output, error) in zip(commands, results):
        logging.debug("Check output for command [%s]", command)

        if error:
            logging.error("ERROR: %s", "".join(error))
            sys.exit()
        elif "init" in command and not any(
            "Terraform has been successfully initialized!" in out for out in output
        ):
            logging.error("ERROR on init: %s", "".join(output))
            sys.exit()
        elif "validate" in command and not any(
            "Success! The configuration is valid." in out for out in output
        ):
            logging.error("ERROR on validate: %s", "".join(output))
            sys.exit()

    # Finally, apply the configuration
    command = ["terraform", "apply", "--auto-validate"]
    output, error = machines[0].process(config, command)[0]

    if error:
        logging.error("Could not apply Terraform configuration: %s", "".join(error))
        sys.exit()
    elif not any("Apply complete!" in out for out in output):
        logging.warning("Could not apply Terraform configuration:: %s", "".join(output))

    # TODO: Possibly insert a small time.sleep here? You never know.
