"""Create a flipped csv for fig1
Assume the csv is already correct
"""

import argparse
import time
import math

import pandas as pd
import numpy as np

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.ticker import MaxNLocator


def parse_data(df):
    """Parse dataframe into a plottable csv

    Args:
        df (dataframe): Pandas dataframe with input data

    Returns:
        dict: Dict with parsed data
    """
    csv = {
        "Time (s)": [],
        "Default Kubernetes": [],
        "Managed Kubernetes": [],
        "Containerd (threads=1)": [],
        "Containerd (threads=8)": [],
        "Columbo (our solution)": [],
    }

    # First add all time entries
    for column in df:
        if column == "Deployed Containers":
            continue

        for t in df[column]:
            csv["Time (s)"].append(t)

    # Remove duplicate entries and sort
    csv["Time (s)"] = [0.0] + csv["Time (s)"]
    csv["Time (s)"] = list(set(csv["Time (s)"]))
    csv["Time (s)"].sort()

    # Set entire list to zero
    for key in csv:
        if key == "Time (s)":
            continue

        csv[key] = [0] * len(csv["Time (s)"])

    # To prevent a large tail of 100 values
    finished = {}
    for key in csv:
        finished[key] = False

    # Now add entries
    for i, timestamp in enumerate(csv["Time (s)"]):
        for column in df:
            if column in ["Deployed Containers"]:
                continue

            for t in df[column]:
                if timestamp == t:
                    for j in range(i, len(csv[column])):
                        # Don't create a big tail of 100 values
                        if not finished[column]:
                            csv[column][j] += 1

                            # Set all values after the 100 to none - we don't need those values
                            if csv[column][j] == 100:
                                finished[column] = True
                                if j + 1 != len(csv[column]):
                                    for k in range(j + 1, len(csv[column])):
                                        csv[column][k] = None

    return csv


def plot_data(ax, df):
    """Plot parsed data

    Args:
        df (dataframe): Dataframe with parsed data
        timestamp (datetime): Datetime object with current timestamp
    """
    colors = [
        "#6929c4",
        "#1192e8",
        "#005d5d",
        "#9f1853",
        "#fa4d56",
        # "#570408",
        # "#198038",
    ]

    for i, key in enumerate(df):
        if key == "Time (s)":
            continue

        ax.plot(
            df["Time (s)"],
            df[key],
            color=colors[i - 1],
            linewidth=8.0,
        )

    # Set plot details
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.grid(True)

    # Set y axis details
    ax.set_ylabel("Containers" + "\n" + "Deployed")
    ax.set_ylim(0, df["Default Kubernetes"].values[-1])
    plt.yticks(np.arange(0, 101, 20))

    # Set x axis details
    ax.set_xlabel("Time (s)")
    ax.set_xlim(0, math.ceil(df["Time (s)"].values[-1]) + 1)

    # add legend
    patches = []
    for c in colors:
        patches.append(mpatches.Patch(facecolor=c, edgecolor="k"))

    texts = df.columns.values[1:]
    ax.legend(patches, texts, loc="lower right", fontsize="16", bbox_to_anchor=(1.01, -0.03))

    plt.text(12.3, 90, "A", fontsize=22)


def plot_bar(ax, timestamp):
    """We take the last application/pod from the "Local Kubernetes" line from the main plot
    And make a vertical stacked bar plot out of it

    Args:
        timestamp (datetime): Datetime object with current timestamp
    """
    # colors = [
    #     "#6929c4",
    #     "#1192e8",
    #     "#005d5d",
    #     "#9f1853",
    #     "#fa4d56",
    #     "#570408",
    #     "#ffffff"
    #     "#198038",
    # ]

    # We take the last application/pod from the "Local Kubernetes" line from the main plot
    # And make a vertical stacked bar plot out of it
    x = [""]
    # y = {
    #     "Create Workload Object": 0.248514413833618,
    #     "Unpack Workload Object": 2.22330665588379,
    #     "Create Pod Object": 3.9536349773407,
    #     "Schedule Pod": 3.96205139160156,
    #     "Create Pod": 11.7857611179352,
    #     "Create Container": 12.1920666694641,
    #     "Deployed": 14.0,
    # }

    # Change of hearts: Only plot 2 phases, scheduling and container deployment
    y = {
        "Schedule Application": 3.9536349773407,
        "Deploy Application": 12.1920666694641,
        "Deployed": 14.0,
    }

    colors = ("gray", "darkgray", "lightgray")

    # Horizontal bar only needs differences
    bottom = 0
    for key, color in zip(y, colors):
        y[key] -= bottom
        ax.barh(x, y[key], left=bottom, height=1.0, color=color, alpha=0.99)
        bottom += y[key]

    # Set plot details
    ax.grid(True)
    ax.grid(axis="y")

    # Set y axis details
    ax.set_ylim(-0.25, 0.25)

    patches = []
    for color in colors:
        patches.append(mpatches.Patch(facecolor=color, edgecolor="k"))

    texts = list(y.keys())
    ax.legend(patches, texts, loc="upper center", fontsize="16", ncol=3, bbox_to_anchor=(0.5, 1.68))

    # Save plot
    plt.savefig("./%s_fig1.pdf" % (timestamp), bbox_inches="tight")


def main(df):
    """Main function

    Args:
        df (dataframe): Dataframe with input data
    """
    csv = parse_data(df)
    df_out = pd.DataFrame(csv)

    timestamp = time.strftime("%Y-%m-%d_%H:%M:%S", time.gmtime())
    # df_out.to_csv("./%s_fig1.csv" % (timestamp), index=False, encoding="utf-8")

    plt.rcParams.update({"font.size": 20})
    fig, (ax1, ax2) = plt.subplots(
        nrows=2,
        sharex=True,
        gridspec_kw={"height_ratios": [1, 3.8], "hspace": 0.05},
        figsize=((12, 5)),
    )
    plot_data(ax2, df_out)
    plot_bar(ax1, timestamp)
    plt.close(fig)


if __name__ == "__main__":
    # Get input arguments and parse them
    parser = argparse.ArgumentParser()

    parser.add_argument("path", type=str, help="Path to csv file to make fig1 from")
    arguments = parser.parse_args()

    input_df = pd.read_csv(arguments.path)

    main(input_df)
