"""\
Setup Kubernetes on cloud
"""

import logging
import sys
import time
from input.configuration import config_access
from resource_manager import orchestrator_options, plans


_NONZERO_RETURN_CODE_PREFIX = "Command exited with non-zero return code "
_KUBECTL_FAILURE_TEXT = (
    "timed out waiting for the condition",
    "error:",
    "error from server:",
    "etcdserver: request timed out",
    "unable to connect to the server",
    "the connection to the server",
    "context deadline exceeded",
    "i/o timeout",
    "connection refused",
    "permission denied",
)


def add_options(_config):
    """[INTERFACE] Add config options for this RM module

    Args:
        config (ConfigParser): ConfigParser object

    Returns:
        list(list()): Options to add
    """
    return (
        orchestrator_options.kubernetes_common_options(
            orchestrator_options.KUBE_VERSIONS_CURRENT
        )
        + orchestrator_options.kube_deployment_options()
    )


def verify_options(parser, config):
    """[INTERFACE] Verify config options for this RM module

    Args:
        parser (ArgumentParser): Argparse object
        config (ConfigParser): ConfigParser object
    """
    if (
        config["infrastructure"]["cloud_nodes"] < 1
        or config["infrastructure"]["edge_nodes"] != 0
        or config["infrastructure"]["endpoint_nodes"] < 0
    ):
        parser.error("ERROR: Kubernetes requires #clouds>=1, #edges=0, #endpoints>=0")
    elif config["infrastructure"]["cloud_nodes"] > 1 and (
        config["infrastructure"]["endpoint_nodes"] % (config["infrastructure"]["cloud_nodes"] - 1)
        != 0
    ):
        parser.error(r"ERROR: Kubernetes requires (#clouds-1) % #endpoints == 0 (-1 for control)")


def start(runner):
    """[INTERFACE] Execute Kubernetes software-phase installation.

    Args:
        runner (AnsibleRunner): Shared Ansible runner with config and machine state.
    """
    from resource_manager import resource_manager

    resource_manager.start(runner)


def base_install_playbook(_config, tier):
    """[INTERFACE] Return Kubernetes base-install playbook for a tier.

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
    """[INTERFACE] Build software-phase plan entries for Kubernetes RM.

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
            legacy_target_groups=("cloudcontroller", "clouds", "edges"),
        )
    ]
    if observability_owner is not None:
        entries.append(
            plans.PlanEntry(
                kind="playbook",
                playbook="playbooks/resource_manager/k8s_observability.yml",
                owner_id=observability_owner["id"],
                owner_type=observability_owner["type"],
                legacy_target_groups=("cloudcontroller",),
            )
        )
    return entries


def post_phase_hook(runner):
    """[INTERFACE] Run post-install verification for Kubernetes RM.

    Args:
        runner (AnsibleRunner): Shared runner instance.
    """
    verify_running_cluster(runner.config, runner.machines)


def _stderr_has_real_error(err_lines):
    """Return whether kubectl stderr contains anything except controlled trace output.

    Args:
        err_lines (list(str)): List of error lines

    Returns:
        bool: True if the stderr contains a real error, False otherwise
    """
    for line in err_lines or []:
        stripped = line.strip()
        if not stripped:
            continue

        lowered = stripped.lower()
        if _NONZERO_RETURN_CODE_PREFIX in stripped or any(
            failure_text in lowered for failure_text in _KUBECTL_FAILURE_TEXT
        ):
            return True

        if stripped.startswith("[CONTINUUM]"):
            continue

        return True

    return False


def _stdout_has_readiness(out_lines):
    """Return whether kubectl emitted a positive readiness result."""
    return any("condition met" in line.lower() for line in out_lines or [])


def verify_running_cluster(config, machines):
    """Verify that all nodes in the cluster have status Ready
    If not, either wait until they are ready or stop the framework

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.info("Verify if all nodes in the cluster are connected")

    max_retries = 5
    sleep_time = 5

    cmd_wait = ["kubectl", "wait", "--for=condition=Ready", "node", "--all", "--timeout=10m"]

    for attempt in range(max_retries):
        out, err = machines[0].process(config, cmd_wait, ssh=config["cloud_ssh"][0])[0]
        if _stdout_has_readiness(out) and not _stderr_has_real_error(err):
            logging.info("All nodes are Ready")
            return

        # Treat as transient unless it's the last attempt
        msg = ("".join(err) or "".join(out) or "").strip()
        logging.warning("kubectl wait failed (attempt %d/%d): %s", attempt, max_retries, msg)

        if attempt < max_retries:
            time.sleep(sleep_time)

    logging.error("Cluster did not become Ready after %d attempts", max_retries)
    sys.exit(1)
