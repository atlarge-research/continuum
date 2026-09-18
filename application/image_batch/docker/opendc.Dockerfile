# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e

FROM eclipse-temurin:21-jdk-jammy@sha256:c7d5863b5dd8f26b90c64f1d80cc2b0e5a5e4642f8db9955a370d348edd8f438 AS opendc-build

ENV GRADLE_USER_HOME=/tmp/gradle-home

ADD --checksum=sha256:f1771298a70f6db5a29daf62378c4e18a17fc33c9ba6b14362e0cdf40610380d \
    https://services.gradle.org/distributions/gradle-8.14.4-bin.zip \
    /tmp/gradle-8.14.4-bin.zip
ADD --checksum=sha256:df798dae10c0ee3b1911fb01b0dbd25f06f5adb6e8495826dc8ad8b108f4f52d \
    https://github.com/atlarge-research/opendc/archive/7db7e1a2331fd239bf29c4a69eb6fccd6fddbdad.tar.gz \
    /tmp/opendc-source.tar.gz

RUN echo "f1771298a70f6db5a29daf62378c4e18a17fc33c9ba6b14362e0cdf40610380d  /tmp/gradle-8.14.4-bin.zip" \
      | sha256sum -c - \
    && echo "df798dae10c0ee3b1911fb01b0dbd25f06f5adb6e8495826dc8ad8b108f4f52d  /tmp/opendc-source.tar.gz" \
      | sha256sum -c - \
    && mkdir -p /opt/gradle /src \
    && cd /opt/gradle \
    && jar -xf /tmp/gradle-8.14.4-bin.zip \
    && chmod 0555 /opt/gradle/gradle-8.14.4/bin/gradle \
    && tar -xzf /tmp/opendc-source.tar.gz -C /src --strip-components=1 \
    && test "$(sha256sum /src/gradle/wrapper/gradle-wrapper.jar | cut -d ' ' -f 1)" \
      = "a8451eeda314d0568b5340498b36edf147a8f0d692c5ff58082d477abe9146e4" \
    && test "$(sha256sum /src/LICENSE.txt | cut -d ' ' -f 1)" \
      = "b15bdf3c441b7600aa7e47a15c68ca170061bbff8ba62b2f25c8ceebde3e6347"

WORKDIR /src
RUN /opt/gradle/gradle-8.14.4/bin/gradle \
      --no-daemon --no-parallel --max-workers=2 --no-build-cache \
      --dependency-verification off \
      -Dorg.gradle.jvmargs="-Xms128m -Xmx2g -XX:MaxMetaspaceSize=1g -Dfile.encoding=UTF-8" \
      -Pkotlin.compiler.execution.strategy=in-process \
      :opendc-cli:installDist \
    && test -x /src/opendc-cli/build/install/OpenDCExperimentRunner/bin/opendc

FROM eclipse-temurin:21-jre-jammy@sha256:61d6c7b34d36aee3f45d043101259f97f3c6d428dc2a6f75513789983c5e254f AS java-runtime

FROM python:3.11-slim@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534

LABEL org.opencontainers.image.source="https://github.com/atlarge-research/opendc" \
      org.opencontainers.image.revision="7db7e1a2331fd239bf29c4a69eb6fccd6fddbdad" \
      org.opencontainers.image.version="3.0-SNAPSHOT" \
      org.opencontainers.image.licenses="MIT"

ENV JAVA_HOME=/opt/java/openjdk \
    JAVA_OPTS="-Xms64m -Xmx1g -XX:ActiveProcessorCount=1" \
    PATH="/opt/java/openjdk/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/tmp \
    TMPDIR=/tmp

WORKDIR /app

COPY --from=java-runtime /opt/java/openjdk /opt/java/openjdk
COPY --from=opendc-build /src/opendc-cli/build/install/OpenDCExperimentRunner /opt/opendc
COPY application/image_batch/requirements-opendc.txt /tmp/requirements-opendc.txt
RUN PIP_ROOT_USER_ACTION=ignore python -m pip install --no-cache-dir --no-deps --require-hashes \
      -r /tmp/requirements-opendc.txt \
    && rm /tmp/requirements-opendc.txt \
    && python -c "import pyarrow; assert pyarrow.__version__ == '21.0.0'" \
    && java -version \
    && /opt/opendc/bin/opendc --help >/dev/null

COPY application/image_batch/src/opendc_*.py application/image_batch/src/forecast_trace.py /app/
COPY application/image_batch/fixtures/opendc/*.json /fixtures/opendc/

USER 1000:1000
VOLUME ["/tmp"]

ENTRYPOINT ["python", "-u", "/app/opendc_run.py"]
