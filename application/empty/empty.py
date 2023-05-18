"""Manage the empty application"""

import logging
import sys
import copy
import time

from datetime import datetime

import numpy as np
import pandas as pd

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

from application import application


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


def gather_worker_metrics(machines, config, _worker_output, worker_description, starttime):
    """Gather metrics from cloud or edge workers for the empty app

    Args:
        machines (list(Machine object)): List of machine objects representing physical machines
        config (dict): Parsed configuration
        worker_output (list(list(str))): Output of each container ran on the edge
        worker_description (list(list(str))): Extensive description of each container
        starttime (datetime): Time that 'kubectl apply' is called to launche the benchmark

    Returns:
        list(dict): List of parsed output for each cloud or edge worker
    """
    logging.info("Gather metrics with start time: %s", str(starttime))

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

    command_ccreate = []
    command_ccreated = []
    command_pcreate = []
    sshs = []

    # TODO: This breaks when you have multiple multi-container pods
    #       That requires you to reset this var to 0 once you reach the max containers per pod
    last_container_id_index = 0

    # Parse output and build new commands to get final data with
    for i, out in enumerate(worker_description):
        container_id_index = 0
        container_id = ""
        nodename = ""
        pod_name = ""

        for line in out:
            if "name: empty-" in line and pod_name == "":
                # Only take the first mention - this is the pod name
                # All following mentions are container names - we don't need those
                pod_name = line.split("name: ")[1]
            elif "nodeName" in line:
                nodename = line.split("nodeName: ")[1]
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
        elif nodename == "":
            logging.error("ERROR: nodename could not be be set")
            sys.exit()
        elif pod_name == "":
            logging.error("ERROR: pod_name could not be be set")
            sys.exit()

        # If kubecontrol mode = container, there is only one pod
        # Therefore, pod name doesnt have -X, e.g., -1, -2 at the end of pod name
        minus = "-"
        if config["benchmark"]["kube_deployment"] == "container":
            minus = ""

        # Get output from the worker node using journalctl, to get millisecond timing
        command = """sudo journalctl -u containerd -o short-precise | \
grep \'%s%s'""" % (
            pod_name,
            minus,
        )
        command_ccreate.append(command)

        command = """sudo journalctl -u containerd -o short-precise | \
grep \'StartContainer for \\\\\"%s\\\\\" returns successfully'""" % (
            container_id
        )
        command_ccreated.append(command)

        # Use syslog* because there may be multiple syslogs in case there is much output
        command = "sudo cat /var/log/syslog* | grep '0330 waitForVolumeAttach pod=default/%s%s'" % (
            pod_name,
            minus,
        )
        command_pcreate.append(command)

        # Place the _ back in the name
        nodename = nodename.replace(machines[0].user, "_" + machines[0].user)

        for machine in machines:
            if nodename in machine.cloud_names + machine.edge_names:
                if nodename in machine.cloud_names:
                    i = machine.cloud_names.index(nodename)
                    ip = machine.cloud_ips[i]
                elif nodename in machine.edge_names:
                    i = machine.edge_names.index(nodename)
                    ip = machine.edge_ips[i]

                ssh = "%s@%s" % (nodename, ip)
                sshs.append(ssh)
                break

    # Given the commands and the ssh address to execute it at, execute all commands
    results_ccreate = machines[0].process(
        config, command_ccreate, shell=True, ssh=sshs, retryonoutput=True
    )
    results_ccreated = machines[0].process(
        config, command_ccreated, shell=True, ssh=sshs, retryonoutput=True
    )
    results_pcreate = machines[0].process(
        config, command_pcreate, shell=True, ssh=sshs, retryonoutput=True
    )

    # Parse the final output to get the total execution time
    for j, (command, result) in enumerate(
        zip(
            [command_ccreate, command_ccreated, command_pcreate],
            [results_ccreate, results_ccreated, results_pcreate],
        )
    ):
        for i, (com, (output, error)) in enumerate(zip(command, result)):
            if not output:
                logging.error("No output for pod %i and command [%s]", i, com)
                sys.exit()

            # Only take the last line if there are multiple lines
            if len(output) > 0:
                short_output = output[-1]
            else:
                logging.error("No output for pod %i and command [%s]", i, com)

            # Check for keywords
            if (
                (j == 0 and "RunPodSandbox" not in short_output)
                or (j == 1 and "StartContainer" not in short_output)
                or (j == 2 and "waitForVolumeAttach" not in short_output)
            ):
                logging.error(
                    "Incorrect output for pod %i and command [%s]: %s", i, com, "".join(output)
                )
                sys.exit()

            # Special ignore: from j==2, cat syslog* gives some errors
            if (
                error
                and not all("[CONTINUUM]" in l for l in error)
                and not (j == 2 and all("No such file or directory" in l for l in error))
            ):
                logging.error("Error for pod %i and command [%s]: %s", i, com, "".join(error))
                sys.exit()

            if j < 2:
                # Now parse the line to datetime with milliseconds
                dt = short_output.split('time="')[1]
                dt = dt.split(" level=")[0]
                dt = dt.split("Z")[0]
                dt = dt.replace("T", " ")
                dt = dt[:-3]
                dt = datetime.strptime(dt, "%Y-%m-%d %H:%M:%S.%f")
                end_time = datetime.timestamp(dt)
            else:
                # Example: %!s(int64=1680728624591234908)
                time_str = short_output.split("=")[1]
                time_str = time_str.split(")")[0]
                time_obj_nano = float(time_str)
                end_time = time_obj_nano / 10**9

            if j == 0:
                worker_metrics[i]["container_create"] = time_delta(end_time, starttime)
            elif j == 1:
                worker_metrics[i]["container_created"] = time_delta(end_time, starttime)
            elif j == 2:
                worker_metrics[i]["pod_create"] = time_delta(end_time, starttime)

    return worker_metrics


def gather_endpoint_metrics(config, endpoint_output, container_names):
    """Gather metrics from endpoints

    Args:
        config (dict): Parsed configuration
        endpoint_output (list(list(str))): Output of each endpoint container
        container_names (list(str)): Names of docker containers launched

    Returns:
        list(dict): List of parsed output for each endpoint
    """
    endpoint_metrics = []
    endpoint_set = {
        "worker_id": None,  # To which worker is this endpoint connected
        "total_time": None,  # Total runtime of the endpoint
        "proc_avg": None,  # Average procesing time per data element
        "data_avg": None,  # Average generated data size
        "latency_avg": None,  # Average end-to-end latency
        "latency_stdev": None,  # Stdev latency
    }

    # Use 5th-90th percentile for average
    lower_percentile = 0.05
    upper_percentile = 0.90

    for out, container_name in zip(endpoint_output, container_names):
        logging.info("Parse output from endpoint %s", container_name)
        endpoint_metrics.append(copy.deepcopy(endpoint_set))

        # Get timestamp from first and last line
        start_time = application.to_datetime(out[0])
        end_time = application.to_datetime(out[-1])

        endpoint_metrics[-1]["total_time"] = round((end_time - start_time).total_seconds(), 2)
        endpoint_metrics[-1]["data_avg"] = 0.0

        if config["mode"] == "cloud":
            name = container_name.split("_")[0]
            endpoint_metrics[-1]["worker_id"] = int(name[5:])
        elif config["mode"] == "edge":
            name = container_name.split("_")[0]
            endpoint_metrics[-1]["worker_id"] = int(name[4:])
        elif config["mode"] == "endpoint":
            endpoint_metrics[-1]["worker_id"] = int(container_name[8:])

        # Parse line by line to get preparation, preprocessing and processing times
        processing = []
        latency = []
        data_size = []
        for line in out:
            if any(
                word in line
                for word in [
                    "Preparation and preprocessing",
                    "Preparation, preprocessing and processing",
                    "Sending data",
                    "Latency",
                ]
            ):
                try:
                    unit = line[line.find("(") + 1 : line.find(")")]
                    number = int(line.rstrip().split(":")[-1])
                except ValueError as e:
                    logging.warning("Got an error while parsing line: %s. Exception: %s", line, e)
                    continue

                units = ["ns", "bytes"]
                if number < 0:
                    logging.warning("Time/Size < 0 should not be possible: %i", number)
                    continue

                if unit not in units:
                    logging.warning("Unit should be one of [%s], got %s", ",".join(units), unit)
                    continue

                if "Preparation, preprocessing and processing" in line:
                    processing.append(round(number / 10**6, 4))
                elif "Preparation and preprocessing" in line:
                    processing.append(round(number / 10**6, 4))
                elif "Latency" in line:
                    latency.append(round(number / 10**6, 4))
                elif "Sending data" in line:
                    data_size.append(round(number / 10**3, 4))

        processing.sort()
        latency.sort()

        logging.info(
            "Get percentile values between %i - %i", lower_percentile * 100, upper_percentile * 100
        )

        processing_perc = processing[
            int(len(processing) * lower_percentile) : int(len(processing) * upper_percentile)
        ]
        latency_perc = latency[
            int(len(latency) * lower_percentile) : int(len(latency) * upper_percentile)
        ]

        endpoint_metrics[-1]["proc_avg"] = round(np.mean(processing_perc), 2)
        endpoint_metrics[-1]["latency_avg"] = round(np.mean(latency_perc), 2)
        endpoint_metrics[-1]["latency_stdev"] = round(np.std(latency_perc), 2)

        if data_size:
            endpoint_metrics[-1]["data_avg"] = round(np.mean(data_size), 2)

    endpoint_metrics = sorted(endpoint_metrics, key=lambda x: x["worker_id"])

    return endpoint_metrics


def format_output(
    config,
    worker_metrics,
    _endpoint_metrics,
    status=None,
    control=None,
    starttime=None,
    worker_output=None,
):
    """Format processed output to provide useful insights (empty)

    Args:
        config (dict): Parsed configuration
        worker_metrics (list(dict)): Metrics per worker node
        endpoint_metrics (list(dict)): Metrics per endpoint
        status (list(list(str)), optional): Status of started Kubernetes pods over time
        control (list(str), optional): Parsed output from control plane components
        starttime (datetime, optional): Invocation time of kubectl apply command
        worker_output (list(list(str)), optional): Output of each container ran on the edge
    """
    # Plot the status of each pod over time
    if status is not None:
        plot_status(status)

        if control is not None:
            fill_control(config, control, starttime, worker_metrics, worker_output)
            plot_control(config, worker_metrics)


def plot_status(status):
    """Print and plot controlplane data from external observations

    Args:
        status (list(list(str)), optional): Status of started Kubernetes pods over time
    """
    for stat in status:
        logging.debug(stat)

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


def fill_control(config, control, starttime, worker_metrics, worker_output):
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
        worker_metrics (list(dict)): Metrics per worker node
        worker_output (list(list(str))): Output of each container ran on the edge
    """
    logging.info("Gather metrics on deployment phases")

    controlplane_node = "controller"
    if config["infrastructure"]["provider"] == "gcp":
        controlplane_node = "cloud0"

    # Start job manager
    for node, output in control.items():
        if controlplane_node in node:
            for component, out in output.items():
                if component == "controller-manager":
                    for t, line in out:
                        if "0028" in line:
                            logging.debug("0028")
                            worker_metrics[0]["manage_job"] = time_delta(t, starttime)
                            break

    # Job manager is only called once per job - and therefore is the same for all pods
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
                            logging.debug("0277")
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
