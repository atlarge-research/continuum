FROM mpioperator/mpi-pi:openmpi

USER root

# Install MPI
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    build-essential \
    openmpi-bin \
    libopenmpi-dev && \
    rm -rf /var/lib/apt/lists/*

# Copy the source code and build the binary
COPY src/* /home/mpiuser/mpi_example.c
RUN chown mpiuser:mpiuser /home/mpiuser/mpi_example.c && \
    su mpiuser -c "mpicc -O2 -o /home/mpiuser/mpi_example /home/mpiuser/mpi_example.c"

# Back to mpiuser to match the base image behaviour
USER mpiuser
WORKDIR /home/mpiuser