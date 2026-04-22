"""\
Entry file for the benchmark.
Parse the config file, and continue from there on.

Check the documentation and help for more information.
"""

import argparse
import logging
import os
import os.path
import sys
import time

from application import application
from infrastructure import ansible, infrastructure, state as infra_state

# pylint: disable-next=redefined-builtin
from input import input
from input.configuration import config_access, runtime_phase_targets, yaml_parser
from resource_manager import resource_manager


def make_wide(formatter, w=120, h=36):
    """Return a wider HelpFormatter

    Args:
        formatter (HelpFormatter): Format class for Python Argparse
        w (int, optional): Width of Argparse output. Defaults to 120.
        h (int, optional): Max help positions for Argparse output. Defaults to 36.

    Returns:
        formatter: Format class for Python Argparse, possibly with updated output sizes
    """
    try:
        kwargs = {"width": w, "max_help_position": h}
        formatter(None, **kwargs)
        return lambda prog: formatter(prog, **kwargs)
    except TypeError:
        print("Argparse help formatter failed, falling back.")
        return formatter


def set_logging(args):
    """Enable logging to both stdout and file (BENCHMARK_FOLDER/logs)
    If -v/--verbose is used, stdout will report logging.DEBUG, otherwise only logging.INFO
    The file will always use logging.DEBUG (which is the bigger scope)

    Args:
        args (Namespace): Argparse object

    Returns:
        (timestamp): Timestamp of the log file, used for all saved files
    """
    # Log to file parameters
    log_dir = config_access.runtime_logs_dir(args.config)
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    t = time.strftime("%Y-%m-%d_%H:%M:%S", time.gmtime())

    orchestrator_name = "no-orchestrator"
    benchmark_stage_label = "no-application"
    if not config_access.infra_only(args.config):
        orchestrator_name = config_access.orchestrator_name(args.config)
    if config_access.runs_application(args.config):
        try:
            stage_ids = config_access.benchmark_stage_ids(args.config)
            benchmark_stage_label = stage_ids[0] if stage_ids else "benchmark-pipeline"
        except ValueError:
            benchmark_stage_label = "benchmark-pipeline"

    if config_access.infra_only(args.config):
        log_name = "%s_infra_only.log" % (t)
    elif not config_access.runs_application(args.config):
        log_name = "%s_%s_%s.log" % (
            t,
            args.config["mode"],
            orchestrator_name,
        )
    else:
        log_name = "%s_%s_%s_%s.log" % (
            t,
            args.config["mode"],
            orchestrator_name,
            benchmark_stage_label,
        )

    file_handler = logging.FileHandler(os.path.join(log_dir, log_name))
    file_handler.setLevel(logging.DEBUG)

    # Log to stdout parameters
    stdout_handler = logging.StreamHandler(sys.stdout)
    if args.verbose:
        stdout_handler.setLevel(logging.DEBUG)
    else:
        stdout_handler.setLevel(logging.INFO)

    # Set parameters
    logging.basicConfig(
        format="[%(asctime)s %(pathname)s:%(lineno)s - %(funcName)s() ] %(message)s",
        level=logging.DEBUG,
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[file_handler, stdout_handler],
    )

    logging.info("Logging has been enabled. Writing to stdout and file %s/%s", log_dir, log_name)
    return t


def _log_vm_access_hints(config, header="To access the VMs"):
    """Log SSH access hints for the current runtime config when available."""
    ssh_targets = config.get("cloud_ssh", []) + config.get("edge_ssh", []) + config.get(
        "endpoint_ssh", []
    )
    ssh_key = config.get("ssh_key")

    if ssh_targets and ssh_key:
        commands = ["ssh %s -i %s" % (ssh, ssh_key) for ssh in ssh_targets]
        logging.info("%s:\n\t%s\n", header, "\n\t".join(commands))

    if config.get("infrastructure", {}).get("provider") == "qemu":
        logging.info(
            "QEMU fallback inspection hint: use `virsh list --all` to enumerate running VMs "
            "when SSH hints are not yet available in the log."
        )


def main(args):
    """Main control function of the framework

    Args:
        args (Namespace): Argparse object
    """
    try:
        run_infrastructure, run_software, run_application = (
            runtime_phase_targets.resolve_runtime_targets(args.config)
        )
    except ValueError as exc:
        logging.error("%s", exc)
        sys.exit(1)

    machines = []
    if run_infrastructure:
        machines = infrastructure.start(args.config)
        _log_vm_access_hints(args.config, header="VM access hints after infrastructure phase")
        state_path = infra_state.save_state(args.config, "infrastructure", machines)
        logging.info("Saved phase state: %s (phase=infrastructure)", state_path)
    else:
        required_phase = runtime_phase_targets.required_state_phase_for_targets(
            run_infrastructure, run_software, run_application
        )
        try:
            _state_payload, machines = infra_state.load_resume_state(args.config, required_phase)
        except FileNotFoundError:
            logging.error(
                "Cannot skip infrastructure: state file does not exist: %s",
                infra_state.state_file_path(args.config),
            )
            logging.error("Run once with run.targets including 'infrastructure' to create state")
            sys.exit(1)
        except (OSError, ValueError) as exc:
            logging.error("%s", exc)
            sys.exit(1)
        logging.info("Skipping infrastructure phase based on run targets")
        _log_vm_access_hints(args.config, header="VM access hints from resumed state")

    if not machines:
        logging.error("No machines available for software/application phases")
        sys.exit(1)

    runner = ansible.AnsibleRunner(args.config, machines)

    try:
        lock_path = yaml_parser.write_experiment_lock(args.config)
    except ValueError as exc:
        logging.error("Failed to write experiment lock: %s", exc)
        sys.exit(1)
    if lock_path:
        logging.info("Wrote resolved experiment lock to %s", lock_path)

    if run_software:
        resource_manager.start(runner)
        state_path = infra_state.save_state(args.config, "software", machines)
        logging.info("Saved phase state: %s (phase=software)", state_path)
    else:
        logging.info("Skipping software phase based on run targets")

    if run_application and args.config["module"]["application"]:
        application.start(runner)
        state_path = infra_state.save_state(args.config, "application", machines)
        logging.info("Saved phase state: %s (phase=application)", state_path)
    elif run_application:
        logging.info("Application phase requested but no application module is configured")

    if args.config["infrastructure"]["delete"]:
        infrastructure.delete_vms(args.config, machines)
        logging.info("Finished\n")
    else:
        _log_vm_access_hints(args.config)

        if config_access.has_addon(args.config, "observability"):
            logging.info(
                "To access Grafana: ssh -L 3000:%s:3000 %s -i %s",
                args.config["cloud_ips"][0],
                args.config["cloud_ssh"][0],
                args.config["ssh_key"],
            )
            logging.info(
                "To access Prometheus: ssh -L 9090:%s:9090 %s -i %s",
                args.config["cloud_ips"][0],
                args.config["cloud_ssh"][0],
                args.config["ssh_key"],
            )


if __name__ == "__main__":
    # Get input arguments, and validate those arguments
    parser_obj = argparse.ArgumentParser(
        formatter_class=make_wide(argparse.HelpFormatter, w=120, h=500)
    )

    parser_obj.add_argument(
        "config", type=lambda x: input.start(parser_obj, x), help="benchmark config file"
    )
    parser_obj.add_argument("-v", "--verbose", action="store_true", help="increase verbosity level")

    arguments = parser_obj.parse_args()

    timestamp = set_logging(arguments)
    arguments.config["timestamp"] = timestamp

    input.print_input(arguments.config)

    main(arguments)
