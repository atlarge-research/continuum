"""Create plots for the empty application"""

import logging

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator


def plot_status(status, timestamp):
    """Print and plot controlplane data from external observations

    Args:
        status (list(list(str)), optional): Status of started Kubernetes pods over time
        timestamp (time): Global timestamp used to save all files of this run
    """
    for stat in status:
        logging.debug(stat)

    # Make sure matplotlib doesn't inherit our own logging level
    logging.getLogger("matplotlib").setLevel("WARNING")

    # From: https://docs.openstack.org/developer/performance-docs/test_results/
    #           container_cluster_systems/kubernetes/density/index.html
    _, ax1 = plt.subplots(figsize=(12, 6))

    # Re-format data
    times = [s["time"] for s in status]
    arriving = [s["Arriving"] for s in status]
    pending = [s["Pending"] for s in status]
    containercreating = [s["ContainerCreating"] for s in status]
    running = [s["Running"] for s in status]
    succeeded = [s["Succeeded"] for s in status]

    categories = []
    results = []
    if sum(arriving) > 0:
        categories.append("Arriving")
        results.append(arriving)
    if sum(pending) > 0:
        categories.append("Pending")
        results.append(pending)
    if sum(containercreating) > 0:
        categories.append("ContainerCreating")
        results.append(containercreating)
    if sum(running) > 0:
        categories.append("Running")
        results.append(running)
    if sum(succeeded) > 0:
        categories.append("Succeeded")
        results.append(succeeded)

    colors = {
        "Arriving": "#cc0000",
        "Pending": "#ffb624",
        "ContainerCreating": "#ebeb00",
        "Running": "#50c878",
        "Succeeded": "#a366ff",
    }

    cs = [colors[cat] for cat in categories]
    ax1.stackplot(times, results, colors=cs, step="post")

    ax1.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.invert_yaxis()
    ax1.grid(True)

    # Set y axis details
    total_pods = sum(status[0][cat] for cat in categories)
    ax1.set_ylabel("Pods")
    ax1.set_ylim(0, total_pods)

    # Set x axis details
    ax1.set_xlabel("Time (s)")
    ax1.set_xlim(0, status[-1]["time"])

    # add legend
    patches = [mpatches.Patch(color=c) for c in cs]
    texts = categories
    ax1.legend(patches, texts, loc="upper right")

    # Save plot
    plt.savefig("./logs/%s_breakdown.pdf" % (timestamp), bbox_inches="tight")


def plot_control(df, timestamp, xmax=None, ymax=None):
    """Plot controlplane data from the source code

    Phases:
    1: Create workload        [starttime, manage_job]
      - Starts when the user executes KubeCTL
          - Times in Continuum
      - Ends when the resource controller (e.g., job controller)
        receives the workload resource object
          - Source code 0028
      - In between, the APIserver creates the workload resource object in the datastore
        and the appropiate resource controller notices that resource has been created

    2: Unpack workload        [manage_job, pod_object]
      - Ends right before a pod is created for a particular workload instance
          - Source code 0277
      - In between, workload-wide stuff is checked like permissions, and the object is
        unpacked into workload instances if parallelism is used. Each instance is
        treated seperately from here on.

    3: Pod object creation    [pod_object, scheduler_queue]
      - Ends right before pod is added to the scheduling queue
          - Source code 0124
      - In between, a pod is created for a workload instance, is written to the datastore
        via the APIserver, which the scheduler notices and adds to its scheduling queue

    4: Scheduling             [scheduler_queue, pod_create]
      - Ends when the container runtime on a worker starts creating resources for this pod
      - In between, the pod is added to the scheduling queue, the scheduler attempts to
        and eventually successfully schedules the pod onto a worker node, and writes
        the status update back to the datastore via the APIserver

    5: Pod creation           [pod_create, container_create]
      - Ends when containers inside the pod are starting to be created
      - In between, the kubelet notices a pod object in the datastore has been assigned to
        the worker node of that kubelet, and calls various OS-level software packages and
        the container runtime to create a pod abstraction, including process+network namespaces

    6: Container creation     [container_create, app_start]
      - Ends when the application in the container prints output
      - In between, all containers inside the pod are being created, the pod and containers are
        being started and the code inside the container starts executing

    7: Application run        [app_start, >]
      - Application code inside the container is running

    Args:
        df (DataFrame): Pandas dataframe object with parsed timestamps per category
        timestamp (time): Global timestamp used to save all files of this run
        xmax (bool): Optional. Set the xmax of the plot by hand. Defaults to None.
        ymax (bool): Optional. Set the ymax of the plot by hand. Defaults to None.
    """
    plt.rcParams.update({"font.size": 20})
    fig, ax1 = plt.subplots(figsize=(12, 4))

    bar_height = 1.1

    df_plot = df.copy(deep=True)
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
        "P1": "#6929c4",
        "P2": "#1192e8",
        "P3": "#005d5d",
        "P4": "#9f1853",
        "P5": "#fa4d56",
        "P6": "#570408",
        "Deployed": "#198038",
    }
    cs = list(colors.values())

    for column, c in zip(df_plot, cs):
        plt.barh(y, df_plot[column] - left, color=c, left=left, align="edge", height=bar_height)
        left = df_plot[column]

    # Calculate final bar to make all bars the same length
    max_time = df_plot["started_application (s)"].max()
    left = df_plot["started_application (s)"]
    diff = [max_time - l for l in left]
    plt.barh(y, diff, color=cs[-1], left=left, align="edge", height=bar_height)

    # Set plot details
    ax1.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.grid(True)

    # Set y axis details
    ax1.set_ylabel("Pods")
    ax1.set_ylim(0, len(y))
    if ymax:
        ax1.set_ylim(0, ymax)

    # Set x axis details
    ax1.set_xlabel("Time (s)")
    ax1.set_xlim(0, max_time)
    if xmax:
        ax1.set_xlim(0, xmax)

    # add legend
    patches = []
    for c in cs:
        patches.append(mpatches.Patch(facecolor=c, edgecolor="k"))

    texts = colors.keys()
    ax1.legend(patches, texts, loc="lower right", fontsize="16")

    # Save plot
    plt.savefig("./logs/%s_breakdown_intern.pdf" % (timestamp), bbox_inches="tight")
    plt.close(fig)


def plot_p56(df, timestamp, xmax=None, ymax=None):
    """Plot controlplane data from the source code

    Phases:
    1: Start Pod
        - Starts:   C_start_pod     -> 0500
        - Ends:     C_volume_mount  -> 0504
    2. Volume mount
        - Ends:     C_apply_sandbox -> 0511
    3. Create Sandbox
        - Ends:     C_start_cont    -> 0521
    4. Start container
        - Ends:     C_pod_done      -> 0515 Pod is done
    5. Start application
        - Ends:     created_container (s)

    Args:
        df (DataFrame): Pandas dataframe object with parsed timestamps per category
        timestamp (time): Global timestamp used to save all files of this run
        xmax (bool): Optional. Set the xmax of the plot by hand. Defaults to None.
        ymax (bool): Optional. Set the ymax of the plot by hand. Defaults to None.
    """
    plt.rcParams.update({"font.size": 20})
    fig, ax1 = plt.subplots(figsize=(12, 4))

    bar_height = 1.1

    df_plot = df.copy(deep=True)
    df_plot = df_plot[
        [
            "kubelet_pod_received (s)",
            "kubelet_created_cgroup (s)",
            "kubelet_mounted_volume (s)",
            "kubelet_applied_sandbox (s)",
            "kubelet_created_container (s)",
            "started_application (s)",
        ]
    ]

    df_plot = df_plot.sort_values(by=["started_application (s)"])

    y = [*range(len(df_plot["started_application (s)"]))]

    left = [0 for _ in range(len(y))]

    colors = {
        "EMPTY": "#ffffff",
        "P5-1": "#6929c4",
        "P5-2": "#1192e8",
        "P5-3": "#005d5d",
        "P6-1": "#9f1853",
        "P6-2": "#fa4d56",
        "Deployed": "#ffffff",
    }
    cs = list(colors.values())

    for column, c in zip(df_plot, cs):
        plt.barh(y, df_plot[column] - left, color=c, left=left, align="edge", height=bar_height)
        left = df_plot[column]

    # Calculate final bar to make all bars the same length
    max_time = df_plot["started_application (s)"].max()
    left = df_plot["started_application (s)"]
    diff = [max_time - l for l in left]
    plt.barh(y, diff, color=cs[-1], left=left, align="edge", height=bar_height)

    # Set plot details
    ax1.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.grid(True)

    # Set y axis details
    ax1.set_ylabel("Pods")
    ax1.set_ylim(0, len(y))
    if ymax:
        ax1.set_ylim(0, ymax)

    # Set x axis details
    ax1.set_xlabel("Time (s)")
    ax1.set_xlim(0, max_time)
    if xmax:
        ax1.set_xlim(0, xmax)

    # add legend
    patches = []
    for c in cs[1:-1]:
        patches.append(mpatches.Patch(facecolor=c, edgecolor="k"))

    colors.pop("EMPTY")
    colors.pop("Deployed")
    texts = colors.keys()
    ax1.legend(patches, texts, loc="lower right", fontsize="16")

    # Save plot
    plt.savefig("./logs/%s_breakdown_intern_P56.pdf" % (timestamp), bbox_inches="tight")
    plt.close(fig)
