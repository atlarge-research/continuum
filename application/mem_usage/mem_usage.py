"""Manage the stress application"""


def set_container_location(config):
    from ..empty.empty import set_container_location as empty_set_container_location

    return empty_set_container_location(config)


def add_options(_config):
    # from ..empty.empty import add_options as empty_add_options

    # return empty_add_options(_config)
    return []


def verify_options(parser, config):
    if config["benchmark"]["application"] != "mem_usage":
        parser.error("ERROR: Application should be mem_usage")
    elif config["benchmark"]["resource_manager"] != "kubecontrol":
        parser.error("ERROR: Application mem_usage requires resource_manager kubecontrol")
    # elif int(config["benchmark"]["sleep_time"]) < 6000 :
    #     parser.error("ERROR: Application mem_usage requires that pods don't sleep (>6000)")


def cache_worker(_config, _machines):
    from ..empty.empty import cache_worker as empty_cache_worker

    return empty_cache_worker(_config, _machines)


def start_worker(config, _machines):
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


def get_mem_usage(config, machines, start_worker_kube):
    import logging
    import sys
    import time

    from resource_manager.kubernetes import kubernetes

    def deploy_memory_deployment(config, machines, replicas: int):
        app_vars = start_worker(config, machines)

        kubernetes.start_worker_kube(config, machines, app_vars, get_starttime=True)

        command = "kubectl get pods | grep -c Running"

        running_pods = 0
        while running_pods != replicas:
            output, error = machines[0].process(
                config, command, shell=True, ssh=config["cloud_ssh"][0]
            )[0]

            # if error:
            #     logging.error("error while checking for runing pods")
            #     sys.exit(1)

            running_pods = int(output[0])
            time.sleep(5)

    def undeploy_memory_deployment(config, machines):
        logging.info("deleting k8s memory deployment")

        command = f"kubectl delete job.batch --all"

        output, error = machines[0].process(
            config, command, shell=True, ssh=config["cloud_ssh"][0]
        )[0]

        # if error:
        #     logging.error("deleting k8s memory test deployment failed")
        #     sys.exit(1)

        logging.info(f"output: {output}")

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
    logging.info(f"Worker free memory before deployment: {mem_before} MB")

    deploy_memory_deployment(config, machines, replicas)

    mem_after = get_free_memory(config, machines)
    logging.info(f"Worker free memory after deployment -> {mem_after} MB")

    mem_per_cont = (mem_before - mem_after) / replicas
    logging.info(f"mem usage per container -> {mem_per_cont} MB")

    undeploy_memory_deployment(config, machines)
