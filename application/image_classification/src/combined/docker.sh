#!/bin/bash
cp -r ../images src/
cp ../model/* ./src/
docker buildx build --platform linux/amd64,linux/arm64 -t redplanet00/kubeedge-applications:image_classification_combined --push .
rm -r src/images
rm src/labels.txt src/model.tflite
