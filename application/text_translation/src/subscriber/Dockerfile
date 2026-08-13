ARG PYTHON_IMAGE="docker.io/library/python:3.11.13-slim-bookworm@sha256:cec9aa7aa96eea4fa036e9b82be1e6b325f2e3707f462d885868df51ec0a4b47"

FROM ${PYTHON_IMAGE} AS model-artifacts

COPY model.lock.json /tmp/model.lock.json
COPY scripts/fetch_model.py /tmp/fetch_model.py
RUN python3 /tmp/fetch_model.py \
    --lock /tmp/model.lock.json \
    --destination /opt/continuum/text-translation/artifacts/opus-mt-en-nl

FROM ${PYTHON_IMAGE} AS python-dependencies

COPY requirements.lock /tmp/requirements.lock
RUN python3 -m pip install \
    --disable-pip-version-check \
    --no-cache-dir \
    --only-binary=:all: \
    --require-hashes \
    --prefix=/install \
    --requirement /tmp/requirements.lock

FROM ${PYTHON_IMAGE} AS runtime

ENV HOME="/tmp" \
    HF_HOME="/tmp/huggingface" \
    HF_HUB_OFFLINE="1" \
    PYTHONUNBUFFERED="1" \
    TRANSFORMERS_OFFLINE="1"

LABEL io.continuum.benchmark.baseline="new-en-nl-opus-mt" \
      io.continuum.model.license="Apache-2.0" \
      io.continuum.model.repository="Helsinki-NLP/opus-mt-en-nl" \
      io.continuum.model.revision="8aad73b34ff36c090e7fc8a2eb7e2e7cca235d31"

COPY --from=python-dependencies /install/ /usr/local/
COPY --from=model-artifacts \
    /opt/continuum/text-translation/artifacts/opus-mt-en-nl/ \
    /opt/continuum/text-translation/artifacts/opus-mt-en-nl/
COPY src/subscriber.py src/translation_runtime.py \
    /opt/continuum/text-translation/subscriber/

WORKDIR /opt/continuum/text-translation/subscriber

EXPOSE 1883

USER 65532:65532

CMD ["python3", "-u", "/opt/continuum/text-translation/subscriber/subscriber.py"]
