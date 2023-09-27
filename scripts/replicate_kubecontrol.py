"""\
Benchmarks for kubecontrol
1) Run all benchmarks from scratch using the continuum framework
2) Given existing logs, only run the plot code
"""

import argparse
import sys
import logging
import os
import time

import pandas as pd
import numpy as np

sys.path.append("../application/empty")
import replicate_paper  # pylint: disable=wrong-import-position
import plot  # pylint: disable=wrong-import-position,import-error


class MicroBenchmark(replicate_paper.Experiment):
    """Experiment:
    Kubernetes control plane benchmark
    See /continuum/configuration/<qemu/gcp>/experiment_control/README.md for more info

    If --resume is not used, the script will run all experiments
    If --resume is defined, we will use the csv's from those files, and only plot
    """

    def __init__(self, args):
        replicate_paper.Experiment.__init__(self, None)

        self.do_plot = args.plot
        self.sort = args.sort

        self.remove_base = args.remove_base

        # All nodes used locally - used to kill all VMs to preven IP clashing
        self.nodes = ["node1", "node3", "node4"]
        self.username = "matthijs"
        self.infrastructure = args.infrastructure

        # Save all files that only need re-plotting here
        self.plots = []

        self.cfg_path = (
            "configuration/experiment_control/" + args.experiment + "/" + args.infrastructure + "/"
        )

        self.log_path = "logs/" + args.experiment + "/" + args.infrastructure + "/"

        # Feel free to comment out whatever you don't want to test
        self.experiments = []
        if args.experiment == "microbenchmark":
            # This ordering to start with all local nodes -> forces consistent images
            self.experiments = [
                # {"path": "nodes/node_4"},
                # {"path": "nodes/node_2"},
                # {"path": "nodes/node_1"},
                # {"path": "constant_total_pods/node_1"},
                # {"path": "constant_total_pods/node_2"},
                # {"path": "constant_total_pods/node_4"},
                # {"path": "constant_total_pods/node_8"},
                # {"path": "deployment/call_1", "xmax": 1.0, "xinter": 0.2},
                {"path": "deployment/call_100", "xmax": 28, "xinter": 4},
                # {"path": "deployment/container_1"},
                # {"path": "deployment/container_100"},
                # {"path": "deployment/file_1"},
                # {"path": "deployment/file_100"},
                # {"path": "pods_per_node/pod_1"},
                # {"path": "pods_per_node/pod_10"},
                # {"path": "pods_per_node/pod_100"},
            ]

            # GCP has more infrastructure so bigger configurations
            if args.infrastructure == "gcp":
                # If something goes wrong after all executions, only 2 VMs from pod_100 are
                # running, not the 16 from node_16. This saves money if this script is running
                # in the night and we can't stop the VMs by hand.
                self.experiments = [
                    # {"path": "constant_total_pods/node_16"},
                    # {"path": "nodes/node_8"},
                    # {"path": "nodes/node_16"},
                ] + self.experiments

    def __repr__(self):
        """Returns this string when called as print(object)"""
        out = []
        for experiment in self.experiments:
            l = ["%s: %s" % (k, v) for k, v in experiment.items()]
            out.append(" | ".join(l))

        return "EXPERIMENTS:\n%s" % ("\n".join(out))

    def _kill_all(self):
        if self.infrastructure == "qemu":
            for node in self.nodes:
                try:
                    comm = (
                        r"virsh list --all | grep -o -E \"(\w*_%s)\" | \
xargs -I %% sh -c \"virsh destroy %%\""
                        % (self.username)
                    )
                    command = "ssh %s -t 'bash -l -c \"%s\"'" % (node, comm)
                    replicate_paper.execute(command, shell=True, crash=False)
                except Exception as e:
                    logging.error("[ERROR] Could not virsh destroy with %s", e)
                    sys.exit()

    def _remove_base(self):
        """Just to be safe, remove all base images before starting.
        Especially on multi-physical-node runs, there may be consistency problems otherwise."""
        if self.infrastructure == "qemu":
            for node in self.nodes:
                try:
                    comm = r"rm -rf /mnt/sdc/%s/.continuum" % (self.username)
                    command = "ssh %s -t 'bash -l -c \"%s\"'" % (node, comm)
                    replicate_paper.execute(command, shell=True, crash=False)
                except Exception as e:
                    logging.error("[ERROR] Could not remove base images with %s", e)
                    sys.exit()

    def run_commands(self):
        """Execute all generated commands
        ADDED HERE SO YOU CAN CALL _KILL_ALL"""
        if self.remove_base:
            self._remove_base()

        for run in self.runs:
            if run["command"] == []:
                continue

            # Skip runs where we got output with --resume
            if run["output"] is not None:
                logging.info("Skip command: %s", " ".join(run["command"]))
                continue

            self._kill_all()

            output, error = replicate_paper.execute(run["command"])

            logging.debug("------------------------------------")
            logging.debug("OUTPUT")
            logging.debug("------------------------------------")
            logging.debug("\n%s", "".join(output))

            if error:
                logging.debug("------------------------------------")
                logging.debug("ERROR")
                logging.debug("------------------------------------")
                logging.debug("\n%s", "".join(error))
                sys.exit()

            logging.debug("------------------------------------")

            # Get output from log file
            logpath = output[0].rstrip().split("and file ")[-1]
            with open(logpath, "r", encoding="utf-8") as f:
                output = f.readlines()
                run["output"] = output
                f.close()

    def _find_file(self, path, is_cfg=False, is_log=False, is_csv=False, resource=0):
        """Find a file with a .cfg / .log / .csv extention for an experiment
        If found, return the file

        Args:
            path (str): Path to a log or cfg file
            is_cfg (bool, optional): Append .cfg. Defaults to False.
            is_log (bool, optional): Append .log. Defaults to False.
            is_csv (bool, optional): Append .csv. Defaults to False.
            resource (int, optional): Find resource .csv. Default to 0.
                0 = find *dataframe.csv
                1 = find *resources.csv
                2 = find *resources_os.csv

        Returns:
            str: Path with .cfg or .log appended
        """
        if sum(x is True for x in [is_cfg, is_log, is_csv]) != 1:
            logging.error("[ERROR] Exactly one of is_cfg / is_log / is_csv needs to be true")
            sys.exit()

        if is_cfg:
            # CFG = pods_per_node/pod_10
            # Should be pods_per_node/pod_10.cfg
            # So path = pods_per_node
            # Slightly different from .log and .csv
            file_to_check = os.path.basename(path) + ".cfg"
            path = self.cfg_path + os.path.dirname(path)
        else:
            file_to_check = ""
            path = self.log_path + path

        if not os.path.exists(path):
            if is_cfg:
                # Config should alreay exist
                logging.error("[ERROR] Directory %s does not exist", path)
                sys.exit()

            # Create directory for log / csv, and return empty because file doesn't exist
            os.makedirs(path)
            return ""

        # Find file with specific extention
        files_of_interest = []
        for file in os.listdir(path):
            if file.endswith(".cfg") and is_cfg:
                files_of_interest.append(file)
            elif file.endswith(".log") and is_log:
                files_of_interest.append(file)
            elif file.endswith(".csv") and is_csv:
                if not resource and "resources" not in file:
                    files_of_interest.append(file)
                elif resource == 1 and "resources.csv" in file:
                    files_of_interest.append(file)
                elif resource == 2 and "resources_os.csv" in file:
                    files_of_interest.append(file)

        if not files_of_interest:
            if is_cfg:
                # The cfg file should just exist
                # We can't run benchmarks on something that doens't exist
                logging.error("[ERROR] The cfg file %s did not exist", file_to_check)
                sys.exit()

            # If not file with that extention was found, return an empty string
            # This means we need to do a new run for this entry
            return ""

        # If cfg, check if the specific file you were looking for was found
        if file_to_check != "":
            if file_to_check in files_of_interest:
                files_of_interest = [file_to_check]
            else:
                logging.error(
                    "[ERROR] Was searching for %s, found %s instead",
                    file_to_check,
                    files_of_interest,
                )
                sys.exit()

        # Should only find 1 file
        if len(files_of_interest) > 1:
            logging.error(
                "[ERROR] Should have found only one file, but found: %s",
                ",".join(files_of_interest),
            )
            sys.exit()

        # If a file was found, return the file
        return path + "/" + files_of_interest[0]

    def generate(self):
        """Create commands to execute the continuum framework
        For each experiment, check if the dir where we expect the log file to be already exists

        If so: check if there is a log file
            If so: only re-plot using the csv
            If not: re-run the experiment + move the file to that dir
        If not: re-run the experiment + make dir and move files to that dir
        """
        for experiment in self.experiments:
            # Check if cfg exists
            cfg = self._find_file(experiment["path"], is_cfg=True)

            # We don't need to check log file, only csv file
            # csv file is created at the end of a run, log at the start
            # So if csv exists, log exists -> and we only need the csv file
            csv = self._find_file(experiment["path"], is_csv=True)
            csv_resource = self._find_file(experiment["path"], is_csv=True, resource=1)
            csv_resource_os = self._find_file(experiment["path"], is_csv=True, resource=2)

            if csv == "":
                # File does not exist, run entire framework
                logging.info("To run: %s", cfg)
                command = ["python3", "continuum.py", cfg]
                run = {
                    "command": command,
                    "output": None,
                }
                self.runs.append(run)
            elif self.do_plot:
                # File does exist, only run plot code
                logging.info("To plot: %s", cfg)
                run = {
                    "file": csv,
                    "resource": csv_resource,
                    "resource_os": csv_resource_os,
                    "destination": os.path.dirname(csv),
                }

                # Check for custom plot values
                for i in ["xmax", "ymax", "xinter", "yinter"]:
                    if i in experiment:
                        run[i] = experiment[i]
                    else:
                        run[i] = None

                self.plots.append(run)

    def check_resume(self):
        """Not required"""

    def parse_output(self):
        """Not required"""

    def plot(self):
        """Run plotting code for those experiments that already existed"""
        for p in self.plots:
            logging.info("Plot: %s", p["file"])
            timestamp = time.strftime("%Y-%m-%d_%H:%M:%S", time.gmtime())

            df = pd.read_csv(p["file"])
            if self.sort:
                # Full sort every category individually
                df = df.transform(np.sort)

            plot.plot_control(
                df,
                timestamp,
                xmax=p["xmax"],
                ymax=p["ymax"],
                xinter=p["xinter"],
                yinter=p["yinter"],
            )
            plot.plot_p56(
                df,
                timestamp,
                xmax=p["xmax"],
                ymax=p["ymax"],
                xinter=p["xinter"],
                yinter=p["yinter"],
            )

            # Now plot resources
            df1 = pd.read_csv(p["resource"])
            df2 = pd.read_csv(p["resource_os"])
            plot.plot_resources(
                [df1, df2],
                timestamp,
                xmax=p["xmax"],
                ymax=p["ymax"],
                xinter=p["xinter"],
                yinter=p["yinter"],
            )

            # Now move PDF back to the correct folder
            command = "mv logs/%s* %s" % (timestamp, p["destination"])
            replicate_paper.execute(command, shell=True)

    def print_result(self):
        """Not required"""


def main(args):
    """Main function

    Args:
        args (Namespace): Argparse object
    """
    if args.experiment == "microbenchmark":
        logging.info("Experiment: microbenchmark")
        exp = MicroBenchmark(args)
    else:
        logging.error("Invalid experiment: %s", args.experiment)
        sys.exit()

    logging.info(exp)
    exp.generate()
    exp.check_resume()
    exp.run_commands()

    command = ["terraform", "-chdir=/home/matthijs/.continuum/images", "destroy", "--auto-approve"]
    replicate_paper.execute(command)

    exp.parse_output()
    exp.plot()
    exp.print_result()


if __name__ == "__main__":
    # Get input arguments and parse them
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "experiment",
        choices=[
            "microbenchmark",
        ],
        help="Experiment to replicate",
    )
    parser.add_argument(
        "infrastructure",
        choices=[
            "qemu",
            "gcp",
        ],
        help="Infrastructure to deploy on",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="increase verbosity level")
    parser.add_argument(
        "-p", "--plot", action="store_true", help="Create new plots for existing data"
    )
    parser.add_argument("-s", "--sort", action="store_true", help="Sort all phases")
    parser.add_argument("-r", "--remove_base", action="store_true", help="Remove all base images")

    arguments = parser.parse_args()

    replicate_paper.enable_logging(arguments.verbose)

    if arguments.infrastructure == "gcp":
        logging.info("Infrastructure == gcp. Make sure to add your GCP info to the config files.")
        logging.info("This can be automated using continuum/configuration/gcp_update.py")

    main(arguments)
