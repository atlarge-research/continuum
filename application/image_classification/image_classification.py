"""Manage the image_classification application"""

import logging
import copy
import sys
import numpy as np
import pandas as pd

from application import application


def set_container_location(config):
    """Set registry location/path of containerized applications

    Args:
        config (dict): Parsed configuration
    """
    source = "redplanet00/kubeedge-applications"
    if "execution_model" in config and config["execution_model"]["model"] == "openfaas":
        # Serverless applications
        # Has no combined - does not make sense
        config["images"] = {
            "worker": "%s:image_classification_subscriber_serverless" % (source),
            "endpoint": "%s:image_classification_publisher_serverless" % (source),
        }
    else:
        # Container applications
        config["images"] = {
            "worker": "%s:image_classification_subscriber" % (source),
            "endpoint": "%s:image_classification_publisher" % (source),
            "combined": "%s:image_classification_combined" % (source),
        }


def add_options(_config):
    """Add config options for a particular module

    Args:
        config (ConfigParser): ConfigParser object

    Returns:
        list(list()): Options to add
    """
    settings = [["frequency", int, lambda x: x >= 1, True, None]]
    return settings


def verify_options(parser, config):
    """Verify the config from the module's requirements

    Args:
        parser (ArgumentParser): Argparse object
        config (ConfigParser): ConfigParser object
    """
    if config["benchmark"]["application"] != "image_classification":
        parser.error("ERROR: Application should be image_classification")
    elif "cache_worker" in config["benchmark"] and config["benchmark"]["cache_worker"] == "True":
        parser.error("ERROR: image_classification app does not support application caching")
    elif config["benchmark"]["resource_manager"] == "kubecontrol":
        parser.error("ERROR: Application image_classification does not support kubecontrol")
    elif config["infrastructure"]["endpoint_nodes"] <= 0:
        parser.error("ERROR: Application image classification requires at least 1 endpoint")


def start_worker(config, machines):
    """Set variables needed when launching the app on workers

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines

    Returns:
        (dict): Application variables
        OR
        (list): Application variables
    """
    if config["benchmark"]["resource_manager"] == "mist":
        return start_worker_mist(config, machines)
    if config["benchmark"]["resource_manager"] == "baremetal":
        return start_worker_baremetal(config, machines)

    return start_worker_kube(config, machines)


def start_worker_kube(config, _machines):
    """Set variables needed when launching the app on workers

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines

    Returns:
        (dict): Application variables
    """
    if config["mode"] == "cloud":
        worker_apps = (config["infrastructure"]["cloud_nodes"] - 1) * config["benchmark"][
            "applications_per_worker"
        ]
    elif config["mode"] == "edge":
        worker_apps = (
            config["infrastructure"]["edge_nodes"] * config["benchmark"]["applications_per_worker"]
        )

    app_vars = {
        "container_port": 1883,
        "mqtt_logs": True,
        "endpoint_connected": int(config["infrastructure"]["endpoint_nodes"] / worker_apps),
        "cpu_threads": max(1, int(config["benchmark"]["application_worker_cpu"])),
    }
    return app_vars


def start_worker_mist(config, _machines):
    """Set variables needed when launching the app on workers with Mist

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines

    Returns:
        (list): Application variables
    """
    app_vars = [
        "MQTT_LOGS=True",
        "CPU_THREADS=%i" % (config["infrastructure"]["edge_cores"]),
        "ENDPOINT_CONNECTED=%i"
        % (
            int(config["infrastructure"]["endpoint_nodes"] / config["infrastructure"]["edge_nodes"])
        ),
    ]
    return app_vars


def start_worker_baremetal(config, _machines):
    """Set variables needed when launching the app on workers with Mist

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines

    Returns:
        (list): Application variables
    """
    app_vars = [
        "MQTT_LOCAL_IP=%s" % (config["registry"].split(":")[0]),
        "MQTT_LOGS=True",
        "CPU_THREADS=%i" % (config["infrastructure"]["cloud_cores"]),
        "ENDPOINT_CONNECTED=%i"
        % (
            int(
                config["infrastructure"]["endpoint_nodes"] / config["infrastructure"]["cloud_nodes"]
            )
        ),
    ]
    return app_vars


def gather_worker_metrics(_machines, _config, worker_output, _starttime):
    """Gather metrics from cloud or edge workers for the image_classification app

    Args:
        machines (list(Machine object)): List of machine objects representing physical machines
        config (dict): Parsed configuration
        worker_output (list(list(str))): Output of each container ran on the edge
        starttime (datetime): Time that 'kubectl apply' is called to launche the benchmark

    Returns:
        list(dict): List of parsed output for each cloud or edge worker
    """
    worker_metrics = []
    if worker_output == []:
        return worker_metrics

    worker_set = {
        "worker_id": None,  # ID of this worker
        "total_time": None,  # Total runtime for the worker
        "comm_delay_avg": None,  # Average endpoint -> worker delay
        "comm_delay_stdev": None,  # Stdev of delay
        "proc_avg": None,  # Average time to process 1 data element on worker
    }

    # Use 5th-90th percentile for average
    lower_percentile = 0.05
    upper_percentile = 0.90

    # Worker_output = [[pod_name, [output_line, ...]], ...]
    for i, out in enumerate(worker_output):
        logging.info("Parse output from worker node %i", i)
        worker_metrics.append(copy.deepcopy(worker_set))
        worker_metrics[-1]["worker_id"] = i

        # Get network delay in ms (10**-3) and execution times
        # Sometimes, the program gets an incorrect line, then skip
        delays = []
        processing = []
        start_time = 0
        end_time = 0
        negatives = []
        for line in out[1]:
            if start_time == 0 and "Read image and apply ML" in line:
                start_time = application.to_datetime(line)
            elif "Get item" in line:
                end_time = application.to_datetime(line)
            elif any(word in line for word in ["Latency", "Processing"]):
                try:
                    unit = line[line.find("(") + 1 : line.find(")")]
                    time = int(line.rstrip().split(":")[-1])
                except ValueError as e:
                    logging.warning("Got an error while parsing line: %s. Exception: %s", line, e)
                    continue

                units = ["ns"]
                if time < 0:
                    negatives.append(time)
                    continue

                if unit not in units:
                    logging.warning("Unit should be [%s], got %s", ",".join(units), unit)
                    continue

                if unit == "ns":
                    if "Latency" in line:
                        delays.append(round(time / 10**6, 4))
                    elif "Processing" in line:
                        processing.append(round(time / 10**6, 4))

        worker_metrics[-1]["total_time"] = round((end_time - start_time).total_seconds(), 2)

        if len(negatives) > 0:
            logging.warning("Got %i negative time values", len(negatives))

        delays.sort()
        processing.sort()

        logging.info(
            "Get percentile values between %i - %i", lower_percentile * 100, upper_percentile * 100
        )

        delays_perc = delays[
            int(len(delays) * lower_percentile) : int(len(delays) * upper_percentile)
        ]
        processing_perc = processing[
            int(len(processing) * lower_percentile) : int(len(processing) * upper_percentile)
        ]

        worker_metrics[-1]["comm_delay_avg"] = round(np.mean(delays_perc), 2)
        worker_metrics[-1]["comm_delay_stdev"] = round(np.std(delays_perc), 2)
        worker_metrics[-1]["proc_avg"] = round(np.mean(processing_perc), 2)

    return sorted(worker_metrics, key=lambda x: x["worker_id"])


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
                    # Sometimes a sending and receiving line get appended in the docker log
                    # We just ignore this for now - it happens very infrequently
                    if not ("Sending data" in line and "Received PUBLISH" in line):
                        logging.warning(
                            "Got an error while parsing line: %s. Exception: %s", line, e
                        )

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


def format_output(config, worker_metrics, endpoint_metrics, status=None):
    """Format processed output to provide useful insights (image_classification)

    Args:
        config (dict): Parsed configuration
        sub_metrics (list(dict)): Metrics per worker node
        endpoint_metrics (list(dict)): Metrics per endpoint
    """
    if status is not None:
        logging.error("This application does not support status reporting")
        sys.exit()

    df1 = None
    if config["mode"] == "cloud" or config["mode"] == "edge" and worker_metrics:
        logging.info("------------------------------------")
        logging.info("%s OUTPUT", config["mode"].upper())
        logging.info("------------------------------------")
        df1 = pd.DataFrame(worker_metrics)
        df1.rename(
            columns={
                "total_time": "total_time (s)",
                "comm_delay_avg": "delay_avg (ms)",
                "comm_delay_stdev": "delay_stdev (ms)",
                "proc_avg": "proc_time/data (ms)",
            },
            inplace=True,
        )
        df1_no_indices = df1.to_string(index=False)
        logging.info("\n%s", df1_no_indices)

    if config["infrastructure"]["endpoint_nodes"]:
        logging.info("------------------------------------")
        logging.info("ENDPOINT OUTPUT")
        logging.info("------------------------------------")
        if config["mode"] == "cloud" or config["mode"] == "edge":
            df2 = pd.DataFrame(endpoint_metrics)
            df2.rename(
                columns={
                    "worker_id": "connected_to",
                    "total_time": "total_time (s)",
                    "proc_avg": "preproc_time/data (ms)",
                    "data_avg": "data_size_avg (kb)",
                    "latency_avg": "latency_avg (ms)",
                    "latency_stdev": "latency_stdev (ms)",
                },
                inplace=True,
            )
        else:
            df2 = pd.DataFrame(
                endpoint_metrics,
                columns=[
                    "worker_id",
                    "total_time",
                    "proc_avg",
                    "latency_avg",
                    "latency_stdev",
                ],
            )
            df2.rename(
                columns={
                    "worker_id": "endpoint_id",
                    "total_time": "total_time (s)",
                    "proc_avg": "proc_time/data (ms)",
                    "latency_avg": "latency_avg (ms)",
                    "latency_stdev": "latency_stdev (ms)",
                },
                inplace=True,
            )

        df2_no_indices = df2.to_string(index=False)
        logging.info("\n%s", df2_no_indices)

    # Print ouput in csv format
    if config["mode"] == "cloud" or config["mode"] == "edge" and worker_metrics:
        logging.debug("Output in csv format\n%s\n%s", repr(df1.to_csv()), repr(df2.to_csv()))
    else:
        logging.debug("Output in csv format\n%s", repr(df2.to_csv()))
