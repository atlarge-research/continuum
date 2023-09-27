"""Create a flipped csv for fig1
Assume the csv is already correct
See Google Cloud project for assumed CSV input
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
        "Elapsed Time (s)": [],
        "Default Kubernetes": [],
        "GKE": [],
        "Containerd": [],
        "Columbo (our solution)": [],
    }

    # First add all time entries
    for column in df:
        if column == "Deployed Containers":
            continue

        for t in df[column]:
            csv["Elapsed Time (s)"].append(t)

    # Remove duplicate entries and sort
    csv["Elapsed Time (s)"] = [0.0] + csv["Elapsed Time (s)"]
    csv["Elapsed Time (s)"] = list(set(csv["Elapsed Time (s)"]))
    csv["Elapsed Time (s)"].sort()

    # Set entire list to zero
    for key in csv:
        if key == "Elapsed Time (s)":
            continue

        csv[key] = [0] * len(csv["Elapsed Time (s)"])

    # To prevent a large tail of 100 values
    finished = {}
    for key in csv:
        finished[key] = False

    # Now add entries
    for i, timestamp in enumerate(csv["Elapsed Time (s)"]):
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


def plot_data(df, timestamp):
    """Plot parsed data

    Args:
        df (dataframe): Dataframe with parsed data
        timestamp (datetime): Datetime object with current timestamp
    """
    plt.rcParams.update({"font.size": 20})
    fig, ax = plt.subplots(figsize=((12, 4)))

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
        if key == "Elapsed Time (s)":
            continue

        ax.plot(
            df["Elapsed Time (s)"],
            df[key],
            color=colors[i - 1],
            linewidth=8.0,
        )

    # Set plot details
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax.grid(True)

    # Set y axis details
    ax.set_ylabel("Containers Deployed")
    ax.set_ylim(0, df["Default Kubernetes"].values[-1])
    plt.yticks(np.arange(0, 101, 20))

    # Set x axis details
    ax.set_xlabel("Elapsed Time (s)")
    ax.set_xlim(0, math.ceil(df["Elapsed Time (s)"].values[-1]) + 1)

    # add legend
    patches = []
    for c in colors:
        patches.append(mpatches.Patch(facecolor=c, edgecolor="k"))

    texts = df.columns.values[1:]
    ax.legend(patches, texts, loc="lower right", fontsize="16", bbox_to_anchor=(1.01, -0.03))

    # Save plot
    plt.savefig("./%s_fig1.pdf" % (timestamp), bbox_inches="tight")
    plt.close(fig)


def main(df):
    """Main function

    Args:
        df (dataframe): Dataframe with input data
    """
    csv = parse_data(df)
    df_out = pd.DataFrame(csv)

    timestamp = time.strftime("%Y-%m-%d_%H:%M:%S", time.gmtime())
    # df_out.to_csv("./%s_fig1.csv" % (timestamp), index=False, encoding="utf-8")

    plot_data(df_out, timestamp)


if __name__ == "__main__":
    # Get input arguments and parse them
    parser = argparse.ArgumentParser()

    parser.add_argument("path", type=str, help="Path to csv file to make fig1 from")
    arguments = parser.parse_args()

    input_df = pd.read_csv(arguments.path)

    main(input_df)
