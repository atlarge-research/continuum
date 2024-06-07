"""\
Explanaation of the dataset and how to download it can be found here:
https://github.com/Azure/AzurePublicDataset/blob/master/AzureTracesForPacking2020.md

The script assumes the data file is called "packing_trace_zone_a_v1.sqlite" and is in the same
directory as this script

-----------------
The sqlite database has 2 tables:
1. vm
2. vmType

We are interested in the former, which has the following format

            vmId  tenantId  vmTypeId  priority   starttime    endtime
0              0         0         8         0 -138.925486        NaN
1              1         0         8         0 -138.925486  18.035497
2              2         0         8         0 -138.925486  29.828787
3              3         0         8         0 -138.925486        NaN
4              4         0         8         0  -63.689572  53.589653
...          ...       ...       ...       ...         ...        ...
5559795  7735508   2791895        42         0   13.381644  13.382375
5559796  7735509   2791895        42         0   13.381644  13.382375
5559797  7735516   2791704        42         0   13.397303  13.404040
5559798  7735517   2791704        42         0   13.397303  13.404040
5559799  7735518   2791704        42         0   13.397303  13.404040

[5559800 rows x 6 columns]

The columns have the following explanation
vmId 	    unique id of the vm request1
tenantId 	unique id for the owner of a group of requests1
vmTypeId 	requested VM type1
priority 	priority of the VM request2
starttime 	the time (in fractional days) when the VM request was created3
endtime 	the time (in fractional days) when the VM left the system3

We are only interested in starttime. The time starts with a negative number of the VM was started
before the trace. We offset these values to 0 so nothing is <0. We also bin per X seconds, where
X is an argument to this script. We do this because when we launch the workloads to Kubernetes,
we launch Y jobs per X seconds via kubectl, with Y the number of VMs in the bin of X seconds.
"""

import argparse
import sqlite3

import matplotlib.pyplot as plt
import pandas as pd

FILE = "packing_trace_zone_a_v1.sqlite"


def plot_hist(df):
    print("=========================================")
    print(df.info)
    print("Minimum: " + str(df["starttime"].min()))
    print("Maximum: " + str(df["starttime"].max()))
    print("=========================================\n")

    # 1 bin = 1/100 of a day = 14.4 minutes
    plt.hist(df["starttime"], bins=1400)
    plt.show()


def plot_line(df):
    print("=========================================")
    print(df.info)
    print("Minimum: " + str(df["starttime"].min()))
    print("Maximum: " + str(df["starttime"].max()))
    print("=========================================\n")

    plt.plot(df["starttime"], df["bincount"])
    plt.show()


def main(arguments):
    # ----------------------------------------------------------
    # Read the file to pandas dataframe
    # We are only interested in starttime, see comments at the top of this file
    con = sqlite3.connect(FILE)
    df = pd.read_sql_query("SELECT starttime FROM vm", con)

    print("Original dataset")
    plot_hist(df)

    # ----------------------------------------------------------
    # Correct negative starttimes to positives
    # df["starttime"] += df["starttime"][0] * -1

    # Ignore negative starttimes
    df = df.loc[df["starttime"] > 0.0]
    print("Removed all starttimes <0")
    plot_hist(df)

    # ----------------------------------------------------------
    # Transform from fractional days to seconds
    df["starttime"] *= 3600 * 24
    print("Transformed from fractional days to seconds")
    plot_hist(df)

    # ----------------------------------------------------------
    # Bin per second
    bins = [i for i in range(0, 14 * 3600 * 24 + 1, arguments.bin)]
    bincount = df.groupby(pd.cut(df["starttime"], bins=bins)).size()
    df_bins = pd.DataFrame({"starttime": bincount.index, "bincount": bincount.values})

    df_bins["starttime"] = df_bins["starttime"].apply(lambda x: x.left)

    print("Convert to bincount for %i seconds" % (arguments.bin))
    plot_line(df_bins)

    # ----------------------------------------------------------
    df_bins.to_csv("packing.csv", sep="\t", encoding="utf-8", index=False)


if __name__ == "__main__":
    parser_obj = argparse.ArgumentParser()
    parser_obj.add_argument(
        "bin",
        type=int,
        help="binning interval in seconds",
    )

    arguments = parser_obj.parse_args()
    main(arguments)
