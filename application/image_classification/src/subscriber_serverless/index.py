"""\
Copyright (c) Alex Ellis 2017. All rights reserved.
Licensed under the MIT license. See LICENSE file in the project root for full license information.
"""

import sys
from function import handler


def get_stdin():
    """Get input from the trigger and forward the request body to the serverless function

    Returns:
        str: Input from trigger as string
    """
    buf = ""
    while True:
        line = sys.stdin.readline()
        buf += line
        if line == "":
            break
    return buf


if __name__ == "__main__":
    st = get_stdin()
    ret = handler.handle(st)
    if ret is not None:
        print(ret)
