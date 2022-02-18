# Application: Image Classification
This application supports deployment on cloud, edge and endpoint. It consists of two parts: An image generator and an image processor.

- **Image generator**: This part emulates a security camera: X images are generated per second, which then need processing either locally or by offloading. The image generator always runs on the endpoint as cameras are endpoints.
- **Image processor**: Processes generated images, using object detection. This can run in any part of the continuum.

## Folders
- **Combined**: Docker source code for local processing on endpoints. This contains both the image generator and processor parts.
- **Images**: The images used for the image generator part. We include these 60 images from ImageNet in our image generator Docker containers, and then loop over them when we need to "generate" an image.
- **Model**: MobileNetV2 model from Tensorflow, used for image processing
- **Publisher**: Docker source code for the image generator. It publishes generated images to an MQTT broker running in the cloud or edge.
- **Subscriber**: Docker source code for the image processor. It is subscribed to an MQTT topic using its local MQTT broker (edge or cloud), receives the images, and processes them. 

## How to use
If you just want to use the application, ignore this folder, and use the following Docker containers from DockerHub:

- redplanet00/kubeedge-applications:image_classification_subscriber
- redplanet00/kubeedge-applications:image_classification_publisher
- redplanet00/kubeedge-applications:image_classification_combined

## Building and updating
If you want to update the application, you are free to do so. Instructions on how to build the docker containers can be found in the `docker.sh` files present in the combined, publisher, and subscriber folders.

## Misc.
Notes in the application

- The image processing happening when offloading to the cloud or edge (subscriber) uses multiprocessing. Given a worker with 4 cores, the mean thread listens to the local MQTT broker for new data, and adds this to a queue. The 4 other worker threads pick images from this queue and process them independently (given n threads we process n images in parallel if there are enough images).
- The data generation rate is a parameter that can be set in the framework. Given a generation rate of 2, we generate 2 images per second, and we check this by using time and sleep libraries.
