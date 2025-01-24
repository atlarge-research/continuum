"""Create plots for the empty application"""

import logging
import math

import numpy as np

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
    # Note: If the pod is deployed in < 1 second, there is only one status entry with time = 0.0
    #       You can't set xlim to [0 - 0], so we have to set it to at least 1.0
    ax1.set_xlabel("Time (s)")
    ax1.set_xlim(0, max(status[-1]["time"], 1.0))

    # add legend
    patches = [mpatches.Patch(color=c) for c in cs]
    texts = categories
    ax1.legend(patches, texts, loc="upper right")

    # Save plot
    plt.savefig("./logs/%s_breakdown.pdf" % (timestamp), bbox_inches="tight")


def plot_control(df, timestamp, xmax=None, ymax=None, xinter=None, yinter=None):
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
            "controller_read_workload (s)", #0028
            "controller_unpacked_workload (s)", #0277
            "scheduler_read_pod (s)",   #0124
            "kubelet_pod_received (s)", #0500
            "kubelet_applied_sandbox (s)",  #0514
            "started_application (s)",
        ]
    ]
    y = [*range(len(df_plot["started_application (s)"]))]

    left = [0 for _ in range(len(y))]

    colors = {
        "S1: CWO end:0028": "#6929c4",
        "S2: UWO end:0277": "#1192e8",
        "S3: CPO end:0124": "#005d5d",
        "S4: SP end:0500": "#9f1853",
        "S5: CP end:0514": "#fa4d56",
        "S6: CC": "#570408",
        "Deployed": "#198038",
    }
    cs = list(colors.values())

    for column, c in zip(df_plot, cs):
        plt.barh(y, df_plot[column] - left, color=c, left=left, align="edge", height=bar_height)
        left = df_plot[column]

    # Calculate final bar to make all bars the same length
    max_time = df_plot["started_application (s)"].max()
    if xmax is not None and xmax != max_time:
        # Or fill to some custom xmax
        max_time = xmax
    elif xmax is None and max_time < 1.0:
        # xmax should be at least 1.0
        max_time = 1.0

    left = df_plot["started_application (s)"]
    diff = [max_time - l for l in left]
    plt.barh(y, diff, color=cs[-1], left=left, align="edge", height=bar_height)

    # Set plot details
    ax1.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.grid(True)

    # Set y axis details
    ax1.set_ylabel("Pods")
    y_max = len(y)
    if ymax:
        y_max = ymax

    ax1.set_ylim(0, y_max)

    # Set x axis details
    ax1.set_xlabel("Time (s)")
    x_max = max(1.0, max_time)
    if xmax:
        x_max = xmax

    ax1.set_xlim(0, x_max)

    # Set x/y ticks if argument passed
    if xinter:
        ax1.set_xticks(np.arange(0, x_max + 0.1, xinter))
    if yinter:
        ax1.set_yticks(np.arange(0, y_max + 0.1, yinter))

    # add legend
    patches = []
    for c in cs:
        patches.append(mpatches.Patch(facecolor=c, edgecolor="k"))

    texts = colors.keys()
    ax1.legend(patches, texts, loc="lower right", fontsize="16")

    # Save plot
    plt.savefig("./logs/%s_breakdown_intern.pdf" % (timestamp), bbox_inches="tight")
    plt.close(fig)


def plot_p56(df, timestamp, xmax=None, ymax=None, xinter=None, yinter=None, width=20, height=5):
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
    fig, ax1 = plt.subplots(figsize=(width, height))

    bar_height = 1.1

    df_plot = df.copy(deep=True)
    df_plot = df_plot[
        [
            "kubelet_pod_received (s)", #0500
            "kubelet_created_cgroup (s)", #0504
            "kubelet_mounted_volume (s)", #0505
            "kubelet_applied_sandbox (s)", #0514
            "kubelet_created_container (s)", #0517
            "started_application (s)",
        ]
    ]

    df_plot = df_plot.sort_values(by=["started_application (s)"])
    df_plot.to_csv("./logs/%s_sort_dataframe_56.csv" % timestamp, index=False, encoding="utf-8")

    y = [*range(len(df_plot["started_application (s)"]))]

    left = [0 for _ in range(len(y))]

    colors = {
        "EMPTY": "#ffffff", 
        r"$T_{cg} + T_{nn}$ 500-504": "#6929c4",
        r"$\sum_{i=0}^{V} T_{mv,i}$ 504-505": "#1192e8",
        r"$T_{cs}$ 505-514": "#005d5d",
        r"$\sum_{i=0}^{C} T_{cc,i}$ 514-517": "#9f1853",
        r"$\sum_{j=0}^{C} T_{sc,j}$": "#fa4d56",
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
    y_max = len(y)
    if ymax:
        y_max = ymax

    ax1.set_ylim(0, y_max)

    # Set x axis details
    ax1.set_xlabel("Time (s)")
    x_max = max(1.0, max_time)
    if xmax:
        x_max = xmax

    ax1.set_xlim(0, x_max)

    # Set x/y ticks if argument passed
    if xinter:
        ax1.set_xticks(np.arange(0, x_max + 0.1, xinter))
    if yinter:
        ax1.set_yticks(np.arange(0, y_max + 0.1, yinter))

    # add legend
    patches = []
    for c in cs[1:-1]:
        patches.append(mpatches.Patch(facecolor=c, edgecolor="k"))

    colors.pop("EMPTY")
    colors.pop("Deployed")
    texts = colors.keys()
    ax1.legend(patches, texts, loc="lower left", fontsize="16")

    # Save plot
    plt.savefig("./logs/%s_breakdown_intern_P56.pdf" % (timestamp), bbox_inches="tight")
    plt.close(fig)

def plot_p57(df, timestamp, xmax=None, ymax=None, xinter=None, yinter=None, width=500, height=5):
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
    plt.rcParams.update({"font.size": height*2})
    fig, ax1 = plt.subplots(figsize=(width, height))

    bar_height = 1.1

    df_plot = df.copy(deep=True)
    df_plot = df_plot[
        [
            "kubelet_pod_received (s)", #0500
            # "kubelet_created_cgroup (s)", #0504
            # "kubelet_mounted_volume (s)", #0505
            # "kubelet_applied_sandbox (s)", #0514
            # "kubelet_created_container (s)", #0517
            "started_application (s)",
            # "kubelet_0502 (s)",
            # "kubelet_0503 (s)",
            # "kubelet_0506 (s)",
            # "kubelet_0507 (s)",
            # "kubelet_0508 (s)",
            # "kubelet_0509 (s)",
            # "kubelet_0510 (s)",
            # "kubelet_0511 (s)",
            # "kubelet_0512 (s)",
            # "kubelet_0513 (s)",
            # "kubelet_0515 (s)",
            # "kubelet_0516 (s)",
            # "kubelet_0518 (s)",
            # "kubelet_0519 (s)",
            # "kubelet_0520 (s)",
            # "kubelet_0521 (s)",
            # "kubelet_0522 (s)",
            # "kubelet_0523 (s)",
            # "kubelet_0540 (s)",
            # "kubelet_0541 (s)",
            # "kubelet_0542 (s)",
            # "kubelet_0555 (s)",
            # "kubelet_0556 (s)",
            # "kubelet_0557 (s)",
            # "kubelet_0558 (s)",
            # "kubelet_0559 (s)",
            # "kubelet_0560 (s)",
        # "0601",
        "0602",
        # "0603",
        # "0604",
        "0605",
        # "0606",
        # "0641",
        # "0642",
        # "0643",
        # "0644",
        "0645",
        # "0646",
        "0647",
        # "0648",
        # "0611",
        # "0612",
        # "0613",
        # "0614",
        # "0631",
        # "0632",
        # "0633",
        # "0634",
        "0635",

        # "0651",
        # "0652",
        # "0653",
        # "0654",
        # "0655",
        # "0656",
        # "0657",
        # "0658",


        # "0811",
        # "0812",
        # "0813",
        # "0814",
        # "0824",
        # "0828",
        # "0829",
        # "0825",

        "0901",
        # "0902",
        # "0903",
        # "0904",
        # "0905",
        # "0906",
        # "0907",
        # "0908",
        # "0909",
        "0912",
        # "0913",
        # "0914",
        # "0915",
        # "0916",
        "0917",
        "0918",
        # "0919",

        # "0920",
        # "0921",
        # "0922",
        # "0923",
        # "0924",
        # "0925",
        # "0926",
        "0927",
        # "0928",
        # "0929",
        # "0930",
        # "0931",
        # "0932",
        # "0933",
        # "0934",
        # "0935",
        # "0936",
        # "0937",
        # "0938",

        # "0940",
        "0941",
        # "0942",
        # "0943",
        "0944",
        "0945",
        # "0946",
        "0947",
        "0948",
        "0949",
        # "0950",
        # "0980",
        "0981",
        # "0982",
        # "0983",
        "0984",
        "0985",

        # "0960",
        # "0961",
        # "0962",
        # "0963",
        # "0964",
        "0965",
        # "0966",
        # "0967",
        # "0968",
        # "0969",
        # "0994",
        "0995",
        # "0996",
        # "0997",
        # "0998",
        # "0999",
        # "0850",
        # "0851",
        # "0852",
        # "0853",
        # "0854",
        # "0855",
        # "0856",
        # "0857",
        # "0858",
        # "0859",
        # "0860",

        # "0031",
        "0033",
        # "0034",
        # "0035",
        # "0038",
        # "0039",
        # # "0040",
        # "0041",

        # "0043",
        # # "0044",
        # # "0045",
        # "0048",
        # "0049",
        # # "0050",
        # "0051",
        ]
    ]

    # df_plot.to_csv("./logs/%s_unsort_dataframe.csv" % timestamp, index=False, encoding="utf-8")
    df_plot = df_plot.sort_values(by=["started_application (s)"])
    df_plot = df_plot.sort_values(by=df.first_valid_index(), axis=1)
    df_plot.to_csv("./logs/%s_sort_dataframe_57.csv" % timestamp, index=False, encoding="utf-8")

    y = [*range(len(df_plot["started_application (s)"]))]

    left = [0 for _ in range(len(y))]

    new_colors = {
        "kubelet_pod_received (s)": ["EMPTY", "#ffffff"],   #0500
        "kubelet_created_cgroup (s)": [r"$T_{cg} + T_{nn}$ 0504", "#6929c4"],    #0504
        "kubelet_mounted_volume (s)": [r"$\sum_{i=0}^{V} T_{mv,i}$ 0505", "#1192e8"],    #0505
        "kubelet_applied_sandbox (s)": [r"$T_{cs}$ 0514", "#005d5d"], #0514
        "kubelet_created_container (s)": [r"$\sum_{i=0}^{C} T_{cc,i}$ 0517", "#9f1853"], #0517
        "started_application (s)": [r"$\sum_{j=0}^{C} T_{sc,j}$", "#fa4d56"],

        "0502": ["end:0502", "#9980ff"],
        "0503": ["end:0503", "#cc0000"],
        "0506": ["end:0506", "#993333"],
        "0507": ["end:0507", "#1aa3ff"],
        "0508": ["end:0508", "#cc3300"],
        "0509": ["end:0509", "#ffcc99"],
        "0510": ["end:0510", "#336600"],
        "0511": ["end:0511", "#cc0033"],
        "0512": ["end:0512", "#00CED1"],
        "0513": ["end:0513", "#ff751a"],
        "0515": ["end:0515", "#ff6600"],
        "0516": ["end:0516", "#660000"],
        "0518": ["end:0518", "#B3BF6F"],
        "0519": ["end:0519", "#cc0066"],
        "0520": ["end:0520", "#ff944d"],
        "0521": ["end:0521", "#ffe6cc"],
        "0522": ["end:0522", "#99ccff"],
        "0523": ["end:0523", "#23F23C"],
        "0540": ["end:0540", "#ffb380"],
        "0541": ["end:0541", "#66cc66"],
        "0542": ["end:0542", "#e6ac00"],
        "0555": ["end:0555", "#ff3300"],
        "0556": ["end:0556", "#ffdbb0"],
        "0557": ["end:0557", "#ff8533"],
        "0558": ["end:0558", "#8b4513"],
        "0559": ["end:0559", "#23F23C"],
        "0560": ["end:0560", "#ff1a75"],

        "0601": ["0601:SyncPod:start", "#9980ff"],
        "0602": ["0602:SyncPod:cgroups:done", "#cc0000"],
        "0603": ["0603:SyncPod:CreateMirrorPod:done", "#993333"],
        "0604": ["0604:SyncPod:makePodDataDirs:done", "#cc9900"],
        "0605": ["0605:SyncPod:WaitForAttachAndMount:done", "#1aa3ff"],
        "0606": ["0606:SyncPod:done", "#cc3300"],
        "0641": ["0641:startContainer:start", "#ffcc99"],
        "0642": ["0642:startContainer:EnsureImageExists:done", "#ff1a75"],
        "0643": ["0643:startContainer:generateContainerConfig:done", "#cc0033"],
        "0644": ["0644:startContainer:PreCreateContainer:done", "#ff751a"],
        "0645": ["0645:startContainer:CreateContainer:done", "#00CED1"],
        "0646": ["0646:startContainer:PreStartContainer:done", "#660000"],
        "0647": ["0647:startContainer:StartContainer:done", "#B3BF6F"],
        "0648": ["0648:startContainer:done", "#cc0066"],
        "0611": ["0611:SyncPod:start ", "#ff944d"],
        "0612": ["0612:SyncPod:CreateSandbox:done", "#99ccff"],
        "0613": ["0613:SyncPod:generatePodSandboxConfig:done", "#23F23C"],
        "0614": ["0614:SyncPod:done", "#ffb380"],
        "0631": ["0631:createPodSandbox:start", "#66cc66"],
        "0632": ["0632:createPodSandbox:generatePodSandboxConfig:done", "#e6ac00"],
        "0633": ["0633:createPodSandbox:MkdirAll:done", "#ff3300"],
        "0634": ["0634:createPodSandbox:LookupRuntimeHandler:done", "#ffdbb0"],
        "0635": ["0635:createPodSandbox:RunPodSandbox:done", "#ff8533"],

        "0651": ["0651", "#9980ff"],
        "0652": ["0652", "#cc0000"],
        "0653": ["0653", "#993333"],
        "0654": ["0654", "#1aa3ff"],
        "0655": ["0655", "#cc3300"],
        "0656": ["0656", "#ffcc99"],
        "0657": ["0657", "#336600"],
        "0658": ["0658", "#cc0033"],

        "0811" : ["0811:libcrun_container_create:start", "#ff944d"],
        "0812" : ["0812:libcrun_container_create:done", "#99ccff"],
        "0813" : ["0813:libcrun_container_start:start", "#23F23C"],
        "0814" : ["0814:libcrun_container_start:done", "#ffb380"],
        "0824" : ["0824:libcrun_container_run_internal:start", "#66cc66"],
        "0828" : ["0828:libcrun_configure_handler:start", "#ff8533"],
        "0829" : ["0829:libcrun_configure_handler:done", "#ff3300"],
        "0825" : ["0825:libcrun_container_run_internal:done", "#ffdbb0"],

        "0901" : ["0901:containerd:RunPodSandbox:start", "#B3BF6F"],
        "0902" : ["0902:containerd:NewSandbox:done", "#cc0066"],
        "0903" : ["0903:containerd:ensureImageExists:done", "#1192e8"],
        "0904" : ["0904:containerd:sandboxContainerSpec:done", "#9980ff"],
        "0905" : ["0905:containerd:getSandboxRootDir:done", "#66cc66"],
        "0906" : ["0906:containerd:setupSandboxFiles:done", "#005d5d"],
        "0907" : ["0907:containerd:podNetwork:done", "#00CED1"],
        "0908" : ["0908:containerd:task.wait:done", "#cc3300"],
        "0909" : ["0909:containerd:RunPodSandbox:done", "#ffcc99"],
        "0912" : ["0912:containerd:CreateContainer:start", "#6929c4"],
        "0913" : ["0913:containerd:getContainerRootDir:done", "#1aa3ff"],
        "0914" : ["0914:containerd:containerMounts:done", "#23F23C"],
        "0915" : ["0915:containerd:NewContainerIO:done", "#99ccff"],
        "0916" : ["0916:containerd:CreateContainer:done", "#660000"],
        "0917" : ["0917:containerd:client:NewContainer:done", "#993333"],
        "0918" : ["0918:containerd:containerstore.NewContainer:done", "#e6ac00"],
        "0919" : ["0919:containerd:containerstore.Add:done", "#ffdbb0"],

        "0920" : ["0920:containerd:modifyProcessLabel:done", "#9980ff"],
        "0921" : ["0921:containerd:GetSecurityContext:done", "#e6ac00"],
        "0922" : ["0922:containerd:sandboxContainerSpecOpts:done", "#993333"],
        "0923" : ["0923:containerd:buildLabels:done", "#1aa3ff"],
        "0924" : ["0924:containerd:generateRuntimeOptions:done", "#cc3300"],
        "0925" : ["0925:containerd:snapshots:done", "#ffcc99"],
        "0926" : ["0926:containerd:NewContainerOpts:done", "#336600"],
        "0927" : ["0927:containerd:NewContainer:done", "#fa4d56"],
        "0928" : ["0928:containerd:getSandboxRootDir:done", "#00CED1"],
        "0929" : ["0929:containerd:getVolatileSandboxRootDir:done", "#ff751a"],
        "0930" : ["0930:containerd:container.Info:done", "#660000"],
        "0931" : ["0931:containerd:podNetwork:start", "#B3BF6F"],
        "0932" : ["0932:containerd:NewNetNS:done", "#cc0066"],
        "0933" : ["0933:containerd:NetNS.GetPath:done", "#ff944d"],
        "0934" : ["0934:containerd:updateNetNamespacePath:done", "#ffe6cc"],
        "0935" : ["0935:containerd:container.Update:done", "#99ccff"],
        "0936" : ["0936:containerd:setupPodNetwork:done", "#ffb380"],
        "0937" : ["0937:containerd:container.Update:done", "#66cc66"],
        "0938" : ["0938:containerd:UpdateSince:done", "#ff3300"],

        "0940" : ["0940:containerd:NewContainer:start", "#66cc66"],
        "0941" : ["0941:containerd:WithLease:done", "#FFA8A8"],
        "0942" : ["0942:containerd:RuntimeInfo:info", "#75C0FF"],
        "0943" : ["0943:containerd:Create:done", "#693593"],
        "0944" : ["0944:containerd:containerstore:Create:start", "#EFFF31"],
        "0945" : ["0945:containerd:containerstore:Create:done", "#AFBE00"],
        "0946" : ["0946:containerd:client:StartContainer:start", "#53EE46"],
        "0947" : ["0947:containerd:task.start:done", "#FF25C3"],
        "0948" : ["0948:containerd:StartContainer:done", "#19BB93"],
        "0949" : ["0949:containerd:NewTask:done", "#0046BA"],
        "0950" : ["0950:0950 containerd:buildLabels:done", "#EFFF31"],

        "0980" : ["0980:containerd:NewContainer:start", "#66cc66"],
        "0981" : ["0981:containerd:WithLease:done", "#FFA8A8"],
        "0982" : ["0982:containerd:RuntimeInfo:info", "#75C0FF"],
        "0983" : ["0983:containerd:Create:done", "#693593"],
        "0984" : ["0984:containerd:containerstore:Create:start", "#EFFF31"],
        "0985" : ["0985:containerd:containerstore:Create:done", "#AFBE00"],

        "0960" : ["0960:done", "#B3BF6F"],
        "0961" : ["0961:done", "#00CED1"],
        "0962" : ["0962:done", "#336600"],
        "0963" : ["0963:done", "#66cc66"],

        "0964" : ["0964:done", "#66cc66"],
        "0965" : ["0965:containerd:Create:NamespaceRequired:done", "#336600"],
        "0966" : ["0966", "#B3BF6F"],
        "0967" : ["0967", "#00CED1"],
        "0968" : ["0968", "#66cc66"],
        "0969" : ["0969", "#75C0FF"],
        "0994" : ["0994", "#66cc66"],
        "0995" : ["0995:containerd:Create:NamespaceRequired:done", "#336600"],
        "0996" : ["0996", "#B3BF6F"],
        "0997" : ["0997", "#00CED1"],
        "0998" : ["0998", "#66cc66"],
        "0999" : ["0999", "#75C0FF"],

        "0850" : ["0850:done", "#9980ff"],
        "0851" : ["0851:done", "#cc0000"],
        "0852" : ["0852:done", "#993333"],
        "0853" : ["0853:done", "#1aa3ff"],
        "0854" : ["0854:done", "#cc3300"],
        "0855" : ["0855:done", "#ffcc99"],
        "0856" : ["0856:done", "#336600"],
        "0857" : ["0857:done", "#cc0033"],
        "0858" : ["0858:done", "#19BB93"],
        "0859" : ["0859:done", "#AFBE00"],
        "0860" : ["0860:done", "#53EE46"],

        "0033": ["0033: shimTask:Create:done", "#99ccff"],
        "0034": ["0034", "#1aa3ff"],
        "0035": ["0035", "#EFFF31"],
        "0038": ["0038: container:NewContainer:start", "#EFFF31"],
        "0039": ["0039: container:NewContainer:done", "#B3BF6F"],
        "0040": ["0040", "#336600"],
        "0041": ["0041: container:process:Start:done", "#993333"],

        "0043": ["0043: shimTask:Create:done", "#99ccff"],
        "0044": ["0044", "#1aa3ff"],
        "0045": ["0045", "#EFFF31"],
        "0048": ["0048: container:NewContainer:start", "#EFFF31"],
        "0049": ["0049: container:NewContainer:done", "#B3BF6F"],
        "0050": ["0050", "#336600"],
        "0051": ["0051: container:process:Start:done", "#993333"],
    }
    used_colors = {}

    for column in df_plot:
        plt.barh(y, df_plot[column] - left, color=new_colors[column][1], left=left, align="edge", height=bar_height)
        left = df_plot[column]
        used_colors[new_colors[column][0]] = new_colors[column][1]

    cs = list(used_colors.values())

    # Calculate final bar to make all bars the same length
    max_time = df_plot["started_application (s)"].max()
    left = df_plot["started_application (s)"]
    diff = [max_time - l for l in left]
    plt.barh(y, diff, color="#ffffff", left=left, align="edge", height=bar_height)

    # Set plot details
    ax1.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.grid(True)

    # Set y axis details
    ax1.set_ylabel("Pods")

    y_max = len(y)
    if ymax:
        y_max = ymax

    ax1.set_ylim(0, y_max)

    # Set x axis details
    ax1.set_xlabel("Time (s)")
    x_max = max(1.0, max_time)
    if xmax:
        x_max = xmax

    ax1.set_xlim(0, x_max)
    #set xticks
    xticks = np.arange(0, x_max, min([0.1, 1, 10], key=lambda x: abs(x - x_max/10)))
    ax1.set_xticks(xticks)

    # Set x/y ticks if argument passed
    if xinter:
        ax1.set_xticks(np.arange(0, x_max + 0.1, xinter))
    if yinter:
        ax1.set_yticks(np.arange(0, y_max + 0.1, yinter))

    # add legend
    patches = []
    for c in cs[1:]:
        patches.append(mpatches.Patch(facecolor=c, edgecolor="k"))

    used_colors.pop("EMPTY")
    texts = used_colors.keys()
    ax1.legend(patches, texts, loc="best", fontsize=height*2)

    # Save plot
    plt.savefig("./logs/%s_breakdown_intern_P57_%s.pdf" % (timestamp, width), bbox_inches="tight")
    plt.close(fig)

def plot_resources(df, timestamp, xmax=None, ymax=None, xinter=None, yinter=None):
    """Plot resource utilization data

    Args:
        df (DataFrame): Pandas dataframe object with parsed timestamps per category
        timestamp (time): Global timestamp used to save all files of this run
        xmax (bool): Optional. Set the xmax of the plot by hand. Defaults to None.
        ymax (bool): Optional. Set the ymax of the plot by hand. Defaults to None.
    """
    plot_resources_kube(df[0], timestamp, xmax + 100.0, ymax, xinter, yinter)
    plot_resources_os(df[1], timestamp, xmax + 100.0, ymax, xinter, yinter)


def plot_resources_kube(df, timestamp, xmax=None, ymax=None, xinter=None, yinter=None):
    """Plot resources based on kubectl top command

    Args:
        df (DataFrame): Pandas dataframe object with parsed timestamps per category
        timestamp (time): Global timestamp used to save all files of this run
        xmax (bool): Optional. Set the xmax of the plot by hand. Defaults to None.
        ymax (bool): Optional. Set the ymax of the plot by hand. Defaults to None.
    """
    # Create one plot for cpu and one for memory
    plt.rcParams.update({"font.size": 20})
    fig, ax1 = plt.subplots(figsize=(12, 4))

    for column in df.columns:
        if "_cpu" in column:
            ax1.plot(df["Time (s)"], df[column], label=column)

    ax1.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.grid(True)

    # Set y axis details
    ax1.set_ylabel("CPU Usage (millicpu)")
    y_max = math.ceil(df.filter(like="_cpu").values.max() * 1.1)
    if ymax:
        y_max = ymax

    ax1.set_ylim(0, y_max)

    # Set x axis details
    ax1.set_xlabel("Time (s)")
    x_max = df["Time (s)"].values.max()
    if xmax:
        x_max = xmax

    ax1.set_xlim(0, x_max)

    # Set x/y ticks if argument passed
    if xinter:
        ax1.set_xticks(np.arange(0, x_max + 0.1, xinter))
    if yinter:
        ax1.set_yticks(np.arange(0, y_max + 0.1, yinter))

    # add legend
    ax1.legend(loc="best", fontsize="16")

    plt.savefig("./logs/%s_resources_cpu.pdf" % (timestamp), bbox_inches="tight")
    plt.close(fig)

    # ------------------------------
    # Now for memory
    fig, ax1 = plt.subplots(figsize=(12, 4))

    for column in df.columns:
        if "_memory" in column:
            ax1.plot(df["Time (s)"], df[column], label=column)

    ax1.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.grid(True)

    # Set y axis details
    ax1.set_ylabel("Memory Usage (MB)")
    y_max = math.ceil(df.filter(like="_memory").values.max() * 1.1)
    if ymax:
        y_max = ymax

    ax1.set_ylim(0, y_max)

    # Set x axis details
    ax1.set_xlabel("Time (s)")
    x_max = df["Time (s)"].values.max()
    if xmax:
        x_max = xmax

    ax1.set_xlim(0, x_max)

    # Set x/y ticks if argument passed
    if xinter:
        ax1.set_xticks(np.arange(0, x_max + 0.1, xinter))
    if yinter:
        ax1.set_yticks(np.arange(0, y_max + 0.1, yinter))

    # add legend
    ax1.legend(loc="best", fontsize="16")

    plt.savefig("./logs/%s_resources_memory.pdf" % (timestamp), bbox_inches="tight")
    plt.close(fig)


def plot_resources_os(df, timestamp, xmax=None, ymax=None, xinter=None, yinter=None):
    """Plot resources based on os-level resource metric commands

    Args:
        df (DataFrame): Pandas dataframe object with parsed timestamps per category
        timestamp (time): Global timestamp used to save all files of this run
        xmax (bool): Optional. Set the xmax of the plot by hand. Defaults to None.
        ymax (bool): Optional. Set the ymax of the plot by hand. Defaults to None.
    """
    plt.rcParams.update({"font.size": 20})
    fig, ax1 = plt.subplots(figsize=(12, 4))

    for column in df.columns:
        if "cpu-used" in column:
            name = column
            if "controller" in column:
                name = "Control Plane"
            else:
                name = "Worker Node " + column.split("cloud")[1].split(" (")[0]
            ax1.plot(df["Time (s)"], df[column], label=name)

    ax1.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.grid(True)

    # Set y axis details
    ax1.set_ylabel("CPU Utilization (%)")
    y_max = 100
    if ymax:
        y_max = ymax

    ax1.set_ylim(0, y_max)

    # Set x axis details
    ax1.set_xlabel("Time (s)")
    x_max = df["Time (s)"].values.max()
    if xmax:
        x_max = xmax

    ax1.set_xlim(0, x_max)

    # Set x/y ticks if argument passed
    if xinter:
        ax1.set_xticks(np.arange(0, x_max + 0.1, xinter))
    if yinter:
        ax1.set_yticks(np.arange(0, y_max + 0.1, yinter))

    # add legend
    ax1.legend(loc="best", fontsize="16")

    plt.savefig("./logs/%s_resources_os_cpu.pdf" % (timestamp), bbox_inches="tight")
    plt.close(fig)

    # ------------------------------
    # Now for memory
    fig, ax1 = plt.subplots(figsize=(12, 4))

    for column in df.columns:
        if "memory-used" in column:
            name = column
            if "controller" in column:
                name = "Control Plane"
            else:
                name = "Worker Node " + column.split("cloud")[1].split(" (")[0]
            ax1.plot(df["Time (s)"], df[column], label=name)

    ax1.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.grid(True)

    # Set y axis details
    ax1.set_ylabel("Memory Utilization (%)")
    y_max = 100
    if ymax:
        y_max = ymax

    ax1.set_ylim(0, y_max)

    # Set x axis details
    ax1.set_xlabel("Time (s)")
    x_max = df["Time (s)"].values.max()
    if xmax:
        x_max = xmax

    ax1.set_xlim(0, x_max)

    # Set x/y ticks if argument passed
    if xinter:
        ax1.set_xticks(np.arange(0, x_max + 0.1, xinter))
    if yinter:
        ax1.set_yticks(np.arange(0, y_max + 0.1, yinter))

    # add legend
    ax1.legend(loc="best", fontsize="16")

    plt.savefig("./logs/%s_resources_os_memory.pdf" % (timestamp), bbox_inches="tight")
    plt.close(fig)
