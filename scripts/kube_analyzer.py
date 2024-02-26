"""\
Automatic analyzer tool
Assumes all log files already exist
"""

import sys
import argparse

# import pandas as pd

import replicate_kubecontrol


class Analyzer(replicate_kubecontrol.MicroBenchmark):
    """Experiment:
    Kubernetes control plane benchmark
    See /continuum/configuration/<qemu/gcp>/experiment_control/README.md for more info

    If --resume is not used, the script will run all experiments
    If --resume is defined, we will use the csv's from those files, and only plot
    """

    def __init__(self, args):
        replicate_kubecontrol.MicroBenchmark.__init__(self, args)
        self.data = []
        self.baseline = None

    def gather_csv(self):
        """Todo"""
        for experiment in self.experiments:
            csv = self._find_file(experiment["path"], is_csv=True)
            csv_resource = self._find_file(experiment["path"], is_csv=True, resource=1)
            csv_resource_os = self._find_file(experiment["path"], is_csv=True, resource=2)

            if csv == "":
                # File does not exist
                print("ERROR csv not found")
                sys.exit()

            if "nodes/" in experiment["path"]:
                nodes = int(experiment["path"].split("node_")[1])
                pods = 100 * nodes
            elif "constant_total_pods/" in experiment["path"]:
                nodes = int(experiment["path"].split("node_")[1])
                pods = 100
            elif "deployment" in experiment["path"]:
                # We will do this later
                continue
            elif "pods_per_node" in experiment["path"]:
                # This is the baseline to compare against
                if int(experiment["path"].split("pod_")[1]) == 1:
                    data = {
                        "file": csv,
                        "resource": csv_resource,
                        "resource_os": csv_resource_os,
                    }
                    self.baseline = data

            # Gather all info of each run that needs analyzing
            data = {
                "path": experiment["path"],
                "file": csv,
                "resource": csv_resource,
                "resource_os": csv_resource_os,
                "nodes": nodes,
                "pods": pods,
                "cpus": 8,
            }
            self.data.append(data)

    def _get_baseline(self):
        pass

        # df = pd.read_csv(self.baseline["file"])

        # per_job = [
        #     "kubectl_start (s)",
        #     "kubectl_parsed (s)",
        #     "api_workload_arrived (s)",
        #     "controller_read_workload (s)"
        # ]
        # per_pod = [
        #     "controller_unpacked_workload (s)",
        #     "api_pod_created (s)",
        #     "scheduler_read_pod (s)",
        #     "scheduled_pod (s)",
        #     "kubelet_pod_received (s)",
        #     "kubelet_created_cgroup (s)",
        #     "kubelet_mounted_volume (s)",
        #     "kubelet_applied_sandbox (s)"
        # ]
        # per_container = ["kubelet_created_container (s)", "started_application (s)"]

        # for i in range():
        #     entry = {}

        #     # We only do 1 job for now
        #     for cat in per_job:
        #         entry[cat] = df[cat].iloc(0)

        #     # We only do 1 container per pod for now
        #     for cat in per_pod + per_container:

        # entry = {
        #     "kubectl_start (s)":
        # }

        # new_row = {'Courses':'Hyperion', 'Fee':24000, 'Duration':'55days', 'Discount':1800}
        # df2 = df.append(new_row, ignore_index=True)

    def predict(self):
        """
        Baseline: pod-1
        - extrapolate to X pods (the one you want to compare against)
        - Dont do anything with per-job stuff
        - per-pod = per-container in our case
        - ((time for phase with 1 pod) x max_pods) / total_cores
            - gives a good approximation of expected time complexity
            - total_cores = 8 if control plane action or 8*worker_nodes for kubelet stuff

        Strong points:
        - Accurate in bottleneck detection
        - Baseline can be run once and predict best-case scenario for any scenario
            - Without needing to run anything
            - Only needs to run if you want to verify

        Weaknesses:
        - Assumes the reported time per phase = total CPU time of that phase
            - So uses 1 CPU core 100% of the duration of the phase
        - Can only find bottleneck up to the first bottleneck
            - We divide by the number of CPU cores per phase, which assumes all actions
              in a phase start at the same time. If they don't because previous phases
              have skewed execution times per pod, pods in this phase might all complete
              very fast because they're not competing for resources.
              However, that is only a problem if (i) the previous phase executed on another machine
              (the control plane, and this phase is on workers) or if the previous phase has an
              artificial bottleneck. If the previous phase ran on the same machine, and uses full
              CPU, then the current phase will compete for CPU so the division by CPU cores
              still works then.
              - Does it though? Because you compete for resources, there may be more work than cores
                available so you have to wait for your task to even start executing?
                -> It should work. Total time / CPU cores works always if everything uses 1 CPU core
                   for the full duration of its phase. There's no way around it
                -> CORRECTION. The first pod in a workload with 100 pods completes way slower than
                   the first pod in a workload with only 1 pod. THIS NEEDS TO BE TAKEN INTO ACCOUNT
                   OR WE IGNORE FIRST-POD START AND ONLY FOCUS ON TOTAL, BUT STILL

        - IDEALLY you make a cpu pipeline model
            - On a millisecond granularity
            - For every millisecond, and for every machine, inventorize which tasks are running
            - Give the first #cpus tasks 1 millisecond of CPU
            - Go 1 millisecond in the future
            - Invenotrize the list again
            - Give the next #cpus tasks 1 millisecond of CPU
            Then naturally the first started task will complete first
            BUT: How to take bottlenecks into account that don't really use CPU


        OLDER SIMPLE MODEL
        - If we predict a duration for pod=100 for a step, and the actual duration is much lower,
          this either means that (i) there is a one-off cost for the pod=1 baseline or (ii) the
          previous phase is bottlenecked and isn't using CPU efficiently.
        - that's a great conclusion for us as you can't detect this via a CPU graph, as that will
          say that total CPU usage is 90%. That may seem fine, but there still is a bottleneck

        USE THE OLD MODEL - IT SHOULD BE GOOD ENOUGH
        - the problem mentioned earlier that stuff doesn't work is incorrect. The model is only
          accurate up to the first found bottleneck. But our tool works iterative so that's fine.
          However: If in a next phase actual time >> predicted time, that still is a detected
          bottleneck. It's more that new bottlenecks will show up if you solve the current one.
        - The model can predict best-case total deployment time. Not the time of the first app
          because there suddenly is extra concurrency that wasn't in the baseline and we don't
          calculate that per-pod, only in total.
        """
        # for data in self.data:
        #     baseline = self._get_baseline(data["pods"])

        #     if data['kind'] == 'strong':

        # """Something"""


def main(args):
    """Main"""
    a = Analyzer(args)
    print(a)
    a.gather_csv()


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
    main(arguments)
