# Continuum
Continuum is a deployment and benchmarking framework for the edge continuum. Continuum automates setting up an edge continuum environment on virtual machines, emulates network latency and throughput between machines, manages software installations inside the emulated environment, and performs application- and system-level benchmarks.

## How it works
Continuum has the following architecture:

<div align="center">
    <img src="./docs/images/architecture.png" width = "50%" align="center">
</div>
<br>

The execution flow consists of three phases, each having a configuration and execution step. These phases are **infrastructure deployment**, **software installation**, and **benchmarking**. Each phase is optional, i.e., the framework can be used for infrastructure deployment without any pre-installed software if so desired.

1. **Infrastructure configuration:** Libvirt configuration files for QEMU/KVM are created based on the user's preferences.
2. **Infrastructure execution:** The configuration files are executed, creating QEMU/KVM virtual machines connected through network bridges.
3. **Software configuration:** Ansible is configured for software installation based on the configured infrastructure.
4. **Software execution:** Ansible playbooks are executed, installing operating services and resource management software on each machine. This step includes setting up resource management clusters such as Kubernetes.
5. **Benchmark configuration** The benchmark is configured and prepared based on the user's preferences.
6. **Benchmark execution:** Applications (encapsulated in containers) are executed using resource managers running on the emulated infrastructure (Kubernetes, KubeEdge, etc.). Meanwhile, application- and system-level metrics are captured, processed, and presented to the user.

## Demo
The framework supports execution on multiple physical machines through a network bridge.
Continuum has been tested on Ubuntu 20.04. Recommended software versions are noted below.
We present a demo of this framework in three steps:

1. Prepare the environment
2. Install the framework
3. Use the framework

For this demo, we will install the framework inside a QEMU/KVM virtual machine running Ubuntu 20.04.
If you have access to a Ubuntu 20.04 machine yourself, you can skip part 1, prepare the environment, and start at part 2.

### Part 1: Prepare the environment
As the Continuum framework requires Ubuntu 20.04, we prepare a virtual machine with this operating system in this step.
The only requirement for this part is QEMU/KVM and Libvirt.
You can execute this part on any operating system that supports these software packages; our demo focuses on Ubuntu 20.04.
This part can be executed on any 


n this part we will explain how to install a Ubuntu 20.04 virtual machine that will be used to run the framework in. While this works perfectly fine to demonstrate the functionalities of the framework, running the framework inside a virtual machine will result in worse performance compared to running it directly on the host machine.

For this tutorial, you only need a single machine. The framework does support execution across multiple machines, but this is outside of the scope of this tutorial. For more information, see the network readme for an explanation of how to set up a network bridge.






## Installation

1. [Install](https://docs.docker.com/get-docker/) Docker on each physical machine (tested with v20.10.8)
2. Install KVM, QEMU and LibVirt on each physical machine (QEMU v4.2.1 or v6.1.0).<br>
    * For execution on a single physical machine, the virtual network bridge virbr0 will be used. Most often, this will be automatically configured when installing KVM/QEMU/LibVirt.
    * For execution on multiple physical devices, a network bridge br0 is required. This requires extra configuration, see `docs/NETWORK.md`.
    * Run `export LIBVIRT_DEFAULT_URI="qemu:///system"` and/or add to your .bashrc or similar.
3. Install Python 3 (v3.8.10).
    * Install the following packages: `numpy pandas`. For reproducing experiments from our work, `matplotlib` is required as well.
3. [Install](https://docs.ansible.com/ansible/latest/installation_guide/intro_installation.html) Ansible on each physical machine (tested with v2.9.6).
    * Add the following to ansible.cfg (typically in /etc/ansible/ansible.cfg): 
        * Under `[ssh_connection]`, add `retries = 5`
        * Under `[defaults]`, add `callback_whitelist = profile_tasks`

Please read `docs/ISSUES.md` when encountering issues during the installation or usage of the framework.

## Usage
Please follow these steps to run the framework. The framework needs to be executed on a single physical machine, even if you want to make use of multiple physical machines.

1. Clone this repository: `git clone ...`
2. Change directories to the edge resource manager you want to benchmark (example: `cd KubeEdge`)
3. Run the main python script to start the benchmark: `python3 main.py`. For more information on how to use the script, see `python3 main.py -h`.



## Demo
