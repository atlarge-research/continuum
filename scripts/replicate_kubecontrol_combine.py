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

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

import replicate_paper


class MicroBenchmark(replicate_paper.Experiment):
    """Experiment:
    Kubernetes control plane benchmark
    See /continuum/configuration/<qemu/gcp>/experiment_control/README.md for more info

    If --resume is not used, the script will run all experiments
    If --resume is defined, we will use the csv's from those files, and only plot
    """

    def __init__(self, args):
        replicate_paper.Experiment.__init__(self, None)

        self.sort = args.sort

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
                {
                    "title": "Weak Scaling",
                    "paths": [
                        "nodes/node_1",
                        "nodes/node_2",
                        "nodes/node_4",
                        "nodes/node_8",
                        "nodes/node_16",
                    ],
                    "xmax": None,
                    "ymax": None,
                    "xinter": None,
                    "yinter": None,
                },
                {
                    "title": "Strong Scaling",
                    "paths": [
                        "constant_total_pods/node_1",
                        "constant_total_pods/node_2",
                        "constant_total_pods/node_4",
                        "constant_total_pods/node_8",
                        "constant_total_pods/node_16",
                    ],
                    "xmax": 28,
                    "ymax": None,
                    "xinter": 4,
                    "yinter": None,
                },
                {
                    "title": "Deployment Method",
                    "paths": [
                        "deployment/call_100",
                        "deployment/file_100",
                        "constant_total_pods/node_1",
                        "deployment/container_100",
                    ],
                    "xmax": 28,
                    "ymax": None,
                    "xinter": 4,
                    "yinter": None,
                },
            ]

    def __repr__(self):
        """Returns this string when called as print(object)"""
        out = []
        for experiment in self.experiments:
            l = ["%s: %s" % (k, v) for k, v in experiment.items()]
            out.append(" | ".join(l))

        return "EXPERIMENTS:\n%s" % ("\n".join(out))

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
            runs = []
            for path in experiment["paths"]:
                cfg = self._find_file(path, is_cfg=True)

                # We don't need to check log file, only csv file
                # csv file is created at the end of a run, log at the start
                # So if csv exists, log exists -> and we only need the csv file
                csv = self._find_file(path, is_csv=True)

                if csv == "":
                    print("ERROR NO CSV FOUND")
                    sys.exit()

                # File does exist, only run plot code
                logging.info("To plot: %s", cfg)
                run = {
                    "file": csv,
                    "destination": os.path.dirname(csv),
                }
                runs.append(run)

                # Check for custom plot values
                for i in ["xmax", "ymax", "xinter", "yinter"]:
                    if i in experiment:
                        run[i] = experiment[i]
                    else:
                        run[i] = None

            run = {
                "title": experiment["title"],
                "xmax": experiment["xmax"],
                "ymax": experiment["ymax"],
                "xinter": experiment["xinter"],
                "yinter": experiment["yinter"],
                "data": runs,
            }

            self.plots.append(run)

    def check_resume(self):
        """Not required"""

    def parse_output(self):
        """Not required"""

    def plot(self):
        """Run plotting code for those experiments that already existed"""
        timestamp = time.strftime("%Y-%m-%d_%H:%M:%S", time.gmtime())
        for p in self.plots:
            if p["title"] == "Strong Scaling":
                self._plot_strong(p, timestamp)
            elif p["title"] == "Weak Scaling":
                self._plot_weak(p, timestamp)
            elif p["title"] == "Deployment Method":
                self._plot_deploy(p, timestamp)
            else:
                print("[ERROR] COULD NOT PLOT TITLE %s" % (p["title"]))

    def _plot_strong(self, plot, timestamp):
        logging.info("Plot: %s", plot["title"])

        df_plot = None
        for i, d in enumerate(plot["data"]):
            df = pd.read_csv(d["file"])
            if self.sort:
                # Full sort every category individually
                df = df.transform(np.sort)

            if df_plot is None:
                df_plot = pd.DataFrame(columns=df.columns)

            df_plot.loc[i] = df.iloc[-1]

        df_plot = df_plot.drop("pod", axis=1)
        df_plot = df_plot.drop("container", axis=1)
        print(df_plot)

        # ---------------------------------------------------
        plt.rcParams.update({"font.size": 20})
        fig, ax1 = plt.subplots(figsize=(12, 4))

        bar_height = 0.8

        df_plot = df_plot[
            [
                "controller_read_workload (s)",
                "controller_unpacked_workload (s)",
                "scheduler_read_pod (s)",
                "kubelet_pod_received (s)",
                "kubelet_applied_sandbox (s)",
                "started_application (s)",
            ]
        ]
        y = [*range(len(df_plot["started_application (s)"]))]

        left = [0 for _ in range(len(y))]

        colors = {
            "S1: CWO": "#6929c4",
            "S2: UWO": "#1192e8",
            "S3: CPO": "#005d5d",
            "S4: SP": "#9f1853",
            "S5: CP": "#fa4d56",
            "S6: CC": "#570408",
            "Deployed": "#198038",
        }
        cs = list(colors.values())

        for column, c in zip(df_plot, cs):
            plt.barh(
                y, df_plot[column] - left, color=c, left=left, align="center", height=bar_height
            )
            left = df_plot[column]

        # Calculate final bar to make all bars the same length
        max_time = df_plot["started_application (s)"].max()
        if plot["xmax"] is not None and plot["xmax"] != max_time:
            # Or fill to some custom xmax
            max_time = plot["xmax"]
        elif plot["xmax"] is None and max_time < 1.0:
            # xmax should be at least 1.0
            max_time = 1.0

        left = df_plot["started_application (s)"]
        diff = [max_time - l for l in left]
        plt.barh(y, diff, color=cs[-1], left=left, align="center", height=bar_height)

        # Set plot details
        # ax1.yaxis.set_major_locator(MaxNLocator(integer=True))
        ax1.xaxis.set_major_locator(MaxNLocator(integer=True))
        ax1.grid(axis="x")

        # Set y axis details
        ax1.set_ylabel("Nodes")
        y_max = len(y)
        if plot["ymax"]:
            y_max = plot["ymax"]

        ax1.set_ylim(-0.5, y_max - 0.5)

        # Set x axis details
        ax1.set_xlabel("Time (s)")
        x_max = max(1.0, max_time)
        if plot["xmax"]:
            x_max = plot["xmax"]

        ax1.set_xlim(0, x_max)

        # Set x/y ticks if argument passed
        if plot["xinter"]:
            ax1.set_xticks(np.arange(0, x_max + 0.1, plot["xinter"]))
        if plot["yinter"]:
            ax1.set_yticks(np.arange(0, y_max + 0.1, plot["yinter"]))

        ax1.set_yticks(np.arange(0, y_max, 1.0))
        ax1.set_yticklabels(["1", "2", "4", "8", "16"])

        # add legend
        patches = []
        for c in cs:
            patches.append(mpatches.Patch(facecolor=c, edgecolor="k"))

        texts = colors.keys()
        ax1.legend(patches, texts, loc="lower right", fontsize="16")

        # Save plot
        plt.savefig("./logs/%s_strong.pdf" % (timestamp), bbox_inches="tight")
        plt.close(fig)

    def _plot_weak(self, plot, timestamp):
        logging.info("Plot: %s", plot["title"])

        df_plot = None
        for i, d in enumerate(plot["data"]):
            df = pd.read_csv(d["file"])
            if self.sort:
                # Full sort every category individually
                df = df.transform(np.sort)

            if df_plot is None:
                df_plot = pd.DataFrame(columns=df.columns)

            df_plot.loc[i] = df.iloc[-1]

        df_plot = df_plot.drop("pod", axis=1)
        df_plot = df_plot.drop("container", axis=1)
        print(df_plot)

        # ---------------------------------------------------
        plt.rcParams.update({"font.size": 20})
        fig, ax1 = plt.subplots(figsize=(12, 4))

        bar_height = 0.8

        df_plot = df_plot[
            [
                "controller_read_workload (s)",
                "controller_unpacked_workload (s)",
                "scheduler_read_pod (s)",
                "kubelet_pod_received (s)",
                "kubelet_applied_sandbox (s)",
                "started_application (s)",
            ]
        ]
        y = [*range(len(df_plot["started_application (s)"]))]

        left = [0 for _ in range(len(y))]

        colors = {
            "S1: CWO": "#6929c4",
            "S2: UWO": "#1192e8",
            "S3: CPO": "#005d5d",
            "S4: SP": "#9f1853",
            "S5: CP": "#fa4d56",
            "S6: CC": "#570408",
            "Deployed": "#198038",
        }
        cs = list(colors.values())

        for column, c in zip(df_plot, cs):
            plt.barh(
                y, df_plot[column] - left, color=c, left=left, align="center", height=bar_height
            )
            left = df_plot[column]

        # Calculate final bar to make all bars the same length
        max_time = df_plot["started_application (s)"].max()
        if plot["xmax"] is not None and plot["xmax"] != max_time:
            # Or fill to some custom xmax
            max_time = plot["xmax"]
        elif plot["xmax"] is None and max_time < 1.0:
            # xmax should be at least 1.0
            max_time = 1.0

        left = df_plot["started_application (s)"]
        diff = [max_time - l for l in left]
        plt.barh(y, diff, color=cs[-1], left=left, align="center", height=bar_height)

        # Set plot details
        # ax1.yaxis.set_major_locator(MaxNLocator(integer=True))
        ax1.xaxis.set_major_locator(MaxNLocator(integer=True))
        ax1.grid(axis="x")

        # Set y axis details
        ax1.set_ylabel("Nodes")
        y_max = len(y)
        if plot["ymax"]:
            y_max = plot["ymax"]

        ax1.set_ylim(-0.5, y_max - 0.5)

        # Set x axis details
        ax1.set_xlabel("Time (s)")
        x_max = max(1.0, max_time)
        if plot["xmax"]:
            x_max = plot["xmax"]

        ax1.set_xlim(0, x_max)

        # Set x/y ticks if argument passed
        if plot["xinter"]:
            ax1.set_xticks(np.arange(0, x_max + 0.1, plot["xinter"]))
        if plot["yinter"]:
            ax1.set_yticks(np.arange(0, y_max + 0.1, plot["yinter"]))

        ax1.set_yticks(np.arange(0, y_max, 1.0))
        ax1.set_yticklabels(["1", "2", "4", "8", "16"])

        # add legend
        patches = []
        for c in cs:
            patches.append(mpatches.Patch(facecolor=c, edgecolor="k"))

        texts = colors.keys()
        ax1.legend(patches, texts, loc="lower right", fontsize="16")

        # Save plot
        plt.savefig("./logs/%s_weak.pdf" % (timestamp), bbox_inches="tight")
        plt.close(fig)

    def _plot_deploy(self, plot, timestamp):
        logging.info("Plot: %s", plot["title"])

        df_plot = None
        for i, d in enumerate(plot["data"]):
            df = pd.read_csv(d["file"])
            if self.sort:
                # Full sort every category individually
                df = df.transform(np.sort)

            if df_plot is None:
                df_plot = pd.DataFrame(columns=df.columns)

            df_plot.loc[i] = df.iloc[-1]

        df_plot = df_plot.drop("pod", axis=1)
        df_plot = df_plot.drop("container", axis=1)
        print(df_plot)

        # ---------------------------------------------------
        plt.rcParams.update({"font.size": 20})
        fig, ax1 = plt.subplots(figsize=(12, 4))

        bar_height = 0.8

        df_plot = df_plot[
            [
                "controller_read_workload (s)",
                "controller_unpacked_workload (s)",
                "scheduler_read_pod (s)",
                "kubelet_pod_received (s)",
                "kubelet_applied_sandbox (s)",
                "started_application (s)",
            ]
        ]
        y = [*range(len(df_plot["started_application (s)"]))]

        left = [0 for _ in range(len(y))]

        colors = {
            "S1: CWO": "#6929c4",
            "S2: UWO": "#1192e8",
            "S3: CPO": "#005d5d",
            "S4: SP": "#9f1853",
            "S5: CP": "#fa4d56",
            "S6: CC": "#570408",
            "Deployed": "#198038",
        }
        cs = list(colors.values())

        for column, c in zip(df_plot, cs):
            plt.barh(
                y, df_plot[column] - left, color=c, left=left, align="center", height=bar_height
            )
            left = df_plot[column]

        # Calculate final bar to make all bars the same length
        max_time = df_plot["started_application (s)"].max()
        if plot["xmax"] is not None and plot["xmax"] != max_time:
            # Or fill to some custom xmax
            max_time = plot["xmax"]
        elif plot["xmax"] is None and max_time < 1.0:
            # xmax should be at least 1.0
            max_time = 1.0

        left = df_plot["started_application (s)"]
        diff = [max_time - l for l in left]
        plt.barh(y, diff, color=cs[-1], left=left, align="center", height=bar_height)

        # Set plot details
        # ax1.yaxis.set_major_locator(MaxNLocator(integer=True))
        ax1.xaxis.set_major_locator(MaxNLocator(integer=True))
        ax1.grid(axis="x")

        # Set y axis details
        y_max = len(y)
        if plot["ymax"]:
            y_max = plot["ymax"]

        ax1.set_ylim(-0.5, y_max - 0.5)

        # Set x axis details
        ax1.set_xlabel("Time (s)")
        x_max = max(1.0, max_time)
        if plot["xmax"]:
            x_max = plot["xmax"]

        ax1.set_xlim(0, x_max)

        # Set x/y ticks if argument passed
        if plot["xinter"]:
            ax1.set_xticks(np.arange(0, x_max + 0.1, plot["xinter"]))
        if plot["yinter"]:
            ax1.set_yticks(np.arange(0, y_max + 0.1, plot["yinter"]))

        ax1.set_yticks(np.arange(0, y_max, 1.0))
        ax1.set_yticklabels(["call", "job", "pod", "container"])

        # # add legend
        patches = []
        for c in cs:
            patches.append(mpatches.Patch(facecolor=c, edgecolor="k"))

        texts = colors.keys()
        ax1.legend(patches, texts, loc="lower right", fontsize="16")

        # Save plot
        plt.savefig("./logs/%s_deployment.pdf" % (timestamp), bbox_inches="tight")
        plt.close(fig)

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
    exp.plot()


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
            "gcp",
        ],
        help="Infrastructure to deploy on",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="increase verbosity level")
    parser.add_argument("-s", "--sort", action="store_true", help="Sort all phases")

    arguments = parser.parse_args()

    replicate_paper.enable_logging(arguments.verbose)

    if arguments.infrastructure == "gcp":
        logging.info("Infrastructure == gcp. Make sure to add your GCP info to the config files.")
        logging.info("This can be automated using continuum/configuration/gcp_update.py")

    main(arguments)
