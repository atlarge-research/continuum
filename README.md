# Edge Continuum Benchmark
Edge computing is a computing paradigm for offloading workload from the cloud or endpoints/IoT devices to small compute clusters near end-users called edge nodes. Leveraging edge technology is difficult as new systems for edge need to be created and applications need to be adapted. This project presents a benchmark for comparing the performance of resource managers and applications in the edge continuum (cloud, edge and endpoint devices). It automates setting up infrastructure using virtual machines and containers up to large scales by leveraging multiple physical machines, manages the installation of software, and finally runs the applications while capturing both system- and application-level metrics.

## How it works
The Edge Continuum Benchmark has the following architecture:

<div align="center">
    <img src="./docs/images/architecture.png" width = "85%" align="center">
</div>
<br>
The execution flow of the benchmark depends on which deployment mode is chosen: Cloud, edge or endpoint. In the cloud deployment mode, workload from endpoints is offloaded to cloud workers, which are all using Kubernetes for cluster management. In the edge deployment mode, workload from endpoints is offloaded to edge workers, which are all using KubeEdge for cluster management. In the endpoint deployment mode, endpoints process their own workload.

As an example, we explain the execution flow of the edge deployment mode in detail here:
1. **Infrastructure configuration:** Using the command line arguments given by the user (see "Usage"), the benchmark creates configuration files for setting up VMs and a network to connect them. Two infrastructure frameworks are supported: Libvirt-only and Terraform with Libvirt. Terraform provides a hihg-level abstraction over Libvirt, simplifiying setting up large amounts of infrastructure, but is currently limited in running Libvirt on only a single physical machine. Meanwhile Libvirt-only supports scaling up to many physical machines. The documentation covers both infrastructure frameworks modes.
2. **Infrastructure creation:** Terraform and/or Libvirt use the configuration files to create one or multiple VMs, and a network bridge (only in Libvirt mode) to connect the VMs. When the network is created, each VM gets a static IP.
3. **Software configuration:** Based on the deployment mode chosen, Ansible Playbooks are created which will install the software required for running the benchmark inside the VMs.
4. **Software installation:** Ansible executes the Playbooks to install software such as Kubernetes and KubeEdge inside the VMs. Then, the Kubernetes/KubeEdge clusters are initialized, with worker machines joining a single control plane machine. Finally, applications are deployed on the edge workers through Kubernetes' control plane. These applications wait for endpoints to send data for processing.
5. **Endpoint configuration** Based on the command line arguments given by the user, a certain number of endpoints have to be created per edge node worker. The required Docker images are pulled and prepared for deployment.
6. **Endpoint deployment:** Docker containers are launched, containing endpoint applications which send data to edge workers for processing. 

After these steps have been executed succesfully, the benchmark gathers metrics such as execution time, scheduling overhead, and network latency, processes the raw numbers and presents an evaluation of the benchmark to the user.

## Installation
Please follow these steps to install the required software. For the installation and usage we assume the use of Ubuntu 20.04.

1. [Install](https://docs.docker.com/get-docker/) Docker on each physical machine (tested with v20.10.8)
2. [Libvirt-only] [Install](https://help.ubuntu.com/community/KVM/Installation) KVM, QEMU and LibVirt on each physical machine (tested with v4.2.1 and v6.1.0).<br>
    [Terraform] [Install](https://learn.hashicorp.com/tutorials/terraform/install-cli) Terraform (tested with v1.0.6)
3. [Install](https://docs.ansible.com/ansible/latest/installation_guide/intro_installation.html) Ansible on each physical machine (tested with v2.9.6). This requires Python 3 (tested with v3.8.10).
    * Add the following to ansible.cfg (for Ubuntu 20.04: /etc/ansible/ansible.cfg): 
        * Under `[ssh_connection]`, add `retries = 5`
        * Under `[defaults]`, add `callback_whitelist = profile_tasks`
    * Install the Python package Numpy using `pip3 install numpy`
4. [Libvirt-only] A network bridge is required when using the Libvirt-only framework, even when running on a single physical machine. See NETWORK.md for a guide on how to configure a network bridge.

## Usage
Please follow these steps to run the Edge Continuum Benchmark. The execution of the benchmark may take some time (>5min) as the benchmark suite handles everything from starting up virtual machines to running benchmark applications. In case you want to use this benchmark with multiple physical machines so as to deploy more VMs and containers, execute these steps on a single host machine which has ssh access to all other machines.

1. Clone this repository: `git clone ...`
2. Change directories to the edge resource manager you want to benchmark (example: `cd KubeEdge`)
3. Run the main python script to start the benchmark: `python3 main.py`. For more information on how to use the script, see `python3 main.py -h`.

### Examples
Examples on how to run the benchmark, with the expected output.

**Example 1**<br>
Here we use the edge deployment mode with the Libvirt-only infrastructure framework and an image classification application. On a single physical machine we deploy 1 cloud node for the Kubernetes control plane (4 cores/VM), 2 edge worker nodes (2 cores/VM), and 6 endpoints (3 endpoints/edge node, 1 core/endpoint).

    git clone https://github.com/EdgeVU/edge-benchmark-RM.git
    cd edge-benchmark-RM/KubeEdge
    python3 main.py --edgenodes 2 --endpoints 3 -m edge image-classification

    Logging has been enabled. Writing to stdout and file at ../logs/2021-11-16_15:53:05_edge_image-classification.log
    Initialize machine objects
    Check hardware of node local
    Trying to schedule all cloud / edge / endpoint nodes on the available hardware
    Set the IPs and names of all VMs for each physical machine
    ------------------------------------------------------------------------------
    Schedule of VMs and containers on physical machines
    ------------------------------------------------------------------------------
    Machine                        Cloud nodes     Edge nodes      Endpoints      
    local                          0               2               6              
    ------------------------------------------------------------------------------
    Generate configuration files for QEMU and Ansible
    Create SSH keys to be used with VMs
    Create a temporary directory for generated files
    Generate Ansible inventory file for physical machines
    Generate Ansible inventory file for VMs
    Start writing QEMU config files for cloud / edge
    Start copying files to all nodes
    Setting up the infrastructure
    Start VM creation using QEMU
    Check if a new OS image needs to be created
    Check if a new base image needs to be created
    Start adding ssh keys to the known_hosts file for each VM
    Install software on the infrastructure
    Start KubeEdge cluster on Vms
    Create local Docker registry
    Start subscribers on edge nodes
    Start subscriber pods on edge
    Deploy MQTT subscribers on the edge via the cloud frontend
    Deployed 2 edge applications
    Wait for subscriber applications to be completed
    Start publishers in Docker containers
    Deploy Docker containers on endpoints with publisher application
    Launch endpoint 0 for edge node edge0
    Launch endpoint 1 for edge node edge0
    Launch endpoint 2 for edge node edge0
    Launch endpoint 0 for edge node edge1
    Launch endpoint 1 for edge node edge1
    Launch endpoint 2 for edge node edge1
    Wait on all endpoint containers to finish
    Extract output from endpoint publishers
    Get output from endpoint: edge0_endpoint0
    Get output from endpoint: edge0_endpoint1
    Get output from endpoint: edge0_endpoint2
    Get output from endpoint: edge1_endpoint0
    Get output from endpoint: edge1_endpoint1
    Get output from endpoint: edge1_endpoint2
    Benchmark has been finished, prepare results
    Gather output from subscribers
    Parse output from worker node 0
    Parse output from worker node 1
    Parse output from endpoint edge0_endpoint0
    Parse output from endpoint edge0_endpoint1
    Parse output from endpoint edge0_endpoint2
    Parse output from endpoint edge1_endpoint0
    Parse output from endpoint edge1_endpoint1
    Parse output from endpoint edge1_endpoint2
    ------------------------------------
    EDGE OUTPUT
    ------------------------------------
    edge node 0: start_time 11/16/2021, 16:00:45.989808 | end_time 11/16/2021, 16:02:08.778294 | total_time 0:01:22.788486 | network delay avg (ms) 129.11264944444443 | network delay stdev (ms) 84.97243780260717
    edge node 1: start_time 11/16/2021, 16:00:47.401314 | end_time 11/16/2021, 16:02:07.681022 | total_time 0:01:20.279708 | network delay avg (ms) 158.56895222222224 | network delay stdev (ms) 166.92726291502984
    ------------------------------------
    ENDPOINT OUTPUT
    ------------------------------------
    Endpoint connected to worker 0: start_time 11/16/2021, 16:00:56.787922 | end_time 11/16/2021, 16:01:00.985858 | total_time 0:00:04.197936
    Endpoint connected to worker 0: start_time 11/16/2021, 16:00:57.176007 | end_time 11/16/2021, 16:01:01.388375 | total_time 0:00:04.212368
    Endpoint connected to worker 0: start_time 11/16/2021, 16:00:57.506413 | end_time 11/16/2021, 16:01:01.693048 | total_time 0:00:04.186635
    Endpoint connected to worker 1: start_time 11/16/2021, 16:00:57.831019 | end_time 11/16/2021, 16:01:02.000177 | total_time 0:00:04.169158
    Endpoint connected to worker 1: start_time 11/16/2021, 16:00:58.152779 | end_time 11/16/2021, 16:01:02.301325 | total_time 0:00:04.148546
    Endpoint connected to worker 1: start_time 11/16/2021, 16:00:58.470124 | end_time 11/16/2021, 16:01:02.629707 | total_time 0:00:04.159583
