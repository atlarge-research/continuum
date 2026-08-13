ARG PYTHON_IMAGE="docker.io/library/python:3.11.13-slim-bookworm@sha256:cec9aa7aa96eea4fa036e9b82be1e6b325f2e3707f462d885868df51ec0a4b47"

FROM ${PYTHON_IMAGE} AS python-dependencies

COPY requirements.lock /tmp/requirements.lock
RUN python3 -m pip install \
    --disable-pip-version-check \
    --no-cache-dir \
    --require-hashes \
    --prefix=/install \
    --requirement /tmp/requirements.lock

FROM ${PYTHON_IMAGE} AS runtime

ENV HOME="/tmp" \
    PYTHONUNBUFFERED="1"

COPY --from=python-dependencies /install/ /usr/local/
COPY src/publisher.py src/crime_and_punishment.txt \
    /opt/continuum/text-translation/publisher/

WORKDIR /opt/continuum/text-translation/publisher

EXPOSE 1883

USER 65532:65532

CMD ["python3", "-u", "/opt/continuum/text-translation/publisher/publisher.py"]
