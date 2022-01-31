#!/bin/bash
cp -r ../images src/
docker build -t redplanet00/kubeedge-applications:image_classification_publisher .
docker push redplanet00/kubeedge-applications:image_classification_publisher
rm -r src/images
