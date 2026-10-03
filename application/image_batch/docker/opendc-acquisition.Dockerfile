# Reuse the calibrated pinned FNS engine; update only the Python input/result wrapper.
ARG OPENDC_PARENT=continuum/opendc:fns-loop-20260925-122a859
FROM ${OPENDC_PARENT}
LABEL org.continuum.opendc.wrapper="controlled-acquisition-v1"
COPY application/image_batch/src/opendc_*.py application/image_batch/src/forecast_trace.py /app/
