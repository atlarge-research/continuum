"""Measure resource usage in a Kubernetes cluster"""

import argparse
import logging
import sys
import subprocess
import time


def enable_logging(verbose):
    """Enable logging -> only used for debugging this script"""
    # Set parameters
    new_level = logging.INFO
    if verbose:
        new_level = logging.DEBUG

    new_format = "[%(asctime)s %(filename)20s:%(lineno)4s - %(funcName)25s() ] %(message)s"
    logging.basicConfig(format=new_format, level=new_level, datefmt="%Y-%m-%d %H:%M:%S")
    logging.debug("Logging has been enabled")


def execute(command, shell=False):
    """Execute a process using the subprocess library

    Args:
        command (list(str) or str): Command to be executed.
        shell (bool). Optional. Execute subprocess via shell. Defaults to False.
        crash (bool). Optional. Crash on error. Defaults to True

    Returns:
        (Popen): Subprocess Popen object of running process
    """
    if isinstance(command, str):
        logging.debug(command)
    else:
        logging.debug(" ".join(command))

    try:
        # pylint: disable-next=consider-using-with
        process = subprocess.Popen(
            command, shell=shell, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
    except Exception as _:
        sys.exit()

    return process


def get_output(process):
    """Wait for a process to complete and return its stdout and stderr

    Args:
        process (Popen): Subprocess Popen object of running process

    Returns:
        (list(str)): Return stdout of this process without custom [CONTINUUM] prints
    """
    output = [line.decode("utf-8") for line in process.stdout.readlines()]
    error = [line.decode("utf-8") for line in process.stderr.readlines()]

    if not output:
        logging.error("stdout is empty, stderr: %s", " ".join(error))
        sys.exit()
    elif error and not all("[CONTINUUM]" in l for l in error):
        logging.error("stderr is not empty: %s", " ".join(error))
        sys.exit()

    # Filter custom prints out of stdout
    # And remove empty spaces
    out = []
    for line in output:
        if "[CONTINUUM]" not in line:
            l = line.split(" ")
            l = [word for word in l if word != ""]
            out.append(l)

    return out


def main(args):
    """Main function

    Args:
        args (Namespace): Argparse object
    """
    # Measure total resource usage
    command_nodes = ["kubectl", "top", "nodes", "--no-headers=True"]

    # Measure resource usage per pod
    command_pods = ["kubectl", "top", "pods", "--no-headers=True", "-n", "kube-system"]

    # Execute the commands every interval and write to file
    with open("resource_usage.csv", "w", encoding="utf-8") as f:
        # Execute top nodes first to discover how many nodes there are
        # And add a CPU and memory column for each node
        process = execute(command_nodes)
        output = get_output(process)

        columns = ["timestamp"]
        for line in output:
            nodename = line[0]
            columns.append(nodename + "_cpu")
            columns.append(nodename + "_memory")

        # Now add entries for control plane components
        # Assume that only 1 copy of each control plane component is running
        components = ["etcd", "apiserver", "controller-manager", "scheduler"]
        for component in components:
            columns.append(component + "_cpu")
            columns.append(component + "_memory")

        # Write header to file
        logging.debug("Columns: %s", ", ".join(columns))
        f.write(",".join(columns) + "\n")
        f.flush()

        # Now start the main loop and gather the data every args.interval seconds
        while True:
            logging.debug("-------------------------")
            logging.debug("Start iteration")
            start_time = time.time_ns()

            # ALways write a timestamp first
            to_write = [str(start_time)]

            # Get info on nodes
            # Get the cpu usage (line[1]) and memory usage (line[3]) per node
            process1 = execute(command_nodes)
            process2 = execute(command_pods)
            output = get_output(process1)

            for line in output:
                # Example header and line (header is not printed in our command)
                # NAME                      CPU(cores)   CPU%   MEMORY(bytes)   MEMORY%
                # cloud0matthijs            54m          0%     588Mi           1%
                if line[1][-1] != "m":
                    logging.error("Expected CPU to be measured in m, was: %s", line[1])
                    sys.exit()

                to_write.append(line[1][:-1])

                if "Mi" in line[3]:
                    to_write.append(line[3][:-2])
                elif "Gi" in line[3]:
                    to_write.append(str(float(line[3][:-2]) * 1000))
                else:
                    logging.error("Expected Mi or Gi as unit for memory, was: %s", line[3])
                    sys.exit()

            # Now get info on pods
            output = get_output(process2)

            for line in output:
                # We don't want info on all components, just on a few
                if not any(c in line[0] for c in components):
                    continue

                # Example header and line (header is not printed in our command)
                # NAME                                              CPU(cores)   MEMORY(bytes)
                # etcd-cloudcontrollermatthijs                      33m          38Mi
                if line[1][-1] != "m":
                    logging.error("Expected CPU to be measured in m, was: %s", line[1])
                    sys.exit()

                to_write.append(line[1][:-1])

                if "Mi" in line[2]:
                    to_write.append(line[2][:-2])
                elif "Gi" in line[3]:
                    to_write.append(str(float(line[2][:-2]) * 1000))
                else:
                    logging.error("Expected Mi or Gi as unit for memory, was: %s", line[3])
                    sys.exit()

            # Write all data from this iteration to file at once
            line = ",".join(to_write)
            logging.debug("Write line: %s", line)
            if len(columns) != len(to_write):
                logging.error(
                    "This line does not contain the expected %i columns: %s", len(columns), line
                )
                sys.exit()

            f.write(line + "\n")
            f.flush()

            # Wait until the next iteration
            interval = float(time.time_ns() - start_time) / 10**9
            if interval < args.interval:
                # Wait until next frame should happen
                time.sleep(interval)
            else:
                logging.debug(
                    "[WARNING] Can't keep up with interval %f: Spent %f seconds instead",
                    args.interval,
                    interval,
                )


if __name__ == "__main__":
    # Get input arguments and parse them
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="store_true", help="increase verbosity level")
    parser.add_argument(
        "-i",
        "--interval",
        type=float,
        default=0.5,
        help="Interval in seconds to measure resource usage",
    )
    arguments = parser.parse_args()

    enable_logging(arguments.verbose)
    main(arguments)
