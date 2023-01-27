#!/bin/bash
cp -r ../images src/
docker buildx build --platform linux/amd64,linux/arm64 -t redplanet00/kubeedge-applications:image_classification_publisher_serverless --push .
rm -r src/images
