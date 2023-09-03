"""Create a flipped csv for fig1
Assume the csv is already correct
"""

import argparse
import time
import math

import pandas as pd

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
        "Local Kubernetes": [],
        "Managed Kubernetes": [],
        "Containerd (threads=1)": [],
        "Containerd (threads=8)": [],
        "Our solution": [],
    }

    # First add all time entries
    for column in df:
        if column == "Deployed Containers":
            continue

        for t in df[column]:
            csv["Time (s)"].append(t)

    # print("\nAFTER TIME COLUMN CREATION")
    # for key in csv:
    #     print("\t%s: %s" % (key, csv[key]))

    # Remove duplicate entries and sort
    csv["Time (s)"] = [0.0] + csv["Time (s)"]
    csv["Time (s)"] = list(set(csv["Time (s)"]))
    csv["Time (s)"].sort()

    # print("\nAFTER TIME SORT")
    # for key in csv:
    #     print("\t%s: %s" % (key, csv[key]))

    # Set entire list to zero
    for key in csv:
        if key == "Time (s)":
            continue

        csv[key] = [0] * len(csv["Time (s)"])

    # print("\nAFTER ZERO SET")
    # for key in csv:
    #     print("\t%s: %s" % (key, csv[key]))

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

    # print("\nFINAL SOLUTION")
    # for key in csv:
    #     print("\t%s: %s" % (key, csv[key]))

    return csv


def plot_data(df, timestamp):
    """Plot parsed data

    Args:
        df (dataframe): Dataframe with parsed data
        timestamp (datetime): Datetime object with current timestamp
    """
    plt.rcParams.update({"font.size": 20})
    fig, ax1 = plt.subplots(figsize=(12, 4))

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

        ax1.plot(
            df["Time (s)"],
            df[key],
            color=colors[i - 1],
            linewidth=8.0,
        )

    # Set plot details
    ax1.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.grid(True)

    # Set y axis details
    ax1.set_ylabel("Containers Deployed")
    ax1.set_ylim(0, df["Local Kubernetes"].values[-1])

    # Set x axis details
    ax1.set_xlabel("Time (s)")
    ax1.set_xlim(0, math.ceil(df["Time (s)"].values[-1]) + 1)

    # add legend
    patches = []
    for c in colors:
        patches.append(mpatches.Patch(facecolor=c, edgecolor="k"))

    texts = df.columns.values[1:]
    ax1.legend(patches, texts, loc="lower right", fontsize="18", bbox_to_anchor=(1.01, -0.03))

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
    df_out.to_csv("./%s_fig1.csv" % (timestamp), index=False, encoding="utf-8")
    plot_data(df_out, timestamp)


if __name__ == "__main__":
    # Get input arguments and parse them
    parser = argparse.ArgumentParser()

    parser.add_argument("path", type=str, help="Path to csv file to make fig1 from")
    arguments = parser.parse_args()

    input_df = pd.read_csv(arguments.path)

    main(input_df)
