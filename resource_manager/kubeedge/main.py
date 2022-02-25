'''\
Main source code file.

Benchmark KubeEdge using one of the provided applications.
Check the README and help for more information.
'''

import argparse
import os.path
import sys
import logging
import os
import time
import pathlib
import json
import socket

import ansible_inventory
import machine as m
import output
import qemu_generate
import qemu
import setup_endpoints
import setup_workers


def main(args):
    if args.mode == 'cloud' or args.mode == 'edge':
        setup_workers.start_kube(args, machines)

    if args.mode == 'cloud' or args.mode == 'edge':
        setup_workers.start_subscribers(args, machines)

    logging.info('Start publishers in Docker containers')
    endpoint_names = setup_endpoints.start_publisher(args, machines)
    setup_endpoints.wait_completion(machines, endpoint_names)
    endpoint_output = output.endpoint_output(machines, endpoint_names)

    logging.info('Benchmark has been finished, prepare results')
    worker_output = []
    if args.mode == 'cloud' or args.mode == 'edge':
        worker_output = output.get_subscriber_output(args, machines)

    sub_metrics, endpoint_metrics = output.gather_metrics(
        args, worker_output, endpoint_output, endpoint_names)
    output.format_output(args, sub_metrics, endpoint_metrics)

    if args.delete:
        delete_vms(machines)
