"""Measure resource usage in a Kubernetes cluster"""

import argparse
import logging
import os
import subprocess
import sys
import time

import pandas as pd

pd.options.mode.chained_assignment = None

os.chdir("../../")
sys.path.append("./application/empty")

import plot


def enable_logging(verbose):
    """Enable logging -> only used for debugging this script"""
    # Set parameters
    new_level = logging.INFO
    if verbose:
        new_level = logging.DEBUG

    new_format = "[%(asctime)s %(filename)20s:%(lineno)4s - %(funcName)25s() ] %(message)s"
    logging.basicConfig(format=new_format, level=new_level, datefmt="%Y-%m-%d %H:%M:%S")
    logging.debug("Logging has been enabled")

    logging.getLogger("matplotlib").setLevel("WARNING")


def ansible_check_output(out):
    """Check if an Ansible Playbook succeeded or failed
    Shared by all files launching Ansible playbooks

    Args:
        output (list(str), list(str)): List of process stdout and stderr
    """
    output, error = out

    # Print summary of executioo times
    summary = False
    lines = [""]
    for line in output:
        if summary:
            lines.append(line.rstrip())

        if "==========" in line:
            summary = True

    if lines != [""]:
        logging.debug("\n".join(lines))

    # Check if executino was succesful
    if error != [] and not all("WARNING" in line for line in error):
        logging.error("".join(error))
        sys.exit()
    elif any("FAILED!" in out for out in output):
        logging.error("".join(output))
        sys.exit()


def get_output(process):
    """Wait for a process to complete and return its stdout and stderr

    Args:
        process (Popen): Subprocess Popen object of running process

    Returns:
        list(str): Stdout, line by line
    """
    output = [line.decode("utf-8") for line in process.stdout.readlines()]
    error = [line.decode("utf-8") for line in process.stderr.readlines()]

    if not output:
        logging.error("stdout is empty, stderr: %s", " ".join(error))
        sys.exit()
    elif error:
        logging.error("stderr is not empty: %s", " ".join(error))
        sys.exit()

    return output


def execute(command):
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
            command,
            shell=True,
            executable="/bin/bash",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except Exception as _:
        sys.exit()

    return process


def filter_metrics_os(args):
    """Filter the metrics gathered via OS tools

    Args:
        config (dict): Parsed configuration
        starttime (datetime): Invocation time of kubectl apply command that launches the benchmark
        endtime (datetime): Time at which the final application is deployed

    Returns:
        (dataframe): Pandas dataframe with resource utilization metrics during our benchmrak deploym
    """
    logging.debug("Filter os metric stats")
    start = args.start
    end = start + args.duration

    vms = ["cloud_controller_matthijs"]
    vms += ["cloud%i_matthijs" % (i) for i in range(0, args.workers)]

    # Gather all data from each VM first
    dfs = []
    for vm_name in vms:
        path = os.path.join(args.basepath, ".continuum/resource_usage_os-%s.csv" % (vm_name))
        df = pd.read_csv(path)
        df["timestamp"] = df["timestamp"] / 10**9

        df_filtered = df.loc[(df["timestamp"] > (start - 1.0)) & (df["timestamp"] < (end + 1.0))]
        df_filtered["timestamp"] -= start
        df_filtered.rename(
            columns={
                "timestamp": "Time (s)",
                "cpu-used (%)": "cpu-used %s" % (vm_name) + " (%)",
                "memory-used (%)": "memory-used %s" % (vm_name) + " (%)",
            },
            inplace=True,
        )

        # Save with deep copy just to be safe
        dfs.append(df_filtered.copy(deep=True))

    # Now save in one big dataframe
    df_final = pd.concat(dfs)
    return df_final


def main(args):
    """Main function

    Args:
        args (Namespace): Argparse object
    """
    # Gather OS CPU and memory metrics
    command = [
        "ansible-playbook",
        "-i",
        os.path.join(args.basepath, ".continuum/inventory_vms"),
        os.path.join(args.basepath, ".continuum/cloud/resource_usage_os_back.yml"),
    ]
    command = " ".join(command)
    process = execute(command)
    output = get_output(process)
    ansible_check_output((output, []))

    # Process the OS metrics
    df = filter_metrics_os(args)

    # Save to CSV
    logging.info("Save dataframe to CSV")
    timestamp = time.strftime("%Y-%m-%d_%H:%M:%S", time.gmtime())
    df.to_csv(
        "./logs/%s_dataframe_resources_os.csv" % (timestamp),
        index=False,
        encoding="utf-8",
    )

    # Plot
    logging.info("Create plots")
    plot.plot_resources_os(df, timestamp, args.duration, None, None, None)


if __name__ == "__main__":
    # Get input arguments and parse them
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="store_true", help="increase verbosity level")
    parser.add_argument(
        "-b",
        "--basepath",
        type=str,
        default="/mnt/sdc/matthijs",
        help="Base path of the Continuum framework",
    )
    parser.add_argument("workers", type=int, help="Number of worker nodes")
    parser.add_argument("start", type=float, help="Start timestamp of the replay script")
    parser.add_argument("duration", type=float, help="Duration of experiment in seconds")
    arguments = parser.parse_args()

    enable_logging(arguments.verbose)
    main(arguments)
