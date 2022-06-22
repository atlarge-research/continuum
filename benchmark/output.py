"""\
Get output from KubeEdge and Docker, and process it into readable format
"""

import sys
import logging
import copy
import numpy as np
import pandas as pd

from datetime import datetime


def get_endpoint_output(config, machines, container_names):
    """Get the output of endpoint docker containers.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
        container_names (list(list(str))): Names of docker containers launched

    Returns:
        list(list(str)): Output of each endpoint container
    """
    logging.info("Extract output from endpoint publishers")

    endpoint_output = []
    for ssh, cont_name in zip(config["endpoint_ssh"], container_names):
        logging.info("Get output from endpoint %s on VM %s" % (cont_name, ssh))

        # Alternatively, use docker logs -t container_name for detailed timestamps
        # Exampel: "2021-10-14T08:55:55.912611917Z Start connecting with the MQTT broker"
        command = ["docker", "logs", "-t", cont_name]
        output, error = machines[0].process(command, ssh=True, ssh_target=ssh)

        if error != []:
            logging.error("".join(error))
            sys.exit()
        elif output == []:
            logging.error("Container %s output empty" % (cont_name))
            sys.exit()

        output = [line.rstrip() for line in output]
        endpoint_output.append(output)

    return endpoint_output


def get_worker_output(config, machines):
    """Get the output of worker cloud / edge applications

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines

    Returns:
        list(list(str)): Output of each container ran on the cloud / edge
    """
    logging.info("Gather output from subscribers")

    # Get list of pods
    command = [
        "kubectl",
        "get",
        "pods",
        "-o=custom-columns=NAME:.metadata.name,STATUS:.status.phase",
        "--sort-by=.spec.nodeName",
    ]
    output, error = machines[0].process(
        command, ssh=True, ssh_target=config["cloud_ssh"][0]
    )

    if error != [] or output == []:
        logging.error("".join(error))
        sys.exit()

    # Get output from pods
    worker_output = []
    for line in output[1:]:
        container = line.split(" ")[0]
        command = ["kubectl", "logs", "--timestamps=true", container]
        output, error = machines[0].process(
            command, ssh=True, ssh_target=config["cloud_ssh"][0]
        )

        if error != [] or output == []:
            logging.error("".join(error))
            sys.exit()

        output = [line.rstrip() for line in output]
        worker_output.append(output)

    return worker_output


def get_worker_output_mist(config, machines, container_names):
    """Get the output of worker mist applications

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines

    Returns:
        list(list(str)): Output of each container ran as a worker in the mist
    """
    logging.info("Gather output from subscribers")

    worker_output = []
    for ssh, cont_name in zip(config["edge_ssh"], container_names):
        logging.info("Get output from mist worker %s on VM %s" % (cont_name, ssh))

        # Alternatively, use docker logs -t container_name for detailed timestamps
        # Exampel: "2021-10-14T08:55:55.912611917Z Start connecting with the MQTT broker"
        command = ["docker", "logs", "-t", cont_name]
        output, error = machines[0].process(command, ssh=True, ssh_target=ssh)

        if error != []:
            logging.error("".join(error))
            sys.exit()
        elif output == []:
            logging.error("Container %s output empty" % (cont_name))
            sys.exit()

        output = [line.rstrip() for line in output]
        worker_output.append(output)

    return worker_output


def to_datetime(s):
    """Parse a datetime string from docker logs to a Python datetime object

    Args:
        s (str): Docker datetime string

    Returns:
        datetime: Python datetime object
    """
    s = s.split(" ")[0]
    s = s.replace("T", " ")
    s = s.replace("Z", "")
    s = s[: s.find(".") + 7]
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S.%f")


def gather_worker_metrics(worker_output):
    """Gather metrics from cloud or edge workers

    Args:
        worker_output (list(list(str))): Output of each container ran on the edge

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

    for i, out in enumerate(worker_output):
        logging.info("Parse output from worker node %i" % (i))
        worker_metrics.append(copy.deepcopy(worker_set))
        worker_metrics[-1]["worker_id"] = i

        # Get network delay in ms (10**-3) and execution times
        # Sometimes, the program gets an incorrect line, then skip
        delays = []
        processing = []
        start_time = 0
        end_time = 0
        negatives = []
        for line in out:
            if start_time == 0 and "Read image and apply ML" in line:
                start_time = to_datetime(line)
            elif "Get item" in line:
                end_time = to_datetime(line)
            elif any(word in line for word in ["Latency", "Processing"]):
                try:
                    unit = line[line.find("(") + 1 : line.find(")")]
                    time = int(line.rstrip().split(":")[-1])
                except Exception as e:
                    logging.warn(
                        "Got an error while parsing line: %s. Exception: %s" % (line, e)
                    )
                    continue

                units = ["ns"]
                if time < 0:
                    negatives.append(time)
                    continue
                elif unit not in units:
                    logging.warn(
                        "Unit should be [%s], got %s" % (",".join(units), unit)
                    )
                    continue

                if unit == "ns":
                    if "Latency" in line:
                        delays.append(round(time / 10**6, 4))
                    elif "Processing" in line:
                        processing.append(round(time / 10**6, 4))

        worker_metrics[-1]["total_time"] = round(
            (end_time - start_time).total_seconds(), 2
        )

        if len(negatives) > 0:
            logging.warn("Got %i negative time values" % (len(negatives)))

        delays.sort()
        processing.sort()

        logging.info(
            "Get percentile values between %i - %i"
            % (lower_percentile * 100, upper_percentile * 100)
        )

        delays_perc = delays[
            int(len(delays) * lower_percentile) : int(len(delays) * upper_percentile)
        ]
        processing_perc = processing[
            int(len(processing) * lower_percentile) : int(
                len(processing) * upper_percentile
            )
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
        logging.info("Parse output from endpoint %s" % (container_name))
        endpoint_metrics.append(copy.deepcopy(endpoint_set))

        # Get timestamp from first and last line
        start_time = to_datetime(out[0])
        end_time = to_datetime(out[-1])

        endpoint_metrics[-1]["total_time"] = round(
            (end_time - start_time).total_seconds(), 2
        )
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
                except Exception as e:
                    logging.warn(
                        "Got an error while parsing line: %s. Exception: %s" % (line, e)
                    )
                    continue

                units = ["ns", "bytes"]
                if number < 0:
                    logging.warn("Time/Size < 0 should not be possible: %i" % (number))
                    continue
                elif unit not in units:
                    logging.warn(
                        "Unit should be one of [%s], got %s" % (",".join(units), unit)
                    )
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
            "Get percentile values between %i - %i"
            % (lower_percentile * 100, upper_percentile * 100)
        )

        processing_perc = processing[
            int(len(processing) * lower_percentile) : int(
                len(processing) * upper_percentile
            )
        ]
        latency_perc = latency[
            int(len(latency) * lower_percentile) : int(len(latency) * upper_percentile)
        ]

        endpoint_metrics[-1]["proc_avg"] = round(np.mean(processing_perc), 2)
        endpoint_metrics[-1]["latency_avg"] = round(np.mean(latency_perc), 2)
        endpoint_metrics[-1]["latency_stdev"] = round(np.std(latency_perc), 2)

        if data_size != []:
            endpoint_metrics[-1]["data_avg"] = round(np.mean(data_size), 2)

    endpoint_metrics = sorted(endpoint_metrics, key=lambda x: x["worker_id"])

    return endpoint_metrics


def gather_metrics(config, worker_output, endpoint_output, container_names):
    """Process the raw output to lists of dicts

    Args:
        config (dict): Parsed configuration
        worker_output (list(list(str))): Output of each container ran on the edge
        endpoint_output (list(list(str))): Output of each endpoint container
        container_names (list(str)): Names of docker containers launched

    Returns:
        2x list(dict): Metrics of worker nodes and endpoints
    """
    logging.debug("Print raw output from subscribers and publishers")
    if config["mode"] == "cloud" or config["mode"] == "edge":
        logging.debug("------------------------------------")
        logging.debug("%s OUTPUT" % (config["mode"].upper()))
        logging.debug("------------------------------------")
        for out in worker_output:
            for line in out:
                logging.debug(line)

            logging.debug("------------------------------------")

    logging.debug("------------------------------------")
    logging.debug("ENDPOINT OUTPUT")
    logging.debug("------------------------------------")
    for out in endpoint_output:
        for line in out:
            logging.debug(line)

        logging.debug("------------------------------------")

    worker_metrics = gather_worker_metrics(worker_output)
    endpoint_metrics = gather_endpoint_metrics(config, endpoint_output, container_names)
    return worker_metrics, endpoint_metrics


def format_output(config, worker_metrics, endpoint_metrics):
    """Format processed output to provide useful insights

    Args:
        config (dict): Parsed configuration
        sub_metrics (list(dict)): Metrics per worker node
        endpoint_metrics (list(dict)): Metrics per endpoint
    """
    df1 = None
    if config["mode"] == "cloud" or config["mode"] == "edge":
        logging.info("------------------------------------")
        logging.info("%s OUTPUT" % (config["mode"].upper()))
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
        logging.info("\n" + df1_no_indices)

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
    logging.info("\n" + df2_no_indices)

    # Print ouput in csv format
    if config["mode"] == "cloud" or config["mode"] == "edge":
        logging.debug(
            "Output in csv format\n%s\n%s" % (repr(df1.to_csv()), repr(df2.to_csv()))
        )
    else:
        logging.debug("Output in csv format\n%s" % (repr(df2.to_csv())))
