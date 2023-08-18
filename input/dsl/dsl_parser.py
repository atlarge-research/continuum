# import configparser
import os
from subprocess import Popen, PIPE
import json

from application import application
from input.configuration.configuration_parser import (
    add_constants,
    dynamic_import,
    # add_options,
    verify_options,
)


def start(parser, file_path):
    process = Popen(["ts-node", file_path], stdout=PIPE, stderr=PIPE)
    stdout, stderr = process.communicate()

    if len(stderr):
        parser.error(stderr.decode("utf-8"))

    try:
        config = json.loads(stdout.decode("utf-8"))
    except ValueError:
        parser.error(
            "Invalid Configuration provided. Make sure only one configuration outputs at a time"
        )

    if isinstance(config, list):
        parser.error("Executing a list of configurations is not available yet")

    # TODO: not sure what this does but was used to pass to the add_options function
    # input_config = (
    #     configparser.ConfigParser()
    # )

    dynamic_import(parser, config)
    add_constants(parser, config)

    # Add and verify options for each module
    # TODO why is this disabled?
    # add_options(parser, input_config, config)

    # I think the issue has to do with the way to module/module varaibles are handled.
    verify_options(parser, config)

    if config["module"]["application"]:
        # Add the location of the application container image
        # Required here, for possible integration during infrastructure phase
        application.set_container_location(config)

    config["infrastructure"]["base_path"] = os.path.expanduser(
        config["infrastructure"]["base_path"]
    )

    return config
