"""Manage the stress application"""

import logging
import time

from resource_manager.kubernetes import kubernetes

from ..empty.empty import set_container_location as empty_set_container_location
from ..empty.empty import cache_worker as empty_cache_worker


def set_container_location(config):
    """Set registry location/path of containerized applications

    Args:
        config (dict): Parsed configuration
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
    if config["benchmark"]["application"] != "mem_usage":
        parser.error("ERROR: Application should be mem_usage")
    elif config["benchmark"]["resource_manager"] != "kubecontrol":
        parser.error("ERROR: Application mem_usage requires resource_manager kubecontrol")
    # elif int(config["benchmark"]["sleep_time"]) < 6000 :
    #     parser.error("ERROR: Application mem_usage requires that pods don't sleep (>6000)")


def cache_worker(_config, _machines):
    """See called function

    Args:
        _config (_type_): _description_
        _machines (_type_): _description_

    Returns:
        _type_: _description_
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
    """Get memory usage

    Args:
        config (_type_): _description_
        machines (_type_): _description_
        _start_worker_kube (_type_): _description_
    """

    def deploy_memory_deployment(config, machines, replicas: int):
        app_vars = start_worker(config, machines)

        kubernetes.start_worker_kube(config, machines, app_vars, get_starttime=True)

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

    replicas = config["benchmark"]["applications_per_worker"]

    mem_before = get_free_memory(config, machines)
    logging.info("Worker free memory before deployment: %i MB", mem_before)

    deploy_memory_deployment(config, machines, replicas)

    mem_after = get_free_memory(config, machines)
    logging.info("Worker free memory after deployment -> %i MB", mem_after)

    mem_per_cont = (mem_before - mem_after) / replicas
    logging.info("mem usage per container -> %i MB", mem_per_cont)

    undeploy_memory_deployment(config, machines)
