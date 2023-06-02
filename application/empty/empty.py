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
            plot_control(config, worker_metrics)


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

    # Create object to start all metrics in
    worker_set = {
        "manage_job": None,  # Time to start job manager
        "pod_object": None,  # Time to create pod object
        "scheduler_queue": None,  # Time to schedule
        "pod_create": None,  # Time to create pod
        "container_create": None,  # Time to create container
        "container_created": None,  # Time to created container
        "app_start": None,  # Time to app in container
    }

    worker_metrics = []
    for _ in range(len(worker_description)):
        worker_metrics.append(copy.deepcopy(worker_set))

    controlplane_node = "controller"
    if config["infrastructure"]["provider"] == "gcp":
        controlplane_node = "cloud0"

    # Start job manager
    i = 0
    for node, output in control.items():
        if controlplane_node in node:
            for component, out in output.items():
                if component == "controller-manager":
                    for t, line in out:
                        if "0028" in line:
                            worker_metrics[i]["manage_job"] = time_delta(t, starttime)
                            i += 1

                            if config["benchmark"]["kube_deployment"] in ["container", "pod"]:
                                break

    if config["benchmark"]["kube_deployment"] in ["container", "pod"]:
        # Here, there only is 1 worker object
        # Therefore, phase 1 is the same for all pods/containers
        manage_job = worker_metrics[0]["manage_job"]
        for metrics in worker_metrics:
            metrics["manage_job"] = manage_job

    # Pod object creation time
    i = 0
    for node, output in control.items():
        if controlplane_node in node:
            for component, out in output.items():
                if component == "controller-manager":
                    for t, line in out:
                        if "0277" in line:
                            if i > len(worker_metrics):
                                logging.debug("WARNING: i > number of deployed pods. Skip")
                                continue

                            worker_metrics[i]["pod_object"] = time_delta(t, starttime)
                            i += 1

    # Fill up if there are multiple containers per pod
    j = i - 1
    while i < len(worker_metrics):
        worker_metrics[i]["pod_object"] = worker_metrics[j]["pod_object"]
        i += 1

    # Scheduler time
    i = 0
    for node, output in control.items():
        if controlplane_node in node:
            for component, out in output.items():
                if component == "scheduler":
                    for t, line in out:
                        if "0124" in line:
                            worker_metrics[i]["scheduler_queue"] = time_delta(t, starttime)
                            i += 1

    # Fill up if there are multiple containers per pod
    j = i - 1
    while i < len(worker_metrics):
        worker_metrics[i]["scheduler_queue"] = worker_metrics[j]["scheduler_queue"]
        i += 1

    # Container creation
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
    i = 0
    for node, output in control.items():
        if controlplane_node not in node:
            for component, out in output.items():
                if component == "kubelet":
                    for t, line in out:
                        if "0330" in line:
                            worker_metrics[i]["pod_create"] = time_delta(t, starttime)
                            i += 1

    # Fill up if there are multiple containers per pod
    j = i - 1
    while i < len(worker_metrics):
        worker_metrics[i]["pod_create"] = worker_metrics[j]["pod_create"]
        i += 1

    # Container creation
    i = 0
    for node, output in control.items():
        if controlplane_node not in node:
            for component, out in output.items():
                if component == "containerd":
                    for t, line in out:
                        if "RunPodSandbox returns" in line:
                            worker_metrics[i]["container_create"] = time_delta(t, starttime)
                            i += 1

    # Fill up if there are multiple containers per pod
    j = i - 1
    while i < len(worker_metrics):
        worker_metrics[i]["container_create"] = worker_metrics[j]["container_create"]
        i += 1

    # Container created
    i = 0
    for node, output in control.items():
        if controlplane_node not in node:
            for component, out in output.items():
                if component == "containerd":
                    for t, line in out:
                        if "StartContainer returns" in line:
                            worker_metrics[i]["container_created"] = time_delta(t, starttime)
                            i += 1

    # Fill up if there are multiple containers per pod
    j = i - 1
    while i < len(worker_metrics):
        worker_metrics[i]["container_created"] = worker_metrics[j]["container_created"]
        i += 1

    return worker_metrics


def plot_control(config, worker_metrics):
    """Plot controlplane data from the source code

    Args:
        config (dict): Parsed configuration
        worker_metrics (list(dict)): Metrics per worker node
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
        },
        inplace=True,
    )

    for col in df:
        df[col] = df[col].sort_values(ignore_index=True)

    df_no_indices = df.to_string(index=False)
    logging.info("\n%s", df_no_indices)

    # Print ouput in csv format
    logging.debug("Output in csv format\n%s", repr(df.to_csv()))

    # ----------------------------------------------------------------------------
    # Plot
    _, ax1 = plt.subplots(figsize=(12, 6))

    # Re-format data
    manage = [w["manage_job"] for w in worker_metrics]
    pobject = [w["pod_object"] for w in worker_metrics]
    scheduler = [w["scheduler_queue"] for w in worker_metrics]
    pod_create = [w["pod_create"] for w in worker_metrics]
    cont_create = [w["container_create"] for w in worker_metrics]
    app_start = [w["app_start"] for w in worker_metrics]

    events = []
    events += [(t, "manager") for t in manage]
    events += [(t, "object") for t in pobject]
    events += [(t, "scheduler") for t in scheduler]
    events += [(t, "pod_create") for t in pod_create]
    events += [(t, "container_create") for t in cont_create]
    events += [(t, "app") for t in app_start]
    events.sort()

    # Phases:
    # 1: Create workload        [starttime, manage_job]
    #   - Starts when the user executes KubeCTL
    #       - Times in Continuum
    #   - Ends when the resource controller (e.g., job controller)
    #     receives the workload resource object
    #       - Source code 0028
    #   - In between, the APIserver creates the workload resource object in the datastore
    #     and the appropiate resource controller notices that resource has been created
    #
    # 2: Unpack workload        [manage_job, pod_object]
    #   - Ends right before a pod is created for a particular workload instance
    #       - Source code 0277
    #   - In between, workload-wide stuff is checked like permissions, and the object is
    #     unpacked into workload instances if parallelism is used. Each instance is
    #     treated seperately from here on.
    #
    # 3: Pod object creation    [pod_object, scheduler_queue]
    #   - Ends right before pod is added to the scheduling queue
    #       - Source code 0124
    #   - In between, a pod is created for a workload instance, is written to the datastore
    #     via the APIserver, which the scheduler notices and adds to its scheduling queue
    #
    # 4: Scheduling             [scheduler_queue, pod_create]
    #   - Ends when the container runtime on a worker starts creating resources for this pod
    #   - In between, the pod is added to the scheduling queue, the scheduler attempts to
    #     and eventually successfully schedules the pod onto a worker node, and writes
    #     the status update back to the datastore via the APIserver
    #
    # 5: Pod creation           [pod_create, container_create]
    #   - Ends when containers inside the pod are starting to be created
    #   - In between, the kubelet notices a pod object in the datastore has been assigned to
    #     the worker node of that kubelet, and calls various OS-level software packages and
    #     the container runtime to create a pod abstraction, including process+network namespaces
    #
    # 6: Container creation     [container_create, app_start]
    #   - Ends when the application in the container prints output
    #   - In between, all containers inside the pod are being created, the pod and containers are
    #     being started and the code inside the container starts executing
    #
    # 7: Application run        [app_start, >]
    #   - Application code inside the container is running

    colors = {
        "Create Workload Object": "#33a02c",
        "Unpack Workload Object": "#b2df8a",
        "Create Pod Object": "#1f78b4",
        "Schedule Pod": "#a6cee3",
        "Create Pod": "#33a02c",
        "Create Container": "#b2df8a",
        "Application Runs": "#1f78b4",
    }
    cs = [colors[cat] for cat in colors.keys()]

    # Set event order
    current = [0 for _ in range(len(colors))]
    current[0] = len(scheduler)  # Every pod starts in the first phase
    results = [current.copy()]
    times = [0.0]
    for t, etype in events:
        times.append(t)
        if etype == "manager":
            current[0] -= 1
            current[1] += 1
            results.append(current.copy())
        elif etype == "object":
            current[1] -= 1
            current[2] += 1
            results.append(current.copy())
        elif etype == "scheduler":
            current[2] -= 1
            current[3] += 1
            results.append(current.copy())
        elif etype == "pod_create":
            current[3] -= 1
            current[4] += 1
            results.append(current.copy())
        elif etype == "container_create":
            current[4] -= 1
            current[5] += 1
            results.append(current.copy())
        elif etype == "app":
            current[5] -= 1
            current[6] += 1
            results.append(current.copy())

    # Transpose - this is the right format
    results2 = [[] for _ in range(len(colors))]
    for result in results:
        for i, val in enumerate(result):
            results2[i].append(val)

    # Now invert
    results2 = list(reversed(results2))

    # And plot
    stacks = ax1.stackplot(times, results2, colors=list(reversed(cs)), step="post")

    hatch = "."
    for stack in stacks[3:]:
        stack.set_hatch(hatch)

    ax1.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.invert_yaxis()
    ax1.grid(True)

    # Set y axis details
    ax1.set_ylabel("Pods")
    ax1.set_ylim(0, len(scheduler))

    # Set x axis details
    ax1.set_xlabel("Time (s)")
    ax1.set_xlim(0, times[-1])

    # add legend
    patches = []
    for i, c in enumerate(cs):
        if i < 3:
            patches.append(mpatches.Patch(facecolor=c, edgecolor="k", hatch=hatch * 3))
        else:
            patches.append(mpatches.Patch(facecolor=c, edgecolor="k"))

    texts = colors.keys()
    ax1.legend(patches, texts, loc="lower right")

    # Save plot
    t = time.strftime("%Y-%m-%d_%H:%M:%S", time.gmtime())
    plt.savefig("./logs/%s_breakdown_intern.pdf" % (t), bbox_inches="tight")
