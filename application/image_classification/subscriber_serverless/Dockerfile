#------------------------------------------------------------------------
FROM --platform=${TARGETPLATFORM:-linux/amd64} python:3.8.7-slim-buster as build_image

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
FROM --platform=${TARGETPLATFORM:-linux/amd64} ghcr.io/openfaas/classic-watchdog:0.2.1 as watchdog
FROM --platform=${TARGETPLATFORM:-linux/amd64} python:3.8.7-slim-buster

COPY --from=watchdog /fwatchdog /usr/bin/fwatchdog
RUN chmod +x /usr/bin/fwatchdog
RUN apt-get update \
    && apt-get install -y ca-certificates \
    && rm -rf /var/lib/apt/lists/

# Add non root user
RUN groupadd app && useradd -r -g app app

WORKDIR /home/app/

COPY index.py           .
COPY requirements.txt   .

RUN chown -R app /home/app && \
    mkdir -p /home/app/python && chown -R app /home/app
USER app
ENV PATH=$PATH:/home/app/.local/bin:/home/app/python/bin/
ENV PYTHONPATH=$PYTHONPATH:/home/app/python

RUN pip install -r requirements.txt --target=/home/app/python

RUN mkdir -p function
RUN touch ./function/__init__.py

WORKDIR /home/app/function/
COPY function/requirements.txt	.

RUN pip install -r requirements.txt --target=/home/app/python

# Copy TFlite wheel
# NOTE: IF TENSORFLOW UPDATES, THIS DOCKERFILE MAY CRASH HERE. UPDATE THE NAMES IN THAT CASE
COPY --from=build_image tensorflow-2.3.4/tensorflow/lite/tools/pip_package/gen/tflite_pip/python3/dist/*.whl ./
RUN pip install *.whl --target=/home/app/python

WORKDIR /home/app/

USER root

COPY function           function

# Allow any user-id for OpenShift users.
RUN chown -R app:app ./ && \
    chmod -R 777 /home/app/python

USER app

ENV fprocess="python3 index.py"
EXPOSE 8080

HEALTHCHECK --interval=3s CMD [ -e /tmp/.lock ] || exit 1

CMD ["fwatchdog"]