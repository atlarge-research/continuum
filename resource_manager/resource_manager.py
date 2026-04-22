"""Select the correct resource manager, install required software and set them up."""

from . import plans


def start(runner):
    """[INTERFACE] Create and manage resource managers

    Args:
        runner (AnsibleRunner): Shared Ansible runner with config and machine state.
    """
    config = runner.config

    # Install orchestrator/addons through centralized software planning.
    entries = plans.build_software_phase_entries(config)
    plans.execute_entries(runner, entries)
    plans.run_post_phase_hook(runner)


def add_options(config):
    """[INTERFACE] Add config options for a particular module

    Args:
        config (ConfigParser): ConfigParser object

    Returns:
        object: Option descriptors from the selected resource manager module.
    """
    return config["module"]["resource_manager"].add_options(config)


def verify_options(parser, config):
    """[INTERFACE] Verify the config from the module's requirements

    Args:
        parser (ArgumentParser): Argparse object
        config (ConfigParser): ConfigParser object
    """
    config["module"]["resource_manager"].verify_options(parser, config)
