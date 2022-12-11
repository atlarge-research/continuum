#!/bin/bash
docker buildx build --platform linux/amd64,linux/arm64 -t redplanet00/kubeedge-applications:empty --push .
