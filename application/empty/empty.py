"""Manage the empty application"""

import logging
import sys
import copy
import time

from datetime import datetime

import pandas as pd

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator


def set_container_location(config):
    """Set registry location/path of containerized applications

    Args:
        config (dict): Parsed configuration
    """
    source = "redplanet00/kubeedge-applications"
    config["images"] = {"worker": "%s:empty" % (source)}


def add_options(_config):
    """Add config options for a particular module

    Args:
        config (ConfigParser): ConfigParser object

    Returns:
        list(list()): Options to add
    """
    settings = [
        ["sleep_time", int, lambda x: x >= 1, True, False],
        ["kube_deployment", str, lambda x: x in ["pod", "container", "file", "call"], False, "pod"],
        [
            "kube_version",
            str,
            lambda _: ["v1.27.0", "v1.26.0", "v1.25.0", "v1.24.0", "v1.23.0"],
            False,
            "v1.27.0",
        ],
    ]
    return settings


def verify_options(parser, config):
    """Verify the config from the module's requirements

    Args:
        parser (ArgumentParser): Argparse object
        config (ConfigParser): ConfigParser object
    """
    if config["benchmark"]["application"] != "empty":
        parser.error("ERROR: Application should be empty")
    elif config["benchmark"]["resource_manager"] != "kubecontrol":
        parser.error("ERROR: Application empty requires resource_manager kubecontrol")


def cache_worker(_config, _machines):
    """Set variables needed when launching the app for caching

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines

    Returns:
        (dict): Application variables
    """
    app_vars = {
        "sleep_time": 30,
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
    app_vars = {
        "sleep_time": config["benchmark"]["sleep_time"],
    }
    return app_vars


def time_delta(t, starttime):
    """Calculate a time delta.
    Timezones may not be applied to all measurement data,
    so we need to detect and correct negative time deltas manually

    Args:
        t (float): Timestamp of a particular event
        starttime (float): Timestamp of the start of the benchmark

    Returns:
        float: Possitive time delta
    """
    delta = t - starttime
    seconds_per_hour = float(3600)
    while delta < float(0):
        delta += seconds_per_hour

    return delta


def format_output(
    config,
    worker_metrics,
    status=None,
    control=None,
    starttime=None,
    worker_output=None,
    worker_description=None,
):
    """Format processed output to provide useful insights (empty)

    Args:
        config (dict): Parsed configuration
        worker_metrics (list(dict)): Metrics per worker node
        status (list(list(str)), optional): Status of started Kubernetes pods over time
        control (list(str), optional): Parsed output from control plane components
        starttime (datetime, optional): Invocation time of kubectl apply command
        worker_output (list(list(str)), optional): Output of each container ran on the edge
        worker_description (list(list(str)), optional): Extensive description of each container
    """
    # Plot the status of each pod over time
    if status is not None:
        plot_status(status)

        if control is not None:
            worker_metrics = fill_control(
                config, control, starttime, worker_output, worker_description
            )
            df = print_control(config, worker_metrics)
            plot_control(df)
            plot_p56(df)


def plot_status(status):
    """Print and plot controlplane data from external observations

    Args:
        status (list(list(str)), optional): Status of started Kubernetes pods over time
    """
    for stat in status:
        logging.debug(stat)

    # Make sure matplotlib doesn't inherit our own logging level
    logging.getLogger("matplotlib").setLevel("WARNING")

    # From: https://docs.openstack.org/developer/performance-docs/test_results/
    #           container_cluster_systems/kubernetes/density/index.html
    _, ax1 = plt.subplots(figsize=(12, 6))

    # Re-format data
    times = [s["time"] for s in status]
    arriving = [s["Arriving"] for s in status]
    pending = [s["Pending"] for s in status]
    containercreating = [s["ContainerCreating"] for s in status]
    running = [s["Running"] for s in status]
    succeeded = [s["Succeeded"] for s in status]

    categories = []
    results = []
    if sum(arriving) > 0:
        categories.append("Arriving")
        results.append(arriving)
    if sum(pending) > 0:
        categories.append("Pending")
        results.append(pending)
    if sum(containercreating) > 0:
        categories.append("ContainerCreating")
        results.append(containercreating)
    if sum(running) > 0:
        categories.append("Running")
        results.append(running)
    if sum(succeeded) > 0:
        categories.append("Succeeded")
        results.append(succeeded)

    colors = {
        "Arriving": "#cc0000",
        "Pending": "#ffb624",
        "ContainerCreating": "#ebeb00",
        "Running": "#50c878",
        "Succeeded": "#a366ff",
    }

    cs = [colors[cat] for cat in categories]
    ax1.stackplot(times, results, colors=cs, step="post")

    ax1.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.invert_yaxis()
    ax1.grid(True)

    # Set y axis details
    total_pods = sum(status[0][cat] for cat in categories)
    ax1.set_ylabel("Pods")
    ax1.set_ylim(0, total_pods)

    # Set x axis details
    ax1.set_xlabel("Time (s)")
    ax1.set_xlim(0, status[-1]["time"])

    # add legend
    patches = [mpatches.Patch(color=c) for c in cs]
    texts = categories
    ax1.legend(patches, texts, loc="upper right")

    # Save plot
    t = time.strftime("%Y-%m-%d_%H:%M:%S", time.gmtime())
    plt.savefig("./logs/%s_breakdown.pdf" % (t), bbox_inches="tight")


def create_control_object(config, worker_description):
    # Create object to store all metrics in
    worker_metrics = []
    worker_set = {
        "pod": None,  # Name of the pod for which these metrics are captured
        "container": None,  # Name of the container in the pod
        "manage_job": None,  # Time to start job manager
        "pod_object": None,  # Time to create pod object
        "scheduler_queue": None,  # Time to schedule
        "pod_create": None,  # Time to create pod
        "container_create": None,  # Time to create container
        "container_created": None,  # Time to created container
        "app_start": None,  # Time to app in container
        "C_start_pod": None,  # 0500 Kubelet starts processing pod pod=default/empty-nzdcl
        "C_volume_mount": None,  # 0504 Make data directories pod=default/empty-nzdcl
        "C_apply_sandbox": None,  # 0511 apply sandbox resources pod=default/empty-nzdcl
        "C_start_cont": None,  # 0521 start containers if scaled pod=default/empty-nzdcl
        "C_pod_done": None,  # 0515 Pod is done pod=default/empty-nzdcl
    }

    # This breaks when you have multiple multi-container pods
    last_container_id_index = 0

    # Set pod and container object per metric set
    for out in worker_description:
        container_id_index = 0
        container_id = ""
        pod_name = ""

        for line in out:
            if "name: empty-" in line and pod_name == "":
                # Only take the first mention - this is the pod name
                # All following mentions are container names - we don't need those
                pod_name = line.split("name: ")[1]
            elif "containerID" in line and container_id_index <= last_container_id_index:
                # Works with single and multiple containers per pod
                container_id = line.split("://")[1]
                if container_id_index == last_container_id_index:
                    last_container_id_index += 2  # Every containerID is printed twice
                    container_id_index += 2

                container_id_index += 1

        if container_id == "":
            logging.error("ERROR: container_id could not be be set")
            sys.exit()
        elif pod_name == "":
            logging.error("ERROR: pod_name could not be be set")
            sys.exit()

        w_set = copy.deepcopy(worker_set)
        w_set["pod"] = pod_name
        w_set["container"] = container_id
        worker_metrics.append(w_set)

    return worker_metrics


def check(
    config,
    control,
    starttime,
    worker_metrics,
    sub_component,
    sub_string,
    tag,
    is_controlplane,
    is_break=False,
):
    """_summary_

    Args:
        config (_type_): _description_
        control (_type_): _description_
        starttime (_type_): _description_
        worker_metrics (_type_): _description_
        sub_component (_type_): _description_
        sub_string (_type_): _description_
        tag (_type_): _description_
        is_controlplane (bool): _description_
        is_break (bool, optional): _description_. Defaults to False.
    """
    logging.debug(
        "Parsing output for component [%s], with tag [%s] and line: %s",
        sub_component,
        tag,
        sub_string,
    )
    controlplane_node = "controller"
    if config["infrastructure"]["provider"] == "gcp":
        controlplane_node = "cloud0"

    i = 0
    for node, output in control.items():
        if (controlplane_node in node and is_controlplane) or (
            controlplane_node not in node and not is_controlplane
        ):
            for component, out in output.items():
                if component == sub_component:
                    for t, line in out:
                        if sub_string in line:
                            if i > len(worker_metrics):
                                logging.debug("WARNING: i > number of deployed pods. Skip")
                                continue

                            if "pod=" in line and "container=" in line:
                                # Match pod and container
                                strip = line.strip().split("pod=")[1]
                                if "default/" in pod:
                                    strip = strip.split("default/")[1]

                                strip = strip.split(" container=")
                                pod = strip[0]
                                container = strip[1]

                                for metric in worker_metrics:
                                    if (
                                        metric["pod"] == pod
                                        and metric["container"] == container
                                        and metric[tag] == None
                                    ):
                                        metric[tag] = time_delta(t, starttime)
                            elif "pod=" in line:
                                # Add to correct pod
                                pod = line.strip().split("pod=")[1]
                                if "default/" in pod:
                                    pod = pod.split("default/")[1]

                                for metric in worker_metrics:
                                    if metric["pod"] == pod and metric[tag] == None:
                                        metric[tag] = time_delta(t, starttime)
                            elif "container=" in line:
                                # Add to correct container
                                container = line.strip().split("container=default/")[1]
                                for metric in worker_metrics:
                                    if metric["container"] == container and metric[tag] == None:
                                        metric[tag] = time_delta(t, starttime)
                            elif worker_metrics[i][tag] == None:
                                # For job (first phase), just add in order
                                worker_metrics[i][tag] = time_delta(t, starttime)
                                i += 1

                            if is_break:
                                break

    # Fill up if there are multiple containers per pod
    if config["benchmark"]["kube_deployment"] == "container" or is_break:
        j = i - 1
        while i < len(worker_metrics):
            worker_metrics[i][tag] = worker_metrics[j][tag]
            i += 1


def fill_control(config, control, starttime, worker_output, worker_description):
    """Gather all data/timestamps on control plane activities
    1. Kubectl apply                  -> starttime
    2. Scheduling queue               -> 0124
    3. Container creation             ->
    4. Container created              ->
    5. Code is running in container   -> kubectl logs <pod>

    Args:
        config (dict): Parsed configuration
        control (list(str), optional): Parsed output from control plane components
        starttime (datetime, optional): Invocation time of kubectl apply command
        worker_output (list(list(str))): Output of each container ran on the edge
        worker_description (list(list(str))): Extensive description of each container
    """
    logging.info("Gather metrics on deployment phases")
    worker_metrics = create_control_object(config, worker_description)

    # Start job manager
    check(
        config,
        control,
        starttime,
        worker_metrics,
        "controller-manager",
        "0028",
        "manage_job",
        True,
        is_break=config["benchmark"]["kube_deployment"] in ["container", "pod"],
    )

    # Pod object creation time
    check(
        config,
        control,
        starttime,
        worker_metrics,
        "controller-manager",
        "0277",
        "pod_object",
        True,
    )

    # Scheduler time
    check(
        config,
        control,
        starttime,
        worker_metrics,
        "scheduler",
        "0124",
        "scheduler_queue",
        True,
    )

    # Container creation
    # TODO: Pin to container as well
    for i, output in enumerate(worker_output):
        for line in output:
            if "Start the application" in line:
                dt = line.split("Z")[0]
                dt = dt.replace("T", " ")
                dt = dt[:-3]
                dt = datetime.strptime(dt, "%Y-%m-%d %H:%M:%S.%f")
                end_time = datetime.timestamp(dt)

                worker_metrics[i]["app_start"] = time_delta(end_time, starttime)

    # Pod creation
    check(
        config,
        control,
        starttime,
        worker_metrics,
        "kubelet",
        "0330",
        "pod_create",
        False,
    )

    # Container creation
    check(
        config,
        control,
        starttime,
        worker_metrics,
        "kubelet",
        "0514 Start containers",
        "container_create",
        False,
    )

    # Container created
    check(
        config,
        control,
        starttime,
        worker_metrics,
        "kubelet",
        "0515 Pod is done",
        "container_created",
        False,
    )

    # --------------------------------------------------
    # EXTRA FOR ZOOM IN PLOT
    check(
        config,
        control,
        starttime,
        worker_metrics,
        "kubelet",
        "0500",
        "C_start_pod",
        False,
    )

    check(
        config,
        control,
        starttime,
        worker_metrics,
        "kubelet",
        "0504",
        "C_volume_mount",
        False,
    )

    check(
        config,
        control,
        starttime,
        worker_metrics,
        "kubelet",
        "0511",
        "C_apply_sandbox",
        False,
    )

    check(
        config,
        control,
        starttime,
        worker_metrics,
        "kubelet",
        "0521",
        "C_start_cont",
        False,
    )

    check(
        config,
        control,
        starttime,
        worker_metrics,
        "kubelet",
        "0515 Pod is done",
        "C_pod_done",
        False,
    )

    return worker_metrics


def print_control(config, worker_metrics):
    """Print controlplane data from the source code

    Args:
        config (dict): Parsed configuration
        worker_metrics (list(dict)): Metrics per worker node

    Returns:
        (DataFrame) Pandas dataframe object with parsed timestamps per category
    """
    logging.info("------------------------------------")
    logging.info("%s OUTPUT", config["mode"].upper())
    logging.info("------------------------------------")
    df = pd.DataFrame(worker_metrics)
    df.rename(
        columns={
            "manage_job": "created_workload_obj (s)",
            "pod_object": "unpacked_workload_obj (s)",
            "scheduler_queue": "created_pod_obj (s)",
            "pod_create": "scheduled_pod (s)",
            "container_create": "created_pod (s)",
            "app_start": "created_container (s)",
            "C_start_pod": "P5_scheduled_pod (s)",
            "C_volume_mount": "P5_started_pod (s)",
            "C_apply_sandbox": "P5_mounted_volume (s)",
            "C_start_cont": "P5_applied_sandbox (s)",
            "C_pod_done": "P6_started_container (s)",
        },
        inplace=True,
    )
    df = df.sort_values(by=["created_container (s)"])

    df_no_indices = df.to_string(index=False)
    logging.info("\n%s", df_no_indices)

    # Print ouput in csv format
    logging.debug("Output in csv format\n%s", repr(df.to_csv()))

    return df


def plot_control(df):
    """Plot controlplane data from the source code

    Phases:
    1: Create workload        [starttime, manage_job]
      - Starts when the user executes KubeCTL
          - Times in Continuum
      - Ends when the resource controller (e.g., job controller)
        receives the workload resource object
          - Source code 0028
      - In between, the APIserver creates the workload resource object in the datastore
        and the appropiate resource controller notices that resource has been created

    2: Unpack workload        [manage_job, pod_object]
      - Ends right before a pod is created for a particular workload instance
          - Source code 0277
      - In between, workload-wide stuff is checked like permissions, and the object is
        unpacked into workload instances if parallelism is used. Each instance is
        treated seperately from here on.

    3: Pod object creation    [pod_object, scheduler_queue]
      - Ends right before pod is added to the scheduling queue
          - Source code 0124
      - In between, a pod is created for a workload instance, is written to the datastore
        via the APIserver, which the scheduler notices and adds to its scheduling queue

    4: Scheduling             [scheduler_queue, pod_create]
      - Ends when the container runtime on a worker starts creating resources for this pod
      - In between, the pod is added to the scheduling queue, the scheduler attempts to
        and eventually successfully schedules the pod onto a worker node, and writes
        the status update back to the datastore via the APIserver

    5: Pod creation           [pod_create, container_create]
      - Ends when containers inside the pod are starting to be created
      - In between, the kubelet notices a pod object in the datastore has been assigned to
        the worker node of that kubelet, and calls various OS-level software packages and
        the container runtime to create a pod abstraction, including process+network namespaces

    6: Container creation     [container_create, app_start]
      - Ends when the application in the container prints output
      - In between, all containers inside the pod are being created, the pod and containers are
        being started and the code inside the container starts executing

    7: Application run        [app_start, >]
      - Application code inside the container is running

    Args:
        df (DataFrame): Pandas dataframe object with parsed timestamps per category
    """
    plt.rcParams.update({"font.size": 20})
    _, ax1 = plt.subplots(figsize=(12, 4))

    bar_height = 1.1

    df_plot = df.copy(deep=True)
    df_plot = df_plot[
        [
            "created_workload_obj (s)",
            "unpacked_workload_obj (s)",
            "created_pod_obj (s)",
            "scheduled_pod (s)",
            "created_pod (s)",
            "created_container (s)",
        ]
    ]
    y = [*range(len(df_plot["created_workload_obj (s)"]))]

    left = [0 for _ in range(len(y))]

    colors = {
        "P1": "#6929c4",
        "P2": "#1192e8",
        "P3": "#005d5d",
        "P4": "#9f1853",
        "P5": "#fa4d56",
        "P6": "#570408",
        "Deployed": "#198038",
    }
    cs = [colors[cat] for cat in colors.keys()]

    for column, c in zip(df_plot, cs):
        plt.barh(y, df_plot[column] - left, color=c, left=left, align="edge", height=bar_height)
        left = df_plot[column]

    # Calculate final bar to make all bars the same length
    max_time = df_plot["created_container (s)"].max()
    left = df_plot["created_container (s)"]
    diff = [max_time - l for l in left]
    plt.barh(y, diff, color=cs[-1], left=left, align="edge", height=bar_height)

    # Set plot details
    ax1.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.grid(True)

    # Set y axis details
    ax1.set_ylabel("Pods")
    ax1.set_ylim(0, len(y))

    # Set x axis details
    ax1.set_xlabel("Time (s)")
    ax1.set_xlim(0, max_time)

    # add legend
    patches = []
    for c in cs:
        patches.append(mpatches.Patch(facecolor=c, edgecolor="k"))

    texts = colors.keys()
    ax1.legend(patches, texts, loc="lower right", fontsize="16")

    # Save plot
    t = time.strftime("%Y-%m-%d_%H:%M:%S", time.gmtime())
    plt.savefig("./logs/%s_breakdown_intern.pdf" % (t), bbox_inches="tight")


def plot_p56(df):
    """Plot controlplane data from the source code

    Phases:
    1: Start Pod
        - Starts:   C_start_pod     -> 0500
        - Ends:     C_volume_mount  -> 0504
    2. Volume mount
        - Ends:     C_apply_sandbox -> 0511
    3. Create Sandbox
        - Ends:     C_start_cont    -> 0521
    4. Start container
        - Ends:     C_pod_done      -> 0515 Pod is done
    5. Start application
        - Ends:     created_container (s)

    TODO
    - TIME FETCH IMAGE
    - IGNORE START POD PART
    - IGNORE START APPLICATION, JUST END WHEN KUBE SAYS END

    Args:
        df (DataFrame): Pandas dataframe object with parsed timestamps per category
    """
    plt.rcParams.update({"font.size": 20})
    _, ax1 = plt.subplots(figsize=(12, 4))

    bar_height = 1.1

    df_plot = df.copy(deep=True)
    df_plot = df_plot[
        [
            "P5_scheduled_pod (s)",
            "P5_started_pod (s)",
            "P5_mounted_volume (s)",
            "P5_applied_sandbox (s)",
            "P6_started_container (s)",
            "created_container (s)",
        ]
    ]

    df_plot.rename(
        columns={
            "created_container (s)": "P6_started_app (s)",
        },
        inplace=True,
    )
    df_plot = df_plot.sort_values(by=["P6_started_app (s)"])

    y = [*range(len(df_plot["P5_started_pod (s)"]))]

    left = [0 for _ in range(len(y))]

    colors = {
        "EMPTY": "#ffffff",
        "P5-1": "#6929c4",
        "P5-2": "#1192e8",
        "P5-3": "#005d5d",
        "P6-1": "#9f1853",
        "P6-2": "#fa4d56",
        "Deployed": "#ffffff",
    }
    cs = [colors[cat] for cat in colors.keys()]

    for column, c in zip(df_plot, cs):
        plt.barh(y, df_plot[column] - left, color=c, left=left, align="edge", height=bar_height)
        left = df_plot[column]

    # Calculate final bar to make all bars the same length
    max_time = df_plot["P6_started_app (s)"].max()
    left = df_plot["P6_started_app (s)"]
    diff = [max_time - l for l in left]
    plt.barh(y, diff, color=cs[-1], left=left, align="edge", height=bar_height)

    # Set plot details
    ax1.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.grid(True)

    # Set y axis details
    ax1.set_ylabel("Pods")
    ax1.set_ylim(0, len(y))

    # Set x axis details
    ax1.set_xlabel("Time (s)")
    ax1.set_xlim(0, max_time)

    # add legend
    patches = []
    for c in cs[1:-1]:
        patches.append(mpatches.Patch(facecolor=c, edgecolor="k"))

    colors.pop("EMPTY")
    colors.pop("Deployed")
    texts = colors.keys()
    ax1.legend(patches, texts, loc="lower right", fontsize="16")

    # Save plot
    t = time.strftime("%Y-%m-%d_%H:%M:%S", time.gmtime())
    plt.savefig("./logs/%s_breakdown_intern_P56.pdf" % (t), bbox_inches="tight")
