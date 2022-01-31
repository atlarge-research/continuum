#!/bin/bash
cp ../model/* ./src/
docker build -t redplanet00/kubeedge-applications:image_classification_subscriber .
docker push redplanet00/kubeedge-applications:image_classification_subscriber
rm src/labels.txt src/model.tflite
