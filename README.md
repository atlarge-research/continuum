# Continuum
Continuum is a deployment and benchmarking framework for the edge continuum. It automates setting up and configuring emulated cloud, edge, and endpoint/IoT hardware and networks, manages installation of software inside the emulated environment, and can perform application- and system-level benchmarks.

## How it works
Continuum has the following architecture:

<div align="center">
    <img src="./docs/images/architecture.png" width = "85%" align="center">
</div>
<br>

The execution flow consists of three phases, each having a configuration and execution step. The phases are **infrastructure deployment**, **software installation**, and **benchmarking**. Each phase can be skipped, i.e. the framework can be used for infrastructure deployment only if so desired.

1. **Infrastructure configuration:** Libvirt or Terraform configuration files are created based on the user's preferences.
2. **Infrastructure execution:** The configuration files are executed, creating QEMU/KVM virtual machines connected through network bridges.
3. **Software configuration:** Based on the configured infrastructure, Ansible is configured for software installation. 
4. **Software execution:** Ansible playbooks are executed, installing operating services and resource management software on each machine. This includes setting up resource management clusters such as Kubernetes.
5. **Benchmark configuration** The benchmark is configured and prepared based on the user's preferences.
6. **Benchmark execution:** Applications in docker containers are executed on resource management software running on the emulated infrastructure (Kubernetes, KubeEdge, etc.). Meanwhile, application- and system-level metrics are captured and finally processed and presented to the user.

## Installation
The framework has been tested on both Ubuntu 20.04 and CentOS 7, and should support similar operating systems. Recommended software versions are noted below.

1. [Install](https://docs.docker.com/get-docker/) Docker on each physical machine (tested with v20.10.8)
2. Install KVM, QEMU and LibVirt on each physical machine (QEMU v4.2.1 or v6.1.0).<br>
   [Terraform] [Install](https://learn.hashicorp.com/tutorials/terraform/install-cli) Terraform (v1.0.6)
    * A network bridge is required. See `docs/NETWORK.md` for installation steps.
    * Run `export LIBVIRT_DEFAULT_URI="qemu:///system"` and/or add to your .bashrc or similar.
3. Install Python 3 (v3.8.10).
    * Install the following packages: `numpy matplotlib pandas`
3. [Install](https://docs.ansible.com/ansible/latest/installation_guide/intro_installation.html) Ansible on each physical machine (tested with v2.9.6).
    * Add the following to ansible.cfg (typically in /etc/ansible/ansible.cfg): 
        * Under `[ssh_connection]`, add `retries = 5`
        * Under `[defaults]`, add `callback_whitelist = profile_tasks`
    * On CentOS or similar, package dnf is required

Please read `docs/ISSUES.md` when encountering issues during the installation or usage of the framework.

## Usage
Please follow these steps to run the framework. The framework needs to be executed on a single physical machine, even if you want to make use of multiple physical machines.

1. Clone this repository: `git clone ...`
2. Change directories to the edge resource manager you want to benchmark (example: `cd KubeEdge`)
3. Run the main python script to start the benchmark: `python3 main.py`. For more information on how to use the script, see `python3 main.py -h`.
