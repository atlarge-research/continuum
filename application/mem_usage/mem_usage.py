"""Manage the stress application"""

import logging
import time

from application import runtime_helpers
from input.configuration import config_access

from ..empty.empty import cache_worker as empty_cache_worker
from ..empty.empty import set_container_location as empty_set_container_location


def set_container_location(config):
    """Set registry location/path of containerized applications

    Args:
        config (dict): Parsed configuration

    Returns:
        list[list[str]]: Container image location overrides.
    """
    return empty_set_container_location(config)


def add_options(_config):
    """Add config options for a particular module

    Args:
        config (ConfigParser): ConfigParser object

    Returns:
        list(list()): Options to add
    """
    return []


def verify_options(parser, config):
    """Verify the config from the module's requirements

    Args:
        parser (ArgumentParser): Argparse object
        config (ConfigParser): ConfigParser object
    """
    if config_access.benchmark_primary_stage_type(config) != "mem_usage":
        parser.error("ERROR: Application should be mem_usage")
    elif config_access.orchestrator_name(config) != "kubecontrol":
        parser.error("ERROR: Application mem_usage requires resource_manager kubecontrol")
    # elif int(config["benchmark"]["sleep_time"]) < 6000 :
    #     parser.error("ERROR: Application mem_usage requires that pods don't sleep (>6000)")


def cache_worker(_config, _machines):
    """Set variables needed when launching the app for caching.

    Args:
        _config (dict): Parsed configuration (unused, delegates to empty).
        _machines (list): List of machine objects (unused).

    Returns:
        dict: Application variables for cache worker.
    """
    return empty_cache_worker(_config, _machines)


def start_worker(_config, _machines):
    """Set variables needed when launching the app on workers

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines

    Returns:
        (dict): Application variables
    """
    app_vars = {
        "sleep_time": 6000,
    }
    return app_vars


def get_mem_usage(config, machines, _start_worker_kube):
    """Measure memory usage per container by deploying and comparing free memory.

    Args:
        config (dict): Parsed configuration.
        machines (list): List of machine objects representing physical machines.
        _start_worker_kube: Unused; worker start function reference.
    """

    def deploy_memory_deployment(config, machines, replicas: int):
        app_vars = start_worker(config, machines)

        runtime_helpers.start_kubernetes_workers(
            config,
            machines,
            app_vars,
            get_starttime=True,
        )

        command = "kubectl get pods | grep -c Running"

        running_pods = 0
        while running_pods != replicas:
            output, _ = machines[0].process(
                config, command, shell=True, ssh=config["cloud_ssh"][0]
            )[0]

            # if error:
            #     logging.error("error while checking for runing pods")
            #     sys.exit(1)

            running_pods = int(output[0])
            time.sleep(5)

    def undeploy_memory_deployment(config, machines):
        logging.info("deleting k8s memory deployment")

        command = "kubectl delete job.batch --all"

        output, _ = machines[0].process(config, command, shell=True, ssh=config["cloud_ssh"][0])[0]

        # if error:
        #     logging.error("deleting k8s memory test deployment failed")
        #     sys.exit(1)

        logging.info("output: %s", output)

    def get_free_memory(config, machines) -> int:
        command = "free -m | awk 'NR==2{print $4}'"
        output, error = machines[0].process(
            config, command, shell=True, ssh=config["cloud_ssh"][1]
        )[0]

        if error:
            logging.error("could not get free memory of worker node")
            return -1

        return int(output[0])

    replicas = config_access.benchmark_param_int(config, "applications_per_worker")

    mem_before = get_free_memory(config, machines)
    logging.info("Worker free memory before deployment: %i MB", mem_before)

    deploy_memory_deployment(config, machines, replicas)

    mem_after = get_free_memory(config, machines)
    logging.info("Worker free memory after deployment -> %i MB", mem_after)

    mem_per_cont = (mem_before - mem_after) / replicas
    logging.info("mem usage per container -> %i MB", mem_per_cont)

    undeploy_memory_deployment(config, machines)
