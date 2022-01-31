#!/bin/bash
cp -r ../images src/
cp ../model/* ./src/
docker build -t redplanet00/kubeedge-applications:image_classification_combined .
docker push redplanet00/kubeedge-applications:image_classification_combined
rm -r src/images
rm src/labels.txt src/model.tflite
