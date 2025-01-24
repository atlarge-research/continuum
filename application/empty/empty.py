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
    # -----------------------------------
    # MKB1 - use pythonbase image to run Pyhton containers, otherwise use wasmrust
    # -----------------------------------
    source = "macko99vu/wasmrust"
    # source = "macko99vu/pythonbase"
    config["images"] = {"worker": "%s:latest" % (source)}


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
        "sleep_time": 10,
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
    seconds_per_hour = 3600.0
    while delta < 0.0:
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
    resource_output=None,
    endtime=None,
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
        endtime (str, optional): Timestamp of the slowest deployed pod
    """
    # Plot the status of each pod over time
    if status is not None:
        plot.plot_status(status, config["timestamp"])

        if control is not None:
            worker_metrics = fill_control(
                config, control, starttime, worker_output, worker_description
            )
            df = print_control(config, worker_metrics, printOut=False)
            df_resources = print_resources(config, resource_output)
            validate_data(df)
            plot.plot_control(df, config["timestamp"])
            plot.plot_p56(df, config["timestamp"], width=20, height=5)
            plot.plot_p57(df, config["timestamp"], width=500, height=50)
            plot.plot_p57(df, config["timestamp"], width=20, height=5)
            plot.plot_resources(df_resources, config["timestamp"], xmax=endtime)


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


def sort_on_time(timestamp, worker_metrics, tag, compare_tag, future_compare):
    """Insert starttime in the array worker_metrics[tag], in chronological order compared
    to an already filled series of timestamps worker_metrics[compare_tag]

    Args:
        starttime (datetime, optional): Invocation time of kubectl apply command
        worker_metrics (list(dict)): Metrics per worker node
        tag (str): Dict key to save the found logs under
        compare_tag (str): Other dict key against which you should sort on time
        future_compare (bool): Compare to a dataset in the future (<) or past (>)
    """
    # Sort previous tag to find the correct order of time
    try:
        sorted_worker_metrics = sorted(worker_metrics, key=lambda x: x[compare_tag])
    except Exception as e:
        logging.error("ERROR: couldnt sort due to exception %s", str(e))
        logging.error(str(worker_metrics))
        sys.exit()

    # You can't directly insert in worker_metrics like this, so we first
    # find the timestamp to insert to in the sorted list, and then
    # find the right entry in worker_metrics to insert into
    insertion_time = 100000
    for s in sorted_worker_metrics:
        if s[tag] is None:
            if (future_compare and timestamp < s[compare_tag]) or (
                not future_compare and timestamp > s[compare_tag]
            ):
                insertion_time = s[compare_tag]
                break

            logging.warning(
                "WARNING: Expected insertion timestamp %s didn't succeed on %s to %s (future=%i)",
                str(timestamp),
                tag,
                compare_tag,
                int(future_compare),
            )

    if insertion_time == 100000:
        logging.error("ERROR: didn't find an entry to insert a %s print into", tag)
        logging.error(str(worker_metrics))
        sys.exit()

    # Now insert in the real list given by searching for our timestamp
    insert = False
    for metric in worker_metrics:
        if metric[compare_tag] == insertion_time and metric[tag] is None:
            metric[tag] = timestamp
            insert = True
            break

    if not insert:
        logging.error("ERROR: didn't find an entry to insert a %s print into", tag)
        logging.error(str(worker_metrics))
        sys.exit()


def check(
    config,
    control,
    starttime,
    worker_metrics,
    component,
    sub_string,
    tag,
    compare_tag="",
    reverse=False,
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
        compare_tag (str): Optional. When no tag exists in the output line (like 0400 job=empty-1)
                           compare against worker_metrics[compare_tag] for chronological insertion.
        reverse (bool): Optional. Reverse insertion chronological. Defaults to False
    """
    logging.debug(
        "Parsing output for component [%s], with tag [%s] and filter: %s (unto %s in reverse=%s)",
        component,
        tag,
        sub_string,
        compare_tag,
        reverse,
    )
    controlplane_node = "controller"
    if config["infrastructure"]["provider"] == "gcp":
        controlplane_node = "cloud0"

    # Only the kubelet component is on worker nodes, all other components are in the controlplane
    is_controlplane = True
    if component in ["kubelet", "crun", "containerd", "runc"]:
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

            # Now parse the lines
            for t, line in out_filtered:
                if i == len(worker_metrics):
                    logging.debug("WARNING: i == number of deployed pods. Stop processing")
                    break

                # Sort on time cases
                if component == "apiserver" or (
                    tag == "5_pod_object_create"
                    and config["benchmark"]["kube_deployment"] in ["pod", "container"]
                ):
                    # See comments in next function
                    timestamp = time_delta(t, starttime)
                    sort_on_time(timestamp, worker_metrics, tag, compare_tag, reverse)
                    i += 1
                else:
                    # The cases where a tag exists
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

                        # Normal insertion according to job match
                        for metric in worker_metrics:
                            if job in metric["pod"] and metric[tag] is None:
                                metric[tag] = time_delta(t, starttime)
                                i += 1

    if i < len(worker_metrics):
        if (component == "apiserver" or tag == "5_pod_object_create") and i == 1:
            # Only fill up the rest if there was only 1 entry and its the apiserver we're parsing
            logging.debug(
                "Parsed output for %i / %i pods. Fill up the rest.", i, len(worker_metrics)
            )

            # Fill up if there are multiple containers per pod
            if i < len(worker_metrics):
                j = i - 1
                while i < len(worker_metrics):
                    worker_metrics[i][tag] = worker_metrics[j][tag]
                    i += 1
        else:
            # In all other conditions all pods should have been parsed automatically
            # If that didn't happen, generate an error
            logging.error("ERROR: Only parsed output for %i / %i pods.", i, len(worker_metrics))
            sys.exit()


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

    # Component, tag to search for, name, sort_on_time, future_compare
    mapping = [
        # 0: Timestamp before kubectl command is invoked, in framework
        ["kubectl", "0400", "1_kubectl_start"],  # Start of kubectl command
        ["kubectl", "0401", "2_kubectl_send"],  # Before kubectl sends data to apiserver
        ["apiserver", "0200", "3_api_receive_job"],  # Receive write request for job from kubectl
        ["controller-manager", "0028", "4_jobcontroller_start"],  # Start of job controller
        ["controller-manager", "0277", "5_pod_object_create"],  # After unpacking, per pod start
        ["apiserver", "0202", "6_api_receive_pod"],  # Receive write request for pod from controller
        ["scheduler", "0124", "7_scheduler_start"],  # Start of scheduler
        ["apiserver", "0204", "8_api_receive_pod"],  # Receive write request for pod from scheduler
        ["kubelet", "0500", "9_kubelet_start"],  # Start of kubelet (create pod, includes cgroups)
        ["kubelet", "0504", "10_volume_mount"],  # Start mounting volumes
        ["kubelet", "0505", "11_sandbox_start"],  # Create sandbox
        ["kubelet", "0514", "12_create_container"],  # Create containers
        ["kubelet", "0517", "13_start_container"],  # Start container
        ["kubelet", "0502", "0502"],
        ["kubelet", "0503", "0503"],
        ["kubelet", "0506", "0506"],
        ["kubelet", "0507", "0507"],
        ["kubelet", "0508", "0508"],
        ["kubelet", "0509", "0509"],
        ["kubelet", "0510", "0510"],
        ["kubelet", "0511", "0511"],
        ["kubelet", "0512", "0512"],
        ["kubelet", "0513", "0513"],
        ["kubelet", "0515", "0515"],
        # ["kubelet", "0516", "0516"],
        ["kubelet", "0518", "0518"],
        ["kubelet", "0519", "0519"],
        ["kubelet", "0520", "0520"],
        ["kubelet", "0521", "0521"],
        ["kubelet", "0522", "0522"],
        ["kubelet", "0523", "0523"],
        ["kubelet", "0540", "0540"],
        ["kubelet", "0541", "0541"],
        ["kubelet", "0542", "0542"],
        ["kubelet", "0555", "0555"],
        ["kubelet", "0556", "0556"],
        ["kubelet", "0557", "0557"],
        ["kubelet", "0558", "0558"],
        ["kubelet", "0559", "0559"],
        ["kubelet", "0560", "0560"],

        ["kubelet", "0601", "0601"],
        ["kubelet", "0602", "0602"],
        ["kubelet", "0603", "0603"],
        ["kubelet", "0604", "0604"],
        ["kubelet", "0605", "0605"],
        ["kubelet", "0606", "0606"],

        ["kubelet", "0641", "0641"],
        ["kubelet", "0642", "0642"],
        ["kubelet", "0643", "0643"],
        ["kubelet", "0644", "0644"],
        ["kubelet", "0645", "0645"],
        ["kubelet", "0646", "0646"],
        ["kubelet", "0647", "0647"],
        ["kubelet", "0648", "0648"],

        ["kubelet", "0611", "0611"],
        ["kubelet", "0612", "0612"],
        ["kubelet", "0613", "0613"],
        ["kubelet", "0614", "0614"],

        ["kubelet", "0631", "0631"],
        ["kubelet", "0632", "0632"],
        ["kubelet", "0633", "0633"],
        ["kubelet", "0634", "0634"],    
        ["kubelet", "0635", "0635"],

        # ["kubelet", "0651", "0651"],
        # ["kubelet", "0652", "0652"],
        # ["kubelet", "0653", "0653"],
        # ["kubelet", "0654", "0654"],
        # ["kubelet", "0655", "0655"],
        # ["kubelet", "0656", "0656"],
        # ["kubelet", "0657", "0657"],
        # ["kubelet", "0658", "0658"],

        ["kubelet", "0701", "0701"],
        ["kubelet", "0702", "0702"],

        # ["crun", "0811", "0811"],
        # ["crun", "0812", "0812"],
        # ["crun", "0824", "0824"],
        # ["crun", "0828", "0828"],
        # ["crun", "0829", "0829"],
        # ["crun", "0825", "0825"],

        ["containerd", "0901", "0901"],
        ["containerd", "0902", "0902"],
        ["containerd", "0903", "0903"],
        ["containerd", "0904", "0904"],
        ["containerd", "0905", "0905"],
        ["containerd", "0906", "0906"],
        ["containerd", "0907", "0907"],
        ["containerd", "0908", "0908"],
        ["containerd", "0909", "0909"],
        ["containerd", "0912", "0912"],
        ["containerd", "0913", "0913"],
        ["containerd", "0914", "0914"],
        ["containerd", "0915", "0915"],
        ["containerd", "0916", "0916"],
        ["containerd", "0917", "0917"],
        ["containerd", "0918", "0918"],
        ["containerd", "0919", "0919"],

        ["containerd", "0920", "0920"],
        ["containerd", "0921", "0921"],
        ["containerd", "0922", "0922"],
        ["containerd", "0923", "0923"],
        ["containerd", "0924", "0924"],
        ["containerd", "0925", "0925"],
        ["containerd", "0926", "0926"],
        ["containerd", "0927", "0927"],
        ["containerd", "0928", "0928"],
        ["containerd", "0929", "0929"],
        ["containerd", "0930", "0930"],
        # ["containerd", "0931", "0931"],
        # ["containerd", "0932", "0932"],
        # ["containerd", "0933", "0933"],
        # ["containerd", "0934", "0934"],
        # ["containerd", "0935", "0935"],
        # ["containerd", "0936", "0936"],
        # ["containerd", "0937", "0937"],
        # ["containerd", "0938", "0938"],

        ["containerd", "0940", "0940"],
        ["containerd", "0941", "0941"],
        ["containerd", "0942", "0942"],
        ["containerd", "0943", "0943"],
        ["containerd", "0944", "0944"],
        ["containerd", "0945", "0945"],
        ["containerd", "0946", "0946"],
        ["containerd", "0947", "0947"],
        ["containerd", "0948", "0948"],
        ["containerd", "0949", "0949"],
        ["containerd", "0950", "0950"],

        # vurtual, copied from 40-45 why? same code is executed twice
        ["containerd", "0980", "0980"],
        ["containerd", "0981", "0981"],
        ["containerd", "0982", "0982"],
        ["containerd", "0983", "0983"],
        ["containerd", "0984", "0984"],
        ["containerd", "0985", "0985"],

        # ["containerd", "0960", "0960"],
        # ["containerd", "0961", "0961"],
        # ["containerd", "0962", "0962"],
        # ["containerd", "0963", "0963"],
        ["containerd", "0964", "0964"],
        ["containerd", "0965", "0965"],
        ["containerd", "0966", "0966"],
        ["containerd", "0967", "0967"],
        ["containerd", "0968", "0968"],
        ["containerd", "0969", "0969"],

        # vurtual, copied from 64-69 why? same code is executed twice
        ["containerd", "0994", "0994"],
        ["containerd", "0995", "0995"],
        ["containerd", "0996", "0996"],
        ["containerd", "0997", "0997"],
        ["containerd", "0998", "0998"],
        ["containerd", "0999", "0999"],

        # ["runc", "0850", "0850"],
        # ["runc", "0851", "0851"],
        # ["runc", "0852", "0852"],
        # ["runc", "0853", "0853"],
        # ["runc", "0854", "0854"],
        # ["runc", "0855", "0855"],
        # ["runc", "0856", "0856"],
        # ["runc", "0857", "0857"],
        # ["runc", "0858", "0858"],
        # ["runc", "0859", "0859"],
        # ["runc", "0860", "0860"],

        # ["containerd", "0031", "0031"],
        ["containerd", "0033", "0033"],
        ["containerd", "0034", "0034"],
        ["containerd", "0035", "0035"],
        # ["containerd", "0038", "0038"],
        # ["containerd", "0039", "0039"],
        # ["containerd", "0040", "0040"],
        # ["containerd", "0041", "0041"],

        # vurtual, copied from 33-41 why? same code is executed twice
        # ["containerd", "0043", "0043"],
        # ["containerd", "0044", "0044"],
        # ["containerd", "0045", "0045"],
        # ["containerd", "0048", "0048"],
        # ["containerd", "0049", "0049"],
        # ["containerd", "0050", "0050"],
        # ["containerd", "0051", "0051"],
    
        [None, None, "14_app_start"],  # First print in the application
    ]

    worker_metrics = create_control_object(worker_description, mapping)

    # Issue: 5_pod_object_create does not print the pod that has been created
    #        So, we only insert it after 7_scheduler_start, which does have this info
    #        And we insert it in chronological order
    #        The new order is 7 -> 6 -> 5 and reverse insertion
    #        See 0277 comments in check()
    pod_5 = mapping[4]
    mapping[4] = mapping[6]
    mapping[6] = pod_5

    # Parse and insert
    for i, (component, sub_string, tag) in enumerate(mapping):
        if component == "apiserver" or tag == "5_pod_object_create":
            compare_tag = mapping[i - 1][2]
            if i == 7:
                # 8_api_receive_pod should be shorted against 7_scheduler_start
                # But, 7_scheduler_start is now in mapping[4]
                compare_tag = mapping[4][2]

            # Reverse insertion for entry 5 and 6 because of previous issue
            reverse = False
            if i in [5, 6]:
                reverse = True

            check(
                config,
                control,
                starttime,
                worker_metrics,
                component,
                sub_string,
                tag,
                compare_tag,
                reverse,
            )
        elif component is not None:
            check(config, control, starttime, worker_metrics, component, sub_string, tag)

    # 17_app_start: First print in the application
    for pod, output in worker_output:
        for line in output:
            if "Hello, World!" in line:
                if config["infrastructure"]["provider"] == "qemu":
                    # Example: 2023-09-03T11:50:03.183541380+02:00 Hello, World!
                    dt = line.split("+")[0]
                elif config["infrastructure"]["provider"] == "gcp":
                    # Example: 2023-09-03T11:50:03.183541380Z Hello, World!
                    dt = line.split("Z")[0]

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
                        worker_metrics[i][mapping[-1][2]] = time_delta(end_time, starttime)
                        # You could add a break here and in the end of the next else, but the
                        # code's logic should be robust enough so that it isn't required
                    elif (
                        check_container
                        and metrics["pod"] == pod
                        and metrics["container"] == container
                    ):
                        worker_metrics[i][mapping[-1][2]] = time_delta(end_time, starttime)

    return worker_metrics


def print_control(config, worker_metrics, printOut=False):
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
            "3_api_receive_job": "api_workload_arrived (s)",
            "4_jobcontroller_start": "controller_read_workload (s)",
            "5_pod_object_create": "controller_unpacked_workload (s)",
            "6_api_receive_pod": "api_pod_created (s)",
            "7_scheduler_start": "scheduler_read_pod (s)",
            "8_api_receive_pod": "scheduled_pod (s)",
            "9_kubelet_start": "kubelet_pod_received (s)",
            "10_volume_mount": "kubelet_created_cgroup (s)",
            "11_sandbox_start": "kubelet_mounted_volume (s)",
            "12_create_container": "kubelet_applied_sandbox (s)",
            "13_start_container": "kubelet_created_container (s)",
            "14_app_start": "started_application (s)",
        },
        inplace=True,
    )
    df = df.sort_values(by=["started_application (s)"])

    if printOut:
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
            logging.info("[WARNING]: %s < %s is not true for %i lines", first, second, len(diff))


def print_resources(config, df):
    """Modify the resource dataframe and save it to csv

    Example:
    timestamp cloud0mkozub_cpu  cloud0mkozub_memory  cloudcontrollermkozub_cpu   ...
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
