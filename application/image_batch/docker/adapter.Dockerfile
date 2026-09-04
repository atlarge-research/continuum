FROM python:3.11-slim@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534

WORKDIR /app
COPY application/image_batch/requirements-adapter.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY application/image_batch/src /app

RUN useradd --create-home --uid 1000 adapter && mkdir /data && chown adapter:adapter /data
USER adapter

ENV ADAPTER_HOST=0.0.0.0 ADAPTER_PORT=8080 DATA_DIR=/data SUBMITTER=kubernetes
EXPOSE 8080
CMD ["python", "-u", "adapter.py"]
