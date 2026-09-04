FROM python:3.11-slim@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534

WORKDIR /app
COPY application/image_batch/requirements-worker.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY application/image_batch/src/events.py application/image_batch/src/worker.py /app/
COPY application/image_classification/src/model /model

RUN useradd --create-home --uid 1000 worker
USER worker

ENV CLASSIFIER_MODE=tflite MODEL_PATH=/model/model.tflite LABELS_PATH=/model/labels.txt
CMD ["python", "-u", "worker.py"]
