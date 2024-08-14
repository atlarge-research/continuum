"""Create plots for the opencraft application"""

import logging
import math

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import MaxNLocator


def plot_resources(df, timestamp, xmax=None, ymax=None, xinter=None, yinter=None):
    """Plot resource utilization data

    Args:
        df (DataFrame): Pandas dataframe object with parsed timestamps per category
        timestamp (time): Global timestamp used to save all files of this run
        xmax (bool): Optional. Set the xmax of the plot by hand. Defaults to None.
        ymax (bool): Optional. Set the ymax of the plot by hand. Defaults to None.
    """
    logging.getLogger("matplotlib").setLevel("WARNING")
    plot_resources_kube(df[0], timestamp, xmax, ymax, xinter, yinter)
    plot_resources_os(df[1], timestamp, xmax, ymax, xinter, yinter)


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
    if ymax:
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
            if "cloud0" in column:
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
            if "cloud0" in column:
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
