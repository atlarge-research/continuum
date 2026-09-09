FROM python:3.11-slim@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534
WORKDIR /app
COPY application/image_batch/requirements-forecast.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY application/image_batch/src/forecast_trace.py application/image_batch/src/forecast_workload.py application/image_batch/src/evaluate_forecasts.py /app/
USER 1000:1000
ENV OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
CMD ["python", "-u", "forecast_workload.py"]
