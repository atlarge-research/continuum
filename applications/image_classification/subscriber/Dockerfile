# Define custom function directory
ARG FUNCTION_DIR="/function"

#------------------------------------------------------------------------
FROM python:3.8.7-slim-buster as build_image

# Install packages needed for TFlite
RUN apt update
RUN apt install -y \
    swig \
    libjpeg-dev \
    zlib1g-dev \
    python3-dev \
    python3-numpy \
    python3-pip \
    git \
    curl \ 
    unzip \
    wget \ 
    tar

# Install python specific packages
RUN pip3 install numpy pybind11

# Install TF lite from github
RUN wget https://github.com/tensorflow/tensorflow/archive/refs/tags/v2.3.4.tar.gz
RUN tar xvf v2.3.4.tar.gz
RUN bash ./tensorflow-2.3.4/tensorflow/lite/tools/make/download_dependencies.sh
RUN bash ./tensorflow-2.3.4/tensorflow/lite/tools/pip_package/build_pip_package.sh


#------------------------------------------------------------------------
FROM python:3.8.7-slim-buster as runtime_image

# Include global arg in this stage of the build
ARG FUNCTION_DIR

# Copy function source code
RUN mkdir -p ${FUNCTION_DIR}
COPY src/* ${FUNCTION_DIR}/

# Copy TFlite wheel
# NOTE: IF TENSORFLOW UPDATES, THIS DOCKERFILE MAY CRASH HERE. UPDATE THE NAMES IN THAT CASE
COPY --from=build_image tensorflow-2.3.4/tensorflow/lite/tools/pip_package/gen/tflite_pip/python3/dist/*.whl ./
RUN pip3 install *.whl

# Install app specific packages
RUN pip3 install -r ${FUNCTION_DIR}/requirements.txt

# Set working directory to function root directory
WORKDIR ${FUNCTION_DIR}

# Open port to the MQTT broker
EXPOSE 1883

CMD [ "python3", "-u", "subscriber.py"]
