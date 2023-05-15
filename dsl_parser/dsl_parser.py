import os
from subprocess import Popen, PIPE
import json


def start(parser, file_path):
    if not (os.path.exists(file_path) and os.path.isfile(file_path)):
        parser.error("The given config file does not exist: %s" % (arg))

    if not file_path.endswith(".ts"):
        parser.error("The file provided needs to be a TypeScript file (.ts)")

    process = Popen(
        ['ts-node', file_path],
        stdout=PIPE,
        stderr=PIPE
    )
    stdout, stderr = process.communicate()
    
    if(len(stderr)):
        parser.error(stderr.decode("utf-8"))

    return json.loads(stdout.decode("utf-8"))