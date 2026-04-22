"""Runtime target resolution helpers."""

from input.configuration import config_access


def resolve_runtime_targets(config):
    """Resolve requested runtime phases from config."""
    target_set = set(config_access.run_targets(config))
    run_infrastructure = "infrastructure" in target_set
    run_software = "software" in target_set
    run_application = "application" in target_set
    return run_infrastructure, run_software, run_application


def required_state_phase_for_targets(run_infrastructure, run_software, run_application):
    """Return minimum completed phase required when skipping infrastructure."""
    if run_infrastructure:
        return None
    if run_software:
        return "infrastructure"
    if run_application:
        return "software"
    return None
