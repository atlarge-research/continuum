#!/bin/bash
cp ../model/* ./src/
docker buildx build --platform linux/amd64,linux/arm64 -t redplanet00/kubeedge-applications:image_classification_subscriber --push .
rm src/labels.txt src/model.tflite
