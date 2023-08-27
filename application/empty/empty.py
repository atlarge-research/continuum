"""Manage the empty application"""

import logging
import sys
import copy

from datetime import datetime

import pandas as pd

from . import plot


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
        plot.plot_status(status, config["timestamp"])

        if control is not None:
            worker_metrics = fill_control(
                config, control, starttime, worker_output, worker_description
            )
            df = print_control(config, worker_metrics)
            validate_data(df)
            plot.plot_control(df, config["timestamp"])
            plot.plot_p56(df, config["timestamp"])


def create_control_object(worker_description, mapping):
    """Create the data object to store our final parsed data in.
    Make one entry for each pod-container combination.
    Mainly used for filtering pod and container names per entry

    Args:
        worker_description (list(list(str))): Extensive description of each container
        mapping (list(list(str))): Mapping of components with custom prints to tags for analysis
    """
    worker_metrics = []
    worker_set = {
        "pod": None,  # Name of the pod for which these metrics are captured
        "container": None,  # Name of the container in the pod
    }

    for _, _, name in mapping:
        worker_set[name] = None

    container_ids = []

    # Set pod and container object per metric set
    for out in worker_description:
        container_name = ""
        pod_name = ""
        next_name = False

        for line in out:
            if " name: empty-" in line and pod_name == "":
                # Only take the first mention - this is the pod name
                # All following mentions are container names
                # The space at the start in the if statement string is important
                pod_name = line.split("name: ")[1]
            if "- containerID: " in line and container_name == "":
                # Save containerIDs to guarantee that we take unique containers
                # Do this only if we haven't selected a container yet
                container_id = line.split("://")[1]
                if container_id not in container_ids:
                    container_ids.append(container_id)
                    next_name = True
            if "name: " in line and next_name:
                # For containers, take the first "name: " field after the containerID line
                container_name = line.split("name: ")[1]
                next_name = False

        if container_name == "":
            logging.error("ERROR: container_id could not be be set")
            sys.exit()
        elif pod_name == "":
            logging.error("ERROR: pod_name could not be be set")
            sys.exit()

        w_set = copy.deepcopy(worker_set)
        w_set["pod"] = pod_name
        w_set["container"] = container_name
        worker_metrics.append(w_set)

    return worker_metrics


def check(
    config,
    control,
    starttime,
    worker_metrics,
    component,
    sub_string,
    tag,
):
    """Parse [timestamp, line (0400 job=X)] pairs to datastructures for plotting

    Args:
        config (dict): Parsed configuration
        control (list(str), optional): Parsed output from control plane components
        starttime (datetime, optional): Invocation time of kubectl apply command
        worker_metrics (list(dict)): Metrics per worker node
        component (str): Kubernetes component in which logs we look
        sub_string (str): String to check for in each line of component's logs
        tag (str): Dict key to save the found logs under
    """
    logging.debug(
        "Parsing output for component [%s], with tag [%s] and filter: %s",
        component,
        tag,
        sub_string,
    )
    controlplane_node = "controller"
    if config["infrastructure"]["provider"] == "gcp":
        controlplane_node = "cloud0"

    # Only the kubelet component is on worker nodes, all other components are in the controlplane
    is_controlplane = True
    if component == "kubelet":
        is_controlplane = False

    i = 0

    # Investigate either the control plane node or all worker nodes
    for node, output in control.items():
        if (controlplane_node in node and is_controlplane) or (
            controlplane_node not in node and not is_controlplane
        ):
            # Get output from a specific component you want to filter
            if component not in output:
                logging.error("ERROR: component %s not a valid key", component)
                sys.exit()

            out = output[component]

            # Filter output for tag first
            out_filtered = []
            for t, line in out:
                if sub_string in line:
                    out_filtered.append([t, line])

            logging.debug("----------------------")
            logging.debug(out_filtered)
            logging.debug("----------------------")

            # Now parse the lines
            for t, line in out_filtered:
                if i == len(worker_metrics):
                    logging.debug("WARNING: i == number of deployed pods. Skip")
                    continue

                if "pod=" in line and "container=" in line:
                    # Match pod and container
                    strip = line.strip().split("pod=")[1]
                    if "default/" in strip:
                        strip = strip.split("default/")[1]

                    strip = strip.split(" container=")
                    pod = strip[0]
                    container = strip[1]

                    for metric in worker_metrics:
                        if (
                            metric["pod"] == pod
                            and metric["container"] == container
                            and metric[tag] is None
                        ):
                            metric[tag] = time_delta(t, starttime)
                            i += 1
                elif "pod=" in line:
                    # Add to correct pod
                    pod = line.strip().split("pod=")[1]
                    if "default/" in pod:
                        pod = pod.split("default/")[1]

                    for metric in worker_metrics:
                        # Note: logs are already sorted by time, so only just the first entry
                        #       This applies to all metric[tag] is None in this function
                        if metric["pod"] == pod and metric[tag] is None:
                            metric[tag] = time_delta(t, starttime)
                            i += 1
                elif "container=" in line:
                    # Add to correct container
                    container = line.strip().split("container=default/")[1]
                    for metric in worker_metrics:
                        if metric["container"] == container and metric[tag] is None:
                            metric[tag] = time_delta(t, starttime)
                            i += 1
                elif "job=" in line:
                    # Filter on job
                    # These job prints only have "empty-5", while pod name is "empty-5-asdfa"
                    # Therefore, we manually add a "-" here to filter correctly,
                    # otherwise "empty-1" will be in "empty-10" which should not happen
                    if "default/" in line:
                        # For prints inside Kubernetes' control plane
                        job = line.strip().split("job=default/")[1] + "-"
                    else:
                        # For prints in kubectl
                        job = line.strip().split("job=")[1] + "-"

                    if "0277" in line and config["benchmark"]["kube_deployment"] == "pod":
                        # If deployment mode is pod, 0277 will print job=empty but every pod
                        # is part of the empty job so we don't have any ordering.
                        # In that case, brute force the ordering by searching for the number
                        # closest to the next timestamp, 5_scheduler_start
                        # We swapped insertion so 5_scheduler_start is already inserted
                        timestamp = time_delta(t, starttime)

                        # Sort based on 5_scheduler_start so we can insert at the first value
                        # bigger than 4_pod_object_create which doesn't have a value yet
                        sorted_worker_metrics = sorted(
                            worker_metrics, key=lambda x: x["5_scheduler_start"]
                        )

                        # Now insert given the criteria above
                        # Is this 100% correct? No. Is it accurate enough? Yes.
                        insertion_time = 100000.0
                        for s in sorted_worker_metrics:
                            if s[tag] is None and timestamp < s["5_scheduler_start"]:
                                insertion_time = s["5_scheduler_start"]
                                break

                        if insertion_time == 100000.0:
                            logging.error("ERROR: didn't find an entry to insert a 0277 print into")
                            sys.exit()

                        # Now insert in the real list given by searching for our timestamp
                        for metric in worker_metrics:
                            if metric["5_scheduler_start"] == insertion_time:
                                metric[tag] = timestamp
                                i += 1
                                break
                    else:
                        # Normal insertion according to job match
                        for metric in worker_metrics:
                            if job in metric["pod"] and metric[tag] is None:
                                metric[tag] = time_delta(t, starttime)
                                i += 1

    # Fill up if there are multiple containers per pod
    if i < len(worker_metrics):
        logging.debug("Fill up from %i to %i", i, len(worker_metrics))

    j = i - 1
    while i < len(worker_metrics):
        worker_metrics[i][tag] = worker_metrics[j][tag]
        i += 1


def fill_control(config, control, starttime, worker_output, worker_description):
    """Gather all data/timestamps on control plane activities

    Args:
        config (dict): Parsed configuration
        control (list(str), optional): Parsed output from control plane components
        starttime (datetime, optional): Invocation time of kubectl apply command
        worker_output (list(list(str))): Output of each container ran on the edge
        worker_description (list(list(str))): Extensive description of each container
    """
    logging.info("Gather metrics on deployment phases")

    # Component, tag to search for, name
    mapping = [
        ["kubectl", "0400", "1_kubectl_start"],  # Start of kubectl command
        ["kubectl", "0401", "2_kubectl_send"],  # Before kubectl sends data to apiserver
        ["controller-manager", "0028", "3_jobcontroller_start"],  # Start of job controller
        ["controller-manager", "0277", "4_pod_object_create"],  # After unpacking, per pod start
        ["scheduler", "0124", "5_scheduler_start"],  # Start of scheduler
        ["kubelet", "0500", "6_kubelet_start"],  # Start of kubelet (create pod, includes cgroups)
        ["kubelet", "0504", "7_volume_mount"],  # Start mounting volumes
        ["kubelet", "0505", "8_sandbox_start"],  # Create sandbox
        ["kubelet", "0514", "9_create_container"],  # Create containers
        ["kubelet", "0517", "10_start_container"],  # Start container
        ["kubelet", "0523", "11_container_started"],  # Container started
        [None, None, "12_app_start"],  # First print in the application
    ]

    worker_metrics = create_control_object(worker_description, mapping)

    # Swap 4 and 5 for insertion
    # See 0277 comments in check()
    tmp = mapping[3]
    mapping[3] = mapping[4]
    mapping[4] = tmp

    # Parse and insert
    for component, tag, name in mapping:
        if component is not None:
            check(config, control, starttime, worker_metrics, component, tag, name)

    # 12_app_start: First print in the application
    for pod, output in worker_output:
        for line in output:
            if "Start the application" in line:
                dt = line.split("+")[0]
                dt = dt.replace("T", " ")
                dt = dt[:-3]
                dt = datetime.strptime(dt, "%Y-%m-%d %H:%M:%S.%f")
                end_time = datetime.timestamp(dt)

                # Add timestamp to the correct entry
                # Variable pod can either be something like "empty-f4lwj" if container/pod == 1
                # If container/pod > 1, it will be "empty-f4lwj empty-1" being the pod+container
                #
                # This mapping should be 100% strictly correct because to get the output, you
                # need the correct pod/container names as well (which are used to create the
                # worker_metrics object itself)
                check_container = False
                if " " in pod:
                    check_container = True
                    line = pod.split(" ")
                    pod = line[0]
                    container = line[1]

                for i, metrics in enumerate(worker_metrics):
                    if not check_container and metrics["pod"] == pod:
                        worker_metrics[i]["12_app_start"] = time_delta(end_time, starttime)
                        # You could add a break here and in the end of the next else, but the
                        # code's logic should be robust enough so that it isn't required
                    elif (
                        check_container
                        and metrics["pod"] == pod
                        and metrics["container"] == container
                    ):
                        worker_metrics[i]["12_app_start"] = time_delta(end_time, starttime)

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

    # Rename to phases instead of events for plot
    # May need to rename specific entries for specific plots later
    df.rename(
        columns={
            "1_kubectl_start": "kubectl_start (s)",
            "2_kubectl_send": "kubectl_parsed (s)",
            "3_jobcontroller_start": "created_workload_obj (s)",
            "4_pod_object_create": "unpacked_workload_obj (s)",
            "5_scheduler_start": "created_pod_obj (s)",
            "6_kubelet_start": "scheduled_pod (s)",
            # TODO 7: maybe better "created_cgroup"
            "7_volume_mount": "created_pod (s)",
            "8_sandbox_start": "mounted_volume (s)",
            "9_create_container": "applied_sandbox (s)",
            "10_start_container": "created_container (s)",
            # TODO 11: maybe better "finished pod"
            # 11 is that the entire pod is done and all containers inside
            # It isn't container specific so 11 > 12 for the fastest containers
            "11_container_started": "started_container (s)",
            "12_app_start": "started_application (s)",
        },
        inplace=True,
    )
    df = df.sort_values(by=["started_application (s)"])

    df_no_indices = df.to_string(index=False)
    logging.info("\n%s", df_no_indices)

    # Print ouput in csv format
    logging.debug("Output in csv format\n%s", repr(df.to_csv()))

    # Save as csv file
    df.to_csv("./logs/%s_dataframe.csv" % (config["timestamp"]), index=False, encoding="utf-8")

    return df


def validate_data(df):
    """Validate that all numbers are strictly increasing

    Args:
        df (DataFrame): Pandas dataframe object with parsed timestamps per category
    """
    columns = list(df.columns)
    for i, col in enumerate(columns[2:-1]):
        first = col
        second = columns[i + 3]

        diff = df.loc[(df[first] > df[second])]
        if not diff.empty:
            logging.info("WARNING: %s < %s is not true for %i lines", first, second, len(diff))
