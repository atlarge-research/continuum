#!/bin/bash
# Push to both locations
docker buildx build --platform linux/amd64,linux/arm64 -t redplanet00/kubeedge-applications:empty --push .
docker buildx build --platform linux/amd64,linux/arm64 -t redplanet00/empty:latest --push .
