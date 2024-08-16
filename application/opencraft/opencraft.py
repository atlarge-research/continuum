"""Manage the OpenCraft application"""

from . import plot


def set_container_location(config):
    """Set registry location/path of containerized applications

    Args:
        config (dict): Parsed configuration
    """
    # TODO update container location -- these will be deployed on K8s -- should be on Dockerhub
    source = "redplanet00/kubeedge-applications"
    config["images"] = {
        "worker_client": "%s:empty" % (source),
        "worker_renderer": "%s:empty" % (source),
        "worker_server": "%s:empty" % (source),
        "worker_monitor": "%s:empty" % (source),
        "worker_scheduler": "%s:empty" % (source),
    }


def add_options(config):
    """Add config options for a particular module

    Args:
        config (ConfigParser): ConfigParser object

    Returns:
        list(list()): Options to add
    """
    # TODO update app-specific parameters
    # TODO add the parameters to a config file
    # TODO update the launch_benchmark_kubernetes_*.yml files to pass the parameters to the app
    nodes = config["infrastructure"]["cloud_nodes"] - 1
    cpu = config["infrastructure"]["cloud_cores"]
    memory = config["infrastructure"]["cloud_memory"]
    default_cpu = config["benchmark"]["application_worker_cpu"]
    default_mem = config["benchmark"]["application_worker_memory"]

    #   ["param_name", type, condition      , mandatory, default_value]
    # Note: Default value can be ignored if mandatory == True
    settings = [
        ["sleep_time", int, lambda x: x >= 1, True, False],
        ["node_client", int, lambda x: 0 <= x <= nodes, False, 0],
        ["node_renderer", int, lambda x: 0 <= x <= nodes, False, 0],
        ["node_server", int, lambda x: 0 <= x <= nodes, False, 0],
        ["node_monitor", int, lambda x: 0 <= x <= nodes, False, 0],
        ["node_scheduler", int, lambda x: 0 <= x <= nodes, False, 0],
        ["cpu_client", float, lambda x: 0.001 <= x <= cpu, False, default_cpu],
        ["cpu_renderer", float, lambda x: 0.001 <= x <= cpu, False, default_cpu],
        ["cpu_server", float, lambda x: 0.001 <= x <= cpu, False, default_cpu],
        ["cpu_monitor", float, lambda x: 0.001 <= x <= cpu, False, default_cpu],
        ["cpu_scheduler", float, lambda x: 0.001 <= x <= cpu, False, default_cpu],
        ["memory_client", float, lambda x: 0.001 <= x <= memory, False, default_mem],
        ["memory_renderer", float, lambda x: 0.001 <= x <= memory, False, default_mem],
        ["memory_server", float, lambda x: 0.001 <= x <= memory, False, default_mem],
        ["memory_monitor", float, lambda x: 0.001 <= x <= memory, False, default_mem],
        ["memory_scheduler", float, lambda x: 0.001 <= x <= memory, False, default_mem],
    ]
    return settings


def verify_options(parser, config):
    """Verify the config from the module's requirements

    Args:
        parser (ArgumentParser): Argparse object
        config (ConfigParser): ConfigParser object
    """
    if config["benchmark"]["application"] != "opencraft":
        parser.error("ERROR: Application should be opencraft")
    elif config["benchmark"]["resource_manager"] != "kubernetes":
        parser.error("ERROR: Application opencraft requires resource_manager kubernetes")
    elif (
        config["infrastructure"]["cloud_nodes"] == 0
        or config["infrastructure"]["edge_nodes"] > 0
        or config["infrastructure"]["endpoint_nodes"] > 0
    ):
        parser.error("ERROR: Opencraft only supports cloud VM deployment at the moment")
    elif list(range(0, config["infrastructure"]["cloud_nodes"])) != list(
        set(
            {
                config["benchmark"]["node_client"],
                config["benchmark"]["node_renderer"],
                config["benchmark"]["node_server"],
                config["benchmark"]["node_monitor"],
                config["benchmark"]["node_scheduler"],
            }
        )
    ):
        parser.error(
            "ERROR: Not all %i VMs have applications scheduled onto them",
            config["infrastructure"]["cloud_nodes"],
        )
    elif config["infrastructure"]["provider"] != "aws":
        parser.error("Error: Opencraft deployment has only been tested on AWS")

    # TODO add possibly more parameter verifications with the app and options from add_options
    #      I'm not going to check the node/cpu/memory settings in-depth, I assume it's fine


def cache_worker(config, _machines):
    """Set variables needed when launching the app for caching

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines

    Returns:
        (dict): Application variables
    """
    # TODO update variables. Should be in line with add_options()
    #      These are used for a dry run of the application

    m = config["mode"]  # Should be "cloud"
    app_vars = {
        "sleep_time": 15,
        "node_client": m + str(config["benchmark"]["node_client"]),
        "node_renderer": m + str(config["benchmark"]["node_renderer"]),
        "node_server": m + str(config["benchmark"]["node_server"]),
        "node_monitor": m + str(config["benchmark"]["node_monitor"]),
        "node_scheduler": m + str(config["benchmark"]["node_scheduler"]),
        "cpu_client": config["benchmark"]["cpu_client"],
        "cpu_renderer": config["benchmark"]["cpu_renderer"],
        "cpu_server": config["benchmark"]["cpu_server"],
        "cpu_monitor": config["benchmark"]["cpu_monitor"],
        "cpu_scheduler": config["benchmark"]["cpu_scheduler"],
        "memory_client": int(config["benchmark"]["memory_client"] * 1000),
        "memory_renderer": int(config["benchmark"]["memory_renderer"] * 1000),
        "memory_server": int(config["benchmark"]["memory_server"] * 1000),
        "memory_monitor": int(config["benchmark"]["memory_monitor"] * 1000),
        "memory_scheduler": int(config["benchmark"]["memory_scheduler"] * 1000),
    }
    return app_vars


def start_worker(config, _machines):
    """Set variables needed when launching the app on workers

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines

    Returns:
        (dict): Application variables
    """
    # TODO this dict will be passed to the launch_benchmark.yml scripts. Update as needed

    m = config["mode"]  # Should be "cloud"
    app_vars = {
        "sleep_time": config["benchmark"]["sleep_time"],
        "node_client": m + str(config["benchmark"]["node_client"]),
        "node_renderer": m + str(config["benchmark"]["node_renderer"]),
        "node_server": m + str(config["benchmark"]["node_server"]),
        "node_monitor": m + str(config["benchmark"]["node_monitor"]),
        "node_scheduler": m + str(config["benchmark"]["node_scheduler"]),
        "cpu_client": config["benchmark"]["cpu_client"],
        "cpu_renderer": config["benchmark"]["cpu_renderer"],
        "cpu_server": config["benchmark"]["cpu_server"],
        "cpu_monitor": config["benchmark"]["cpu_monitor"],
        "cpu_scheduler": config["benchmark"]["cpu_scheduler"],
        "memory_client": int(config["benchmark"]["memory_client"] * 1000),
        "memory_renderer": int(config["benchmark"]["memory_renderer"] * 1000),
        "memory_server": int(config["benchmark"]["memory_server"] * 1000),
        "memory_monitor": int(config["benchmark"]["memory_monitor"] * 1000),
        "memory_scheduler": int(config["benchmark"]["memory_scheduler"] * 1000),
    }
    return app_vars


def gather_worker_metrics(_machines, _config, worker_output, _starttime):
    """Gather metrics from cloud workers

    Args:
        machines (list(Machine object)): List of machine objects representing physical machines
        config (dict): Parsed configuration
        worker_output (list(list(str))): Output of each container ran on the edge
        starttime (datetime): Time that 'kubectl apply' is called to launche the benchmark

    Returns:
        list(dict): List of parsed output for each cloud workers
    """
    # TODO parse container outputs as needed
    #      It has the following format:
    #       worker_output = [
    #           [pod_name1, ["output-line1", "output-line-2", ...]],
    #           [pod_name2, ["output-line1", "output-line-2", ...]],
    #       ]
    pass


def gather_endpoint_metrics(config, endpoint_output, container_names):
    """Gather metrics from endpoints

    --- DO NOT USE THIS FUNCTION ---

    Args:
        config (dict): Parsed configuration
        endpoint_output (list(list(str))): Output of each endpoint container
        container_names (list(str)): Names of docker containers launched

    Returns:
        list(dict): List of parsed output for each endpoint
    """
    pass


def format_output(config, worker_metrics, endpoint_metrics, resource_output=None, endtime=None):
    """Format processed output to provide useful insights

    Args:
        config (dict): Parsed configuration
        sub_metrics (list(dict)): Metrics per worker node
        endpoint_metrics (list(dict)): Metrics per endpoint
    """
    # TODO present the output of the run. Visually in the terminal, in a file, etc.

    # An example is to print/plot stuff, like resource usage:
    df_resources = _print_resources(config, resource_output)
    plot.plot_resources(df_resources, config["timestamp"], xmax=endtime)


def _print_resources(config, df):
    """Modify the resource dataframe and save it to csv

    Example:
    timestamp cloud0matthijs_cpu  cloud0matthijs_memory  cloudcontrollermatthijs_cpu   ...
    0.359692                 103                    419                         1481   ...
    0.534534                 103                    419                         1481   ...
    0.934234                 103                    419                         1481   ...
    1.323432                 103                    419                         1481   ...

    etcd_cpu  etcd_memory  apiserver_cpu  apiserver_memory  controller-manager_cpu     ...
         948           39             28               196                     270     ...
         948           39             28               196                     270     ...
         948           39             28               196                     270     ...
         948           39             28               196                     270     ...

    Args:
        config (dict): Parsed configuration
        df (DataFrame): Resource metrics data

    Returns:
        (DataFrame) Pandas dataframe object with parsed timestamps per category
    """
    df_kube = df[0]
    df_os = df[1]

    df_kube.columns = ["Time (s)" if c == "timestamp" else c for c in df_kube.columns]
    df_kube.columns = [
        "controller_" + c.split("_")[-1] if "controller" in c else c for c in df_kube.columns
    ]
    df_kube.columns = [
        c.replace(config["username"], "") if config["username"] in c else c for c in df_kube.columns
    ]

    # Save to csv
    df_kube.to_csv(
        "./logs/%s_dataframe_resources.csv" % (config["timestamp"]), index=False, encoding="utf-8"
    )

    # df os only needs to be saved - we already renamed it beforehand
    df_os.to_csv(
        "./logs/%s_dataframe_resources_os.csv" % (config["timestamp"]),
        index=False,
        encoding="utf-8",
    )

    return df
