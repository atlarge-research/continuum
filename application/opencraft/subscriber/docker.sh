#!/bin/bash
cp -r ../images src/
docker buildx build --platform linux/amd64,linux/arm64 -t lwagner1/opencraft_benchmark:opencraft_server --push .
rm -r src/images
