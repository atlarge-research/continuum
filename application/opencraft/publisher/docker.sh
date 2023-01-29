#!/bin/bash
docker buildx build --platform linux/amd64,linux/arm64 -t lwagner1/opencraft_benchmark:opencraft_bot --push .
