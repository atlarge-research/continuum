import logging
import os
import subprocess
import sys
from typing import List
from infrastructure.machine import Machine
import main

def run_playbook(command : List[str], machine : Machine):
    """Run an Ansible command on a machine and check output.

    Args:
        command (List[str]): command for Ansible
        machines (Machine): physical machine to run Ansible command on
    """
    process = machine.process(command, output=False)

    logging.debug("Check output for Ansible command [%s]" % (" ".join(process.args)))
    output = [line.decode("utf-8") for line in process.stdout.readlines()]
    error = [line.decode("utf-8") for line in process.stderr.readlines()]

    main.ansible_check_output((output, error))

def install_openfaas(config : dict, machines : Machine):
    """Install OpenFaaS by executing the playbook.

    Args:
        home_path (dict): parsed configuration of continuum
        machines (Machine): pysical machine to run Ansible command on
    """
    if config["benchmark"]["resource_manager"] != "kubernetes":
        logging.error(f"FAILED! OpenFaaS only runs with Kubernetes, but {config['benchmark']['resource_manager']} was installed")
        sys.exit()

    logging.info("Installing OpenFaaS")

    command = [
        "ansible-playbook",
        "-i",
        os.path.join(config["home"], ".continuum/inventory_vms"),
        os.path.join(config["home"], ".continuum/execution_model/openFaas.yml"),
    ]

    run_playbook(command, machines[0])  # we assume that cloud_controller is on first machine (localhost)

def start(config : dict, machines : List[Machine]):
    """Install execution model.
    Method selects a handler for every execution model there is.

    Args:
        config (dict): Parsed Configuration
        machines (List[Machine]): all physical machines available
    """
    if "execution_model" not in config:
        logging.error("FAILED! Key execution_model is missing in config, but it was tried to install an execution model anyway")
        sys.exit()

    model = config["execution_model"]["model"]
    if model == "openFaas":
        install_openfaas(config, machines)