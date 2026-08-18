"""Runtime target resolution helpers."""

from input.configuration import config_access

_UNSUPPORTED_RESUME_PROVIDERS = {"aws", "gcp"}


def fresh_application_without_software(targets):
    """Return whether fresh infrastructure would run an application without software."""
    target_set = set(targets)
    return (
        "infrastructure" in target_set
        and "application" in target_set
        and "software" not in target_set
    )


def provider_resume_error(provider_name, targets):
    """Return an error when a provider lacks a certified retained-registry resume path."""
    target_set = set(targets)
    if "infrastructure" in target_set or provider_name not in _UNSUPPORTED_RESUME_PROVIDERS:
        return None
    return (
        "Provider '%s' does not support run.targets that skip infrastructure: "
        "its retained registry lifecycle is not certified; run infrastructure in the same "
        "execution"
        % (provider_name,)
    )


def resolve_runtime_targets(config):
    """Resolve requested runtime phases from config."""
    targets = config_access.run_targets(config)
    if fresh_application_without_software(targets):
        raise ValueError(
            "Invalid run target combination in domains.run.targets: "
            "fresh application execution requires the software phase when infrastructure "
            "is selected"
        )

    provider_name = config.get("infrastructure", {}).get("provider")
    resume_error = provider_resume_error(provider_name, targets)
    if resume_error is not None:
        raise ValueError(resume_error)

    target_set = set(targets)
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
