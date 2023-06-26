import configparser
import os
from subprocess import Popen, PIPE
import json

from configuration_parser.configuration_parser import add_constants, dynamic_import, add_options, verify_options
from application import application


def start(parser, file_path):
    if not (os.path.exists(file_path) and os.path.isfile(file_path)):
        parser.error("The given config file does not exist: %s" % (file_path))

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

    try:
        config = json.loads(stdout.decode("utf-8"))

    except ValueError:
        parser.error("Invalid Configuration provided. Make sure only one configuration outputs at a time")

    input_config = configparser.ConfigParser() # TODO: not sure what this does but was used to pass to the add_options function

    if isinstance(config, list):
        parser.error("Executing a list of configurations is not available yet")

    dynamic_import(parser, config)
    add_constants(parser, config)

    # # # Add and verify options for each module
    # add_options(parser, input_config, config)
    # i think the issue has to do with the way to module/module varaibles are handled.
    verify_options(parser, config)

    if config["module"]["application"]:
        # Add the location of the application container image
        # Required here, for possible integration during infrastructure phase
        application.set_container_location(config)

    config["infrastructure"]["base_path"] = os.path.expanduser(config["infrastructure"]["base_path"])

    return config

    