"""\
Setup Kubernetes on cloud
This resource manager doesn't have any/many help functions, see the /kubernetes folder instead
"""

from input.configuration import config_access
from resource_manager import orchestrator_options, plans
from resource_manager.kubernetes import kubernetes


def add_options(_config):
    """[INTERFACE] Add config options for this RM module

    Args:
        config (ConfigParser): ConfigParser object

    Returns:
        list(list()): Options to add
    """
    return (
        orchestrator_options.kubernetes_common_options(orchestrator_options.KUBE_VERSIONS_COMPAT)
        + orchestrator_options.kube_deployment_options()
    )


def verify_options(parser, config):
    """[INTERFACE] Verify config options for this RM module

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


def start(runner):
    """[INTERFACE] Execute kubecontrol software-phase installation.

    Args:
        runner (AnsibleRunner): Shared Ansible runner with config and machine state.
    """
    from resource_manager import resource_manager

    resource_manager.start(runner)


def base_install_playbook(_config, tier):
    """[INTERFACE] Return kubecontrol base-install playbook for a tier.

    Args:
        _config (dict): Parsed configuration (unused).
        tier (str): VM tier selector.

    Returns:
        str | None: K8s base-install playbook for cloud/edge tiers, else None.
    """
    if tier in ("cloud", "edge"):
        return "playbooks/resource_manager/k8s_base_install.yml"
    return None


def build_phase_plan(config):
    """[INTERFACE] Build software-phase plan entries for kubecontrol RM.

    Args:
        config (dict): Parsed configuration.

    Returns:
        list[PlanEntry]: Ordered software-phase execution entries.
    """
    observability_owner = None
    if config_access.has_addon(config, "observability"):
        observability_owner = config_access.software_module_by_type(config, "observability")

    entries = [
        plans.PlanEntry(
            kind="playbook",
            playbook="playbooks/resource_manager/k8s_cluster.yml",
            extra_vars={"ignore_preflight_errors": True},
        ),
        plans.PlanEntry(kind="playbook", playbook="playbooks/resource_manager/k8s_metrics.yml"),
    ]
    if observability_owner is not None:
        entries.append(
            plans.PlanEntry(
                kind="playbook",
                playbook="playbooks/resource_manager/k8s_observability.yml",
                owner_id=observability_owner["id"],
                owner_type=observability_owner["type"],
            )
        )
    return entries


def post_phase_hook(runner):
    """[INTERFACE] Run post-install verification for kubecontrol RM.

    Args:
        runner (AnsibleRunner): Shared runner instance.
    """
    kubernetes.verify_running_cluster(runner.config, runner.machines)
