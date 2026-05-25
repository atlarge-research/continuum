"""\
Setup KubeEdge on cloud/edge
This resource manager doesn't have any/many help functions, see the /kubernetes folder instead
"""

from input.configuration import config_access
from resource_manager import orchestrator_options, plans


def add_options(config):
    """[INTERFACE] Add config options for this RM module

    Args:
        config (ConfigParser): ConfigParser object

    Returns:
        list(list()): Options to add
    """
    # Mist doesn't have cache worker, only KubeEdge
    if config_access.orchestrator_name(config) != "kubeedge":
        return None

    return orchestrator_options.kubernetes_common_options(
        orchestrator_options.KUBE_VERSIONS_CURRENT
    )


def verify_options(parser, config):
    """[INTERFACE] Verify config options for this RM module

    Args:
        parser (ArgumentParser): Argparse object
        config (ConfigParser): ConfigParser object
    """
    # Future cleanup: split KubeEdge and Mist into separate resource-manager modules.
    if config_access.orchestrator_name(config) == "kubeedge" and (
        config["infrastructure"]["cloud_nodes"] != 1
        or config["infrastructure"]["edge_nodes"] == 0
        or config["infrastructure"]["endpoint_nodes"] < 0
    ):
        parser.error("ERROR: KubeEdge requires #clouds=1, #edges>=1, #endpoints>=0")
    elif config_access.orchestrator_name(config) == "mist" and (
        config["infrastructure"]["cloud_nodes"] != 0
        or config["infrastructure"]["edge_nodes"] == 0
        or config["infrastructure"]["endpoint_nodes"] == 0
    ):
        # Mist, shares KubeEdge code for now
        parser.error("ERROR: Mist requires #clouds==0, #edges>=1, #endpoints>=1")

    if config["infrastructure"]["endpoint_nodes"] % config["infrastructure"]["edge_nodes"] != 0:
        parser.error("ERROR: KubeEdge requires #edges %% #endpoints == 0")


def start(runner):
    """[INTERFACE] Execute kubeedge/mist software-phase installation.

    Args:
        runner (AnsibleRunner): Shared Ansible runner with config and machine state.
    """
    from resource_manager import resource_manager

    resource_manager.start(runner)


def base_install_playbook(config, tier):
    """[INTERFACE] Return kubeedge/mist base-install playbook for a tier.

    Args:
        config (dict): Parsed configuration.
        tier (str): VM tier selector.

    Returns:
        str | None: KubeEdge base-install playbook for cloud/edge tiers, else None.
    """
    if tier not in ("cloud", "edge"):
        return None

    if config_access.orchestrator_name(config) in ("kubeedge", "mist"):
        return "playbooks/resource_manager/kubeedge_base_install.yml"

    return None


def build_phase_plan(config):
    """[INTERFACE] Build software-phase plan entries for kubeedge/mist RM.

    Args:
        config (dict): Parsed configuration.

    Returns:
        list[PlanEntry]: Ordered software-phase execution entries.
    """
    if config_access.orchestrator_name(config) == "mist":
        return [
            plans.PlanEntry(kind="playbook", playbook="playbooks/resource_manager/mist_install.yml")
        ]

    return [
        plans.PlanEntry(kind="playbook", playbook="playbooks/resource_manager/kubeedge_cluster.yml")
    ]
