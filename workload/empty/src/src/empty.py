"""\
This application is used to benchmark the control plane of a resource manager.
It only consists of a sleep, and print statements to indicate the start and end of the application.
"""

import os
import time

SLEEP_TIME = int(os.environ["SLEEP_TIME"])


def main():
    """This is an empty function, only containing a single sleep"""
    print("Start the application")
    time.sleep(SLEEP_TIME)
    print("End the application")


if __name__ == "__main__":
    main()
