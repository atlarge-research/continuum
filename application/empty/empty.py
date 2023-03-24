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
    settings = [["sleep_time", int, lambda x: x >= 1, True, False]]
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
        "scheduler_queue": None,  # Time to schedule
        "container_create": None,  # Time to create container
        "container_created": None,  # Time to created container
        "app_start": None,  # Time to app in container
    }

    worker_metrics = []
    for _ in range(len(worker_description)):
        worker_metrics.append(copy.deepcopy(worker_set))

    command_start = []
    command_end = []
    sshs = []

    # Parse output and build new commands to get final data with
    for i, out in enumerate(worker_description):
        container_id = 0
        nodename = 0
        pod_name = ""

        for line in out:
            if "name: empty-" in line:
                pod_name = line.split("name: ")[1]
            if "nodeName" in line:
                nodename = line.split("nodeName: ")[1]
            elif "containerID" in line:
                container_id = line.split("://")[1]
                break

        if container_id == 0 or nodename == 0:
            logging.error("Could not find containerID for pod or scheduled node")
            sys.exit()

        # Get output from the worker node using journalctl, to get millisecond timing
        command = """sudo journalctl -u containerd -o short-precise | \
grep \'%s'""" % (
            pod_name
        )
        command_start.append(command)

        command = """sudo journalctl -u containerd -o short-precise | \
grep \'StartContainer for \\\\\"%s\\\\\" returns successfully'""" % (
            container_id
        )
        command_end.append(command)

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
    results_start = machines[0].process(
        config, command_start, shell=True, ssh=sshs, retryonoutput=True
    )
    results_end = machines[0].process(config, command_end, shell=True, ssh=sshs, retryonoutput=True)

    # Parse the final output to get the total execution time
    for j, (command, result) in enumerate(
        zip([command_start, command_end], [results_start, results_end])
    ):
        for i, (com, (output, error)) in enumerate(zip(command, result)):
            if not output:
                logging.error("No output for pod %i and command [%s]", i, com)
                sys.exit()
            if ("StartContainer" in output[0] and len(output) > 1) or (
                "RunPodSandbox" in output[0] and len(output) > 2
            ):
                logging.error(
                    "Incorrect output for pod %i and command [%s]: %s", i, com, "".join(output)
                )
                sys.exit()
            elif error and not all("[CONTINUUM]" in l for l in error):
                logging.error("Error for pod %i and command [%s]: %s", i, com, "".join(error))
                sys.exit()

            # Now parse the line to datetime with milliseconds
            dt = output[0].split('time="')[1].split("+")[0]
            dt = dt.replace("T", " ")
            dt = dt[:-3]
            dt = datetime.strptime(dt, "%Y-%m-%d %H:%M:%S.%f")
            end_time = datetime.timestamp(dt)

            if j == 0:
                # Start time
                worker_metrics[i]["container_create"] = end_time - starttime
            else:
                # End time
                worker_metrics[i]["container_created"] = end_time - starttime

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
            fill_control(control, starttime, worker_metrics, worker_output)
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
    ax1.stackplot(times, results, colors=cs)

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
    ax1.legend(patches, texts, loc="lower left")

    # Save plot
    t = time.strftime("%Y-%m-%d_%H:%M:%S", time.gmtime())
    plt.savefig("./logs/%s_breakdown.pdf" % (t), bbox_inches="tight")


def fill_control(control, starttime, worker_metrics, worker_output):
    """Gather all data/timestamps on control plane activities
    1. Kubectl apply                  -> starttime
    2. Scheduling queue               -> 0124
    3. Container creation             ->
    4. Container created              ->
    5. Code is running in container   -> kubectl logs <pod>

    Args:
        control (list(str), optional): Parsed output from control plane components
        starttime (datetime, optional): Invocation time of kubectl apply command
        worker_metrics (list(dict)): Metrics per worker node
        worker_output (list(list(str))): Output of each container ran on the edge
    """
    # Scheduler time
    i = 0
    for node, output in control.items():
        if "controller" in node:
            for component, out in output.items():
                if component == "scheduler":
                    for t, line in out:
                        if "0124" in line:
                            worker_metrics[i]["scheduler_queue"] = t - starttime
                            i += 1

    # Container creation
    for i, output in enumerate(worker_output):
        for line in output:
            if "Start the application" in line:
                dt = line.split("+")[0]
                dt = dt.replace("T", " ")
                dt = dt[:-3]
                dt = datetime.strptime(dt, "%Y-%m-%d %H:%M:%S.%f")
                end_time = datetime.timestamp(dt)

                worker_metrics[i]["app_start"] = end_time - starttime


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
            "scheduler_queue": "scheduler_queue (s)",
            "container_create": "container_create (s)",
            "container_created": "container_created (s)",
            "app_start": "app_start (s)",
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
    scheduler = [w["scheduler_queue"] for w in worker_metrics]
    create = [w["container_create"] for w in worker_metrics]
    app_start = [w["app_start"] for w in worker_metrics]

    events = []
    events += [(t, "scheduler") for t in scheduler]
    events += [(t, "container") for t in create]
    events += [(t, "app") for t in app_start]
    events.sort()

    # Phases:
    # 1. Arriving   [starttime, scheduler_queue]
    # 2. Scheduler  [scheduler_queue, container_create]
    # 3. Container  [container_create, app_start]
    # 4. Running    [app_start, >]
    current = [len(scheduler), 0, 0, 0]
    results = [current.copy()]
    times = [0.0]
    for t, etype in events:
        times.append(t)
        if etype == "scheduler":
            current[0] -= 1
            current[1] += 1
            results.append(current.copy())
        elif etype == "container":
            current[1] -= 1
            current[2] += 1
            results.append(current.copy())
        elif etype == "app":
            current[2] -= 1
            current[3] += 1
            results.append(current.copy())

    results2 = [[], [], [], []]
    for result in results:
        for i, val in enumerate(result):
            results2[i].append(val)

    categories = ["Arriving", "Scheduling", "ContainerCreating", "Running"]
    colors = {
        "Arriving": "#cc0000",
        "Scheduling": "#ffb624",
        "ContainerCreating": "#ebeb00",
        "Running": "#50c878",
    }

    cs = [colors[cat] for cat in categories]
    ax1.stackplot(times, results2, colors=cs)

    ax1.grid(True)

    # Set y axis details
    ax1.set_ylabel("Pods")
    ax1.set_ylim(0, len(scheduler))

    # Set x axis details
    ax1.set_xlabel("Time (s)")
    ax1.set_xlim(0, times[-1])

    # add legend
    patches = [mpatches.Patch(color=c) for c in cs]
    texts = categories
    ax1.legend(patches, texts, loc="lower left")

    # Save plot
    t = time.strftime("%Y-%m-%d_%H:%M:%S", time.gmtime())
    plt.savefig("./logs/%s_breakdown_intern.pdf" % (t), bbox_inches="tight")
