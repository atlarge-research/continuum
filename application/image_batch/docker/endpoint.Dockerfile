FROM python:3.11-slim@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534

WORKDIR /app
COPY application/image_batch/src/events.py application/image_batch/src/endpoint.py /app/
COPY application/image_classification/src/images /images

RUN useradd --create-home --uid 1000 endpoint
USER endpoint

ENV IMAGE_DIR=/images BATCH_COUNT=1
CMD ["python", "-u", "endpoint.py"]
