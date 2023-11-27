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
    elif error:
        logging.error("stderr is not empty: %s", " ".join(error))
        sys.exit()

    # We only expect 1 line of output
    if len(output) != 1:
        logging.error("stdout should have contained only 1 line, stdout: %s", " ".join(output))
        sys.exit()

    # The output should be a float
    try:
        percentage = float(output[0].strip())
    except Exception as _:
        logging.error("Couldn't convert expected percentage to float: %s", " ".join(output))
        sys.exit()

    return percentage


def main(args):
    """Main function

    Args:
        args (Namespace): Argparse object
    """
    command_cpu = (
        'top -bn1 | grep "Cpu(s)" | sed "s/.*, *\([0-9.]*\)%* id.*/\\1/" | awk \'{print 100 - $1}\''
    )
    command_memory = "free | grep Mem | awk '{print $3/$2 * 100.0}'"

    # Execute the commands every interval and write to file
    with open("resource_usage_os.csv", "w", encoding="utf-8") as f:
        # Write header to file
        columns = ["timestamp", "cpu-used (%)", "memory-used (%)"]
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

            # Execute both commands
            process1 = execute(command_cpu)
            process2 = execute(command_memory)

            # Get CPU usage
            cpu = get_output(process1)
            to_write.append(str(cpu))

            # Get memory usage
            memory = get_output(process2)
            to_write.append(str(memory))

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
