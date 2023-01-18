#!/bin/bash
cp ../model/* ./function/
docker build -t redplanet00/kubeedge-applications:image_classification_subscriber_serverless .
docker push redplanet00/kubeedge-applications:image_classification_subscriber_serverless
rm function/labels.txt function/model.tflite
