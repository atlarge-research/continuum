"""\
Manage applicaiton logic in the framework
Mostly used for calling specific application code
"""

import logging
import os
import sys
from datetime import datetime

from application import runtime_helpers as application_runtime_helpers
from input.configuration import config_access, image_requirements
from resource_manager import legacy_execution
from resource_manager.endpoint import endpoint
from resource_manager.kube_kata import kube_kata


def set_container_location(config):
    """[INTERFACE] Set registry location/path of containerized applications

    Args:
        config (dict): Parsed configuration
    """
    config["module"]["application"].set_container_location(config)


def add_options(config):
    """[INTERFACE] Add config options for a particular module

    Args:
        config (ConfigParser): ConfigParser object

    Returns:
        object: Options from application module.
    """
    return config["module"]["application"].add_options(config)


def verify_options(parser, config):
    """[INTERFACE] Verify the config from the module's requirements

    Args:
        parser (ArgumentParser): Argparse object
        config (ConfigParser): ConfigParser object
    """
    config["module"]["application"].verify_options(parser, config)


def start(runner):
    """[INTERFACE] Start the application with a certain deployment model

    Args:
        runner (AnsibleRunner): Shared Ansible runner with config and machine state.
    """
    config = runner.config
    machines = runner.machines
    if not config["module"]["application"]:
        logging.error(
            "ERROR: Benchmark stage %s does not define an executable application module",
            config_access.benchmark_primary_stage_type(config),
        )
        sys.exit(1)

    legacy_execution.validate_benchmark_execution_envelope(config)

    if config["infrastructure"]["provider"] == "baremetal":
        baremetal(config, machines, runner)
    elif config_access.orchestrator_name(config) == "mist":
        mist(config, machines, runner)
    elif config_access.has_addon(config, "openfaas"):
        serverless(config, machines, runner)
    elif config_access.orchestrator_name(config) == "none":
        endpoint_only(config, machines)
    elif config_access.orchestrator_name(config) in ("kubernetes", "kubeedge"):
        kube(config, machines, runner)
    elif config_access.orchestrator_name(config) in ("kubecontrol", "kube_kata"):
        kube_control(config, machines, runner)
    else:
        logging.error("ERROR: Don't have a deployment for this resource manager / application")
        sys.exit(1)


def print_raw_output(config, worker_output, endpoint_output):
    """Print the raw output

    Args:
        config (dict): Parsed configuration
        worker_output (list(list(str))): Output of each container ran on the edge
        endpoint_output (list(list(str))): Output of each endpoint container
    """
    logging.debug("Print raw output from subscribers and publishers")
    if (config["mode"] == "cloud" or config["mode"] == "edge") and worker_output:
        logging.debug("------------------------------------")
        logging.debug("%s OUTPUT", config["mode"].upper())
        logging.debug("------------------------------------")
        for _, out in worker_output:
            for line in out:
                logging.debug(line)

            logging.debug("------------------------------------")

    if config["infrastructure"]["endpoint_nodes"]:
        logging.debug("------------------------------------")
        logging.debug("ENDPOINT OUTPUT")
        logging.debug("------------------------------------")
        for out in endpoint_output:
            for line in out:
                logging.debug(line)

            logging.debug("------------------------------------")


def to_datetime(s):
    """Parse a datetime string from docker logs to a Python datetime object

    Args:
        s (str): Docker datetime string

    Returns:
        datetime: Python datetime object
    """
    s = s.split(" ")[0]
    s = s.replace("T", " ")

    # This + and Z business changes often. Now we're using this
    # It was (for +): s = s.replace("+", "")
    if "+" in s:
        s = s.split("+")[0]
    elif "Z" in s:
        s = s.split("Z")[0]

    s = s[: s.find(".") + 7]
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S.%f")


def baremetal(config, machines, runner=None):
    """Launch a mist computing deployment

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    # Start the worker
    app_vars = config["module"]["application"].start_worker(config, machines)
    container_names_work = application_runtime_helpers.start_worker(
        config,
        machines,
        app_vars,
        runner=runner,
    )

    # Start the endpoint
    container_names = endpoint.start_endpoint(config, machines)
    endpoint.wait_endpoint_completion(config, machines, config["endpoint_ssh"], container_names)

    # Wait for benchmark to finish
    endpoint.wait_endpoint_completion(config, machines, config["cloud_ssh"], container_names_work)

    # Now get raw output
    logging.info("Benchmark has been finished, prepare results")
    endpoint_output = endpoint.get_endpoint_output(config, machines, container_names, use_ssh=True)
    worker_output = application_runtime_helpers.get_worker_output(
        config,
        machines,
        container_names_work,
    )

    # Parse output into dicts, and print result
    print_raw_output(config, worker_output, endpoint_output)
    worker_metrics = config["module"]["application"].gather_worker_metrics(
        machines, config, worker_output, None
    )
    endpoint_metrics = config["module"]["application"].gather_endpoint_metrics(
        config, endpoint_output, container_names
    )
    config["module"]["application"].format_output(config, worker_metrics, endpoint_metrics)


def mist(config, machines, runner=None):
    """Launch a mist computing deployment

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    # Start the worker
    app_vars = config["module"]["application"].start_worker(config, machines)
    container_names_work = application_runtime_helpers.start_worker(
        config,
        machines,
        app_vars,
        runner=runner,
    )

    # Start the endpoint
    container_names = endpoint.start_endpoint(config, machines)
    endpoint.wait_endpoint_completion(config, machines, config["endpoint_ssh"], container_names)

    # Wait for benchmark to finish
    endpoint.wait_endpoint_completion(config, machines, config["edge_ssh"], container_names_work)

    # Now get raw output
    logging.info("Benchmark has been finished, prepare results")
    endpoint_output = endpoint.get_endpoint_output(config, machines, container_names, use_ssh=True)
    worker_output = application_runtime_helpers.get_worker_output(
        config,
        machines,
        container_names_work,
    )

    # Parse output into dicts, and print result
    print_raw_output(config, worker_output, endpoint_output)
    worker_metrics = config["module"]["application"].gather_worker_metrics(
        machines, config, worker_output, None
    )
    endpoint_metrics = config["module"]["application"].gather_endpoint_metrics(
        config, endpoint_output, container_names
    )
    config["module"]["application"].format_output(config, worker_metrics, endpoint_metrics)


def _start_openfaas_worker(runner):
    """Start the OpenFaaS serverless function deployment playbook.

    Args:
        runner (AnsibleRunner): Shared runner instance.
    """
    config = runner.config

    logging.info("Deploy serverless functions on %s", config["mode"])

    memory = min(1000, int(config_access.benchmark_param_float(config, "application_worker_memory") * 1000))
    cpu = min(1, config_access.benchmark_param_float(config, "application_worker_cpu"))
    extra_vars = {
        "app_name": config_access.benchmark_primary_stage_type(config).split("_")[0],
        "image": image_requirements.runtime_image_ref(
            config,
            os.path.join(config["registry"], config["images"]["worker"].split(":")[1]),
        ),
        "memory_req": memory,
        "cpu_req": cpu,
        "cpu_threads": max(1, int(cpu)),
    }
    playbook = application_runtime_helpers.resolve_benchmark_launch_playbook(
        config,
        runner=runner,
    )
    runner.run_playbook(playbook, inventory="vms", extra_vars=extra_vars)
    logging.info("Deployed %s serverless application", config["mode"])


def serverless(config, machines, runner):
    """Launch a serverless deployment using Kubernetes + OpenFaaS

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    # Start the worker
    _start_openfaas_worker(runner)

    # Start the endpoint
    container_names = endpoint.start_endpoint(config, machines)
    endpoint.wait_endpoint_completion(config, machines, config["endpoint_ssh"], container_names)

    # Now get raw output
    logging.info("Benchmark has been finished, prepare results")
    endpoint_output = endpoint.get_endpoint_output(config, machines, container_names, use_ssh=True)

    # Parse output into dicts, and print result
    print_raw_output(config, None, endpoint_output)
    endpoint_metrics = config["module"]["application"].gather_endpoint_metrics(
        config, endpoint_output, container_names
    )
    config["module"]["application"].format_output(config, None, endpoint_metrics)


def endpoint_only(config, machines):
    """Launch a deployment with only endpoint machines / apps

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    # Start the endpoint
    container_names = endpoint.start_endpoint(config, machines)
    endpoint.wait_endpoint_completion(config, machines, config["endpoint_ssh"], container_names)

    # Now get raw output
    logging.info("Benchmark has been finished, prepare results")
    endpoint_output = endpoint.get_endpoint_output(config, machines, container_names, use_ssh=True)

    # Parse output into dicts, and print result
    print_raw_output(config, None, endpoint_output)
    endpoint_metrics = config["module"]["application"].gather_endpoint_metrics(
        config, endpoint_output, container_names
    )
    config["module"]["application"].format_output(config, None, endpoint_metrics)


def kube(config, machines, runner=None):
    """Launch a K8 deployment, benchmarking K8's applications

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    # Cache the worker to prevent loading
    if config_access.orchestrator_bool_optional(config, "cache_worker", default=False):
        app_vars = config["module"]["application"].cache_worker(config, machines)
        application_runtime_helpers.cache_kubernetes_workers(
            config,
            machines,
            app_vars,
            runner=runner,
        )

    # Start the worker
    app_vars = config["module"]["application"].start_worker(config, machines)
    application_runtime_helpers.start_worker(
        config,
        machines,
        app_vars,
        runner=runner,
    )

    # Start the endpoint
    container_names = endpoint.start_endpoint(config, machines)
    endpoint.wait_endpoint_completion(config, machines, config["endpoint_ssh"], container_names)

    # Wait for benchmark to finish
    application_runtime_helpers.wait_kubernetes_worker_completion(config, machines)

    # Now get raw output
    logging.info("Benchmark has been finished, prepare results")
    endpoint_output = endpoint.get_endpoint_output(config, machines, container_names, use_ssh=True)
    worker_output = application_runtime_helpers.get_worker_output(config, machines)

    # Parse output into dicts, and print result
    print_raw_output(config, worker_output, endpoint_output)
    worker_metrics = config["module"]["application"].gather_worker_metrics(
        machines, config, worker_output, None
    )
    endpoint_metrics = config["module"]["application"].gather_endpoint_metrics(
        config, endpoint_output, container_names
    )
    config["module"]["application"].format_output(config, worker_metrics, endpoint_metrics)


def kube_control(config, machines, runner=None):
    """Launch a K8 deployment, benchmarking K8's controlplane instead of applications running on it

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    # Start the resource utilization metrics
    application_runtime_helpers.start_kubernetes_resource_metrics(config, machines)

    # Cache the worker to prevent loading
    if config_access.orchestrator_bool_optional(config, "cache_worker", default=False):
        app_vars = config["module"]["application"].cache_worker(config, machines)
        application_runtime_helpers.cache_kubernetes_workers(
            config,
            machines,
            app_vars,
            runner=runner,
        )

    benchmark_stage_type = config_access.benchmark_primary_stage_type(config)
    if benchmark_stage_type == "mem_usage":
        config["module"]["application"].get_mem_usage(
            config,
            machines,
            application_runtime_helpers.start_kubernetes_workers,
            runner,
        )

    # Start the worker
    app_vars = config["module"]["application"].start_worker(config, machines)
    starttime, kubectl_out, status = application_runtime_helpers.start_worker(
        config, machines, app_vars, get_starttime=True, runner=runner
    )

    # Wait for benchmark to finish
    application_runtime_helpers.wait_kubernetes_worker_completion(config, machines)

    # Now get raw output
    logging.info("Benchmark has been finished, prepare results")

    worker_output = application_runtime_helpers.get_worker_output(config, machines)
    worker_description = application_runtime_helpers.get_worker_output(
        config,
        machines,
        get_description=True,
    )

    control_output, endtime = application_runtime_helpers.get_kubernetes_control_output(
        config,
        machines,
        starttime,
        status,
    )

    resource_output = application_runtime_helpers.get_kubernetes_resource_output(
        config, machines, starttime, endtime, runner=runner
    )

    # Add kubectl output
    node = config["cloud_ssh"][0].split("@")[0]
    control_output[node]["kubectl"] = kubectl_out

    runtime = config_access.orchestrator_overrides(config, ("runtime",)).get("runtime")
    if isinstance(runtime, str) and "kata" in runtime:
        if benchmark_stage_type == "empty_kata":
            kata_ts = kube_kata.get_kata_timestamps(config, worker_output)
            config["module"]["application"].format_output(
                config,
                None,
                status=status,
                control=control_output,
                starttime=starttime,
                worker_output=worker_output,
                worker_description=worker_description,
                resource_output=resource_output,
                endtime=float(endtime - starttime),
                kata_ts=kata_ts,
            )
        elif benchmark_stage_type == "stress":
            stress_dur = kube_kata.get_deployment_duration(config, machines)
            logging.info("Total stress duration: %s", stress_dur)

    # Parse output into dicts, and print result
    print_raw_output(config, worker_output, [])

    config["module"]["application"].format_output(
        config,
        None,
        status=status,
        control=control_output,
        starttime=starttime,
        worker_output=worker_output,
        worker_description=worker_description,
        resource_output=resource_output,
        endtime=float(endtime - starttime),
    )
