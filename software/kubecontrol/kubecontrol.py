"""\
Setup Kubernetes on cloud
This resource manager doesn't have any/many help functions, see the /kubernetes folder instead
"""

import logging
import os

import settings
from infrastructure import ansible
from infrastructure import infrastructure
from software.kubernetes import kubernetes


class Module(infrastructure.Infrastructure):
    @staticmethod
    def add_options():
        """Add config options for a particular module

        Returns:
            list(list()): Options to add
        """
        return [
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
        ]

    @staticmethod
    def verify_options(parser, config):
        """Verify the config from the module's requirements

        Args:
            parser (ArgumentParser): Argparse object
            config (ConfigParser): ConfigParser object
        """
        # TODO - only cloud mode is accepted for now
        if (
            config["infrastructure"]["cloud_nodes"] < 2
            or config["infrastructure"]["edge_nodes"] != 0
            or config["infrastructure"]["endpoint_nodes"] < 0
        ):
            parser.error("ERROR: kubecontrol requires #clouds>=2, #edges=0, #endpoints>=0")
        elif (
            config["infrastructure"]["endpoint_nodes"]
            % (config["infrastructure"]["cloud_nodes"] - 1)
            != 0
        ):
            parser.error(
                r"ERROR: Kubernetes requires (#clouds-1) % #endpoints == 0 (-1 for control)"
            )

    @staticmethod
    def get_image_location(package):
        """Get the location of containerized software used in this module. You can choose to ignore
        this and pull it layer by hand. However, Continuum can automatically pull it for you into
        its local registry and make it available in the provisioned infrastructure.

        Returns:
            dict: Images to pull, tagged by deployment location
        """

        # Get specific etcd and pause versions per Kubernetes version
        etcd = None
        pause = None
        if package["version"] == "v1.27.0":
            etcd = "3.5.7-0"
            pause = "3.9"
        elif package["version"] == "v1.26.0":
            etcd = "3.5.6-0"
            pause = "3.9"
        elif package["version"] == "v1.25.0":
            etcd = "3.5.4-0"
            pause = "3.8"
        elif package["version"] == "v1.24.0":
            etcd = "3.5.3-0"
            pause = "3.7"
        elif package["version"] == "v1.23.0":
            etcd = "3.5.1-0"
            pause = "3.6"
        else:
            logging.error(f"Continuum supports Kubernetes v1.[23-27].0, not: {package['version']}")

        return {
            "kubecontrol-proxy": "redplanet00/kube-proxy:" + package["version"],
            "kubecontrol-controller-manager": "redplanet00/kube-controller-manager:"
            + package["version"],
            "kubecontrol-scheduler": "redplanet00/kube-scheduler:" + package["version"],
            "kubecontrol-apiserver": "redplanet00/kube-apiserver:" + package["version"],
            "kubecontrol-etcd": "redplanet00/etcd:" + etcd,
            "kubecontrol-pause": "redplanet00/pause:" + pause,
        }


def start():
    """Setup Kubernetes on cloud VMs using Ansible."""
    logging.info("Start Kubernetes cluster on VMs")

    # Setup cloud controller
    p1 = os.path.join(settings.config["base_path"], ".continuum/inventory_machine")
    p2 = os.path.join(settings.config["base_path"], ".continuum/cloud/control_install.yml")
    c1 = f"ansible-playbook -i {p1} {p2}"
    c1 = c1.split(" ")

    # Setup worker
    p3 = os.path.join(settings.config["base_path"], ".continuum/cloud/install.yml")
    c2 = f"ansible-playbook -i {p1} {p3}"
    c2 = c2.split(" ")

    commands = [c1, c2]
    results = settings.process(commands)

    # Check playbooks
    for command, (output, error) in zip(commands, results):
        logging.debug("Check output for Ansible command [%s]", " ".join(command))
        ansible.check_output((output, error))

    kubernetes.verify_running_cluster()

    # Start measuring resources in Kubernetes and on OS level
    p4 = os.path.join(settings.config["base_path"], ".continuum/cloud/resource_usage.yml")
    c3 = f"ansible-playbook -i {p1} {p4}"

    p5 = os.path.join(settings.config["base_path"], ".continuum/cloud/resource_usage_os.yml")
    c4 = f"ansible-playbook -i {p1} {p5}"

    # Install observability packages (Prometheus, Grafana) if configured by the user
    # TODO - the package itself should be visible in this function, add that
    commands = [c3, c4]
    if package["observability"]:
        p6 = os.path.join(settings.config["base_path"], ".continuum/cloud/observability.yml")
        c5 = f"ansible-playbook -i {p1} {p6}"
        c5 = c5.split(" ")
        commands.append(c5)

    # Execute these commands
    for command in commands:
        command = command.split(" ")
        output, error = settings.process(command)[0]

        logging.debug("Check output for Ansible command [%s]", " ".join(command))
        ansible.check_output((output, error))
