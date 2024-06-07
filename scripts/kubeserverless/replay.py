"""\
Replay trace files and produce real Kubernetes workload via kubectl

TODO if kubectl uses too much cpu, can we investigate sending direct HTTP messages to the API
     server instead? That should be much quicker.
"""

import time

import pandas as pd

FILE = "packing.csv"


def main():
    # ----------------------------------------------------------
    # Read the file to pandas dataframe
    df = pd.read_csv(FILE, sep="\t")
    print(df.info)

    time_offset = time.time_ns()
    for _, row in df.iterrows():
        time_now = time.time_ns() - time_offset
        bin_start = row["starttime"] * 10**9

        print("Waiting to execute bin at %i seconds" % (row["starttime"]))

        # Check if and how long we have to sleep until the next bin should start executing
        if time_now < bin_start:
            interval = float(bin_start - time_now) / 10**9
            print("\tSleep for %f seconds" % (interval))
            time.sleep(interval)

        # Check how much too slow we are in starting the next bin. Should be milliseconds.
        time_now = time.time_ns() - time_offset
        if time_now > bin_start:
            interval = float(time_now - bin_start) / 10**9
            print("\tToo late by %f seconds" % (interval))

        # -------------------------------------------------------------
        # Now execute calls within this bin
        bin_count = row["bincount"]
        for i in range(bin_count):
            print("Execute %i" % (i))


if __name__ == "__main__":
    main()
