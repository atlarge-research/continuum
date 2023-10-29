"""\
Setup Kubernetes on cloud
This resource manager doesn't have any/many help functions, see the /kubernetes folder instead
"""

import logging
import os

from infrastructure import ansible
from resource_manager.kubernetes import kubernetes


def add_options(_config):
    """Add config options for a particular module

    Args:
        config (ConfigParser): ConfigParser object

    Returns:
        list(list()): Options to add
    """
    settings = [
        ["cache_worker", bool, lambda x: x in [True, False], False, False],
        [
            "kube_deployment",
            str,
            lambda x: x in ["pod", "container", "file", "call"],
            False,
            "pod",
        ],
        [
            "kube_version",
            str,
            lambda _: ["v1.27.0", "v1.26.0", "v1.25.0", "v1.24.0", "v1.23.0"],
            False,
            "v1.27.0",
        ],
        [
            "runtime",
            str,
            lambda x: x in ['runc', 'kata-qemu', 'kata-fc'],
            False,
            'runc'
        ],
        [
            "runtime_filesystem",
            str,
            lambda x: x in ['overlayfs', 'devmapper'],
            False,
            'devmapper'
        ],
    ]
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
        or config["infrastructure"]["endpoint_nodes"] < 0
    ):
        parser.error("ERROR: kubecontrol requires #clouds>=2, #edges=0, #endpoints>=0")
    elif (
        config["infrastructure"]["endpoint_nodes"] % (config["infrastructure"]["cloud_nodes"] - 1)
        != 0
    ):
        parser.error(r"ERROR: Kubernetes requires (#clouds-1) % #endpoints == 0 (-1 for control)")
    elif (
        config["benchmark"]["runtime"] == "kata-fc" and config["benchmark"]["runtime_filesystem"] == "overlayfs"
    ):
        parser.error(f"ERROR: Overlay FS cannot be used with kata-fc - use option runtime_filesystem = devmapper")


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

    # Setup worker
    commands.append(
        [
            "ansible-playbook",
            "-i",
            os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_vms"),
            os.path.join(
                config["infrastructure"]["base_path"],
                ".continuum/%s/install.yml" % (config["mode"]),
            ),
        ]
    )

    # Setup worker runtime
    runtime = config['benchmark']['runtime']
    if "kata" in runtime:
        commands.append(
            [
                "ansible-playbook",
                "-i",
                os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_vms"),
                os.path.join(
                    config["infrastructure"]["base_path"],
                    f".continuum/{(config['mode'])}/install_kata_containers.yml",
                ),
            ]
        )
        commands.append(
            [
                "ansible-playbook",
                "-i",
                os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_vms"),
                os.path.join(
                    config["infrastructure"]["base_path"],
                    ".continuum/%s/install_kata_cloud_common.yml" % (config["mode"]),
                ),
            ]
        )
        commands.append(
            [
                "ansible-playbook",
                "-i",
                os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_vms"),
                os.path.join(
                    config["infrastructure"]["base_path"],
                    ".continuum/cloud/install_kata_dev_tools.yml",
                ),
            ]
        )
        if config["benchmark"].get("runtime_filesystem") == "overlayfs":
            assert runtime == "kata-qemu"
            commands.append(
                [
                    "ansible-playbook",
                    "-i",
                    os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_vms"),
                    os.path.join(
                        config["infrastructure"]["base_path"],
                        ".continuum/cloud/install_kata_qemu_overlayfs.yml",
                    ),
                ]
            )


    results = machines[0].process(config, commands)

    # Check playbooks
    for command, (output, error) in zip(commands, results):
        logging.debug("Check output for Ansible command [%s]", " ".join(command))
        ansible.check_output((output, error))

    kubernetes.verify_running_cluster(config, machines)

    # Start the resource metrics server
    command = [
        "ansible-playbook",
        "-i",
        os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_vms"),
        os.path.join(
            config["infrastructure"]["base_path"],
            ".continuum/cloud/resource_usage.yml",
        ),
    ]

    output, error = machines[0].process(config, command)[0]

    logging.debug("Check output for Ansible command [%s]", " ".join(command))
    ansible.check_output((output, error))

    # Now the OS server that runs on every VM
    command = [
        "ansible-playbook",
        "-i",
        os.path.join(config["infrastructure"]["base_path"], ".continuum/inventory_vms"),
        os.path.join(
            config["infrastructure"]["base_path"],
            ".continuum/cloud/resource_usage_os.yml",
        ),
    ]

    output, error = machines[0].process(config, command)[0]

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
