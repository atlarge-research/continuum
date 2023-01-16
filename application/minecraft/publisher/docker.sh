#!/bin/bash
cp -r ../images src/
docker buildx build --platform linux/amd64,linux/arm64 -t lwagner1/minecraft_benchmark:minecraft_bot --push .
rm -r src/images
