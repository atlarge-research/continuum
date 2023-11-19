# Define custom function directory
ARG FUNCTION_DIR="/function"

#------------------------------------------------------------------------
FROM python:3.8.7-slim-buster

# Include global arg in this stage of the build
ARG FUNCTION_DIR

# Copy function source code
RUN mkdir -p ${FUNCTION_DIR}
COPY src/* ${FUNCTION_DIR}/

# Set working directory to function root directory
WORKDIR ${FUNCTION_DIR}

CMD [ "python3", "-u", "empty.py"]
