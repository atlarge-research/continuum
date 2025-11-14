#!/bin/bash
docker buildx build --platform linux/amd64 -t redplanet00/mpi-demo:array --push .