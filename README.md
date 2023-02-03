# Continuum
>  Automate Cloud-Edge Infrastructure Deployments and Benchmarks with Continuum. 
> 1. **Infrastructure deployment**: Create and manage virtual compute continuum infrastructure on the cloud or local hardware.
> 2. **Software installation**: Automatically install complex software deployment on the provided infrastructure.
> 3. **Benchmark execution**: Execute application- and system-level benchmarks on the compute continuum deployment.

Quick Jump: [How It Works](#how-it-works) | [Repository Structure](#repository-structure) | [Setup](#setup) | [Installation](#installation) | [Simple Example](#simple-example-15-minutes) | [Appendix](#appendix-a-create-an-ubuntu-2004-vm)

<div align="right">
    <img src="./docs/images/architecture.png" width = "30%" align="right">
</div>
<br>

## How It Works
Continuum has the following execution flow:
1. **Infrastructure configuration:** Users define their desired deployment using Continuum's configuration files, which internally get translated to configurations for the infrastructure provider of choice (e.g., QEMU, Google Cloud).
2. **Infrastructure execution:** The provider creates the requested infrastructure with virtual machines and networks.
3. **Software configuration:** Selected software installation scripts are configured and loaded using Ansible.
4. **Software execution:** Ansible playbooks are executed, installing and configuring software for operating services and resource management on each machine. 
5. **Benchmark configuration** A user-defined benchmark is configured and prepared.
6. **Benchmark execution:** Containerized applications are executed directly (via Docker or Containerd) or via a resource manager (Kubernetes, KubeEdge, etc.). Key metrics are captured, processed, and presented to the user.

## Repository Structure
The Continuum repository has the following structure:

* [application](./application/): Source code of our benchmark applications. The built containers are hosted on DockerHub.
* [benchmark](./benchmark/): Code for benchmark setup, execution, and output processing.
* [configuration](./configuration/): Input configuration files for Continuum, including a test framework.
* [configuration_parser](./configuration_parser/): Code for parsing the configuration files.
* [docs](./docs/): Documentation on how to use Continuum, and fixes for recurring system-issues.
* [execution_model](./execution_model/): Code for deploying the serverless execution model using OpenFaaS.
* [infrastructure](./infrastructure/): Code for managing infrastructure providers.
* [resource_manager](./resource_manager/): Code for managing distributed services and resource managers (e.g., Kubernetes).
* [scripts](./scripts/): Scripts for replicating paper evaluations.

## Setup (0 - 15 minutes)
For this demo, we will use Continuum with Google Cloud Platform (GCP) as the infrastructure provider of choice.
We use GCP over QEMU, the infrastructure provider used in our CCGRID paper, as it provides similar functionality and benchmark results, but is much easier to set up.
QEMU requires the user to have powerful hardware and perform complex installation and configuration steps.
With GCP, infrastructure provisioning is handled in the cloud, easing the burden of the user.

Continuum with GCP requires the user to have a single computer with internet access.
Continuum has been tested with the Ubuntu 20.04 operating system, and it is highly recommended to use this operating system to replicate our results.
Other operating systems can potentially work as the main software requirements of our framework (Docker, Python, Ansible) are available on many operating systems - however, we can't guarantee successful operation.
In the absence of a physical machine with Ubuntu 20.04, a virtual machine can be used.
Any virtual machine provider can be used - we provide an example at the bottom of this README of how to create a Ubuntu 20.04 virtual machine on a physical Ubuntu installation using QEMU.

## Installation ()
Install Continuum's software requirements on your Ubuntu 20.04 machine.
We tested with Docker 20.10.12, Python 3.8.10, and Ansible 2.13.2.

1. Install Docker:
    ```bash
    # 1. Install from the repository:
    # https://docs.docker.com/engine/install/ubuntu/

    # 2. Manage Docker as a non-root user
    # https://docs.docker.com/engine/install/linux-postinstall/#manage-docker-as-a-non-root-user

    # 3. Enable HTTP support
    hostname -I
    # - Select the first IP from this list - this is your machine's IP
    # - Replace the IP_HERE variable with your IP
    sudo mkdir /etc/docker
    sudo touch /etc/docker/daemon.json
    echo '{ "insecure-registries":["IP_HERE:5000"] }' | sudo tee -a /etc/docker/daemon.json
    sudo systemctl restart docker
    ```
2. Install Pip:
    ```bash
    sudo apt install python3-pip
    ```
3. Install Ansible
    ```bash
    sudo apt install ansible
    sudo sed -i '/# command_warnings = False/c\command_warnings = False' /etc/ansible/ansible.cfg
    sudo sed -i '/#callback_whitelist = timer, mail/c\callback_whitelist = profile_tasks' /etc/ansible/ansible.cfg
    ```
4. Install Continuum
    ```bash
    git clone https://github.com/atlarge-research/continuum.git
    cd continuum 
    git checkout CCGRID2023-Artifact-Evaluation
    pip3 install -r requirements.txt

    # Make sure the SSH directory and files are there
    mkdir ~/.ssh
    touch ~/.ssh/known_hosts
    ```
5. Prepare Continuum for Google Cloud usage
    ```bash
    # 1. Get your projectID from GCP (example: continuum-project-123456)
    # https://cloud.google.com/resource-manager/docs/creating-managing-projects

    # 2. Download your GCP credentials
    # https://cloud.google.com/iam/docs/creating-managing-service-account-keys

    # Update all Continuum's configuration files with your GCP information
    cd configuration
    python3 gcp_update.py --help
    # ----------------------------------------------------------------------------------------------
    # Update: create file, show help here, and example command
    # ----------------------------------------------------------------------------------------------
    # ----------------------------------------------------------------------------------------------
    # ----------------------------------------------------------------------------------------------
    ```

## Simple Example (2 x 15 minutes)
First, we execute a simple example to see what Continuum can do:
```bash
cd continuum
python3 continuum.py configuration/gcp_cloud_kubernetes_benchmark.cfg
```
Continuum attempts to start a Kuberentes cluster on Google Cloud, using 2 cloud VMs (one for the control plane, one as a worker) and 1 endpoint VM (the user that offloads data to the cloud).
When Continuum is done, it will output the results of the performed benchmark, similar to this:
```bash

```
Finally, it outputs SSH commands that can be used to SSH into the 




### Part 3: Use the framework
Inside the continuum framework:

1. Check the input parameters of the framework: `python3 continuum.py -h`.
2. The configuration files are stored in /configuration. Check /configuration/template.cfg for the template that these configuration files follow.
3. Run one of these configurations, such as a simple edge computing benchmark: `python3 continuum.py -v configuration/bench_edge.cfg`
4. If the program executes correctly, the results will be printed at the end, as well as the ssh commands needed to log into the created VMs.

### Part 4: Install OpenFaaS
In this part, you will setup [OpenFaaS](https://docs.openfaas.com/), a serverless framework, in the Kubernetes cluster that `Continuum` created for you.  
For the moment, we only allow OpenFaaS to be installed outside of the framework. In the future, we will integrate it in the framework.

1. Run Continuum with a configuration for OpenFaas. The `resource_manager_only = true` flag and `model = openFaas` in section `execution_model` is critical here.
    ```bash
    python3 continuum.py configuration/bench_openfaas.cfg
    ```

2. From your host-system ssh onto the `cloud_controller` node, for example:
   ```bash
   ssh cloud_controller@192.168.100.2 -i ~/.ssh/id_rsa_continuum
   ```

3. On the `cloudcontroller` make port 8080 from the Kubernetes cluster available on the node:
   ```bash
   nohup kubectl port-forward -n openfaas svc/gateway 8080:8080 &
   ```
   After execution, hit `Strg+C` to exit the dialog.

4. Give the `fass-cli` access to the OpenFaas deployment:
   ```bash
   PASSWORD=$(kubectl get secret -n openfaas basic-auth -o jsonpath="{.data.basic-auth-password}" | base64 --decode; echo)
   echo -n $PASSWORD | faas-cli login --username admin --password-stdin
   ```

Congratulations! As long as you don't reset the cluster, you can now access the OpenFaas deployment through the `cloudcontroller` node and `faas-cli`.  

You can test your installation by deploying and running a simple function, [figlet](https://github.com/jmkhael/faas-figlet). Figlet echos its input back to the user as an ASCII-banner.  
For now, we will use the command line to deploy the function. For a real-world scenario, this might not be desireable and you should use a yaml file to do your deployments like Johnny does in [his tutorial](https://jmkhael.io/create-a-serverless-ascii-banner-with-faas/). Why is that?

Deploy figlet to OpenFaaS
```bash
faas-cli store deploy figlet
```
If everthing went well, you should now see it in the list of functions:
```bash
faas-cli list
```

Now it's time to execute your first serverless function:
```bash
curl http://localhost:8080/function/figlet -d 'Hello world!'
```

---
Please read the documentation in /docs when encountering issues during the installation or usage of the framework.

---


# Appendix A: Create an Ubuntu 20.04 VM
This code snippet shows how to create an Ubuntu 20.04 VM on a physical Ubuntu installation.
```bash
#-------------------------------------
# 1. Install the QEMU stack
sudo apt update 
sudo apt install qemu-kvm libvirt-daemon-system libvirt-clients bridge-utils

# Add your user to the libvirt and kvm user group
sudo adduser [username] libvirt
sudo adduser [username] kvm

# Verify that the installation was succesful.
qemu-system-x86_64 --version
sudo systemctl status libvirtd

# If the libvirtd daemon isn't running, do:
sudo systemctl enable --now libvirtd

#-------------------------------------
# 2. Create the Ubuntu 20.04 VM (requirees 20GB in this example - lower can possibly also work)
wget https://releases.ubuntu.com/20.04.3/ubuntu-20.04.3-live-server-amd64.iso
qemu-img create -f qcow2 ubuntu.img 20G

#-------------------------------------
# 3. Boot the VM - example with 4 CPU cores and 8 GB memory (Continuum can work with less)
# On a physical system with a GUI:
sudo qemu-system-x86_64 -hda ubuntu.img --enable-kvm -m 8G -smp 4 -boot d -cdrom ubuntu-20.04.3-live-server-amd64.iso -cpu host -net nic -net user

# On a system without a GUI:
sudo qemu-system-x86_64 -hda ubuntu.img --enable-kvm -m 8G -smp 4 -boot d -cdrom ubuntu-20.04.3-live-server-amd64.iso -cpu host -net nic -net user,hostfwd=tcp::7777-:22
# - Open an SSH session from a machine with a GUI to the GUI-less machine using "ssh -X"
# - Install and run remmina on the GUI-less machine
sudo apt install remmina
remmina
# - This should open a window on your machine with GUI
# - Click on the + icon to create a new connection. Under protocol, select “VNC”, and then under server, add the VNC address displayed in the terminal where you started the VM (for example, 127.0.0.1:5900). Click save and connect to connect to the VM.
#-------------------------------------

# 4. Initialize the VM - don't forget to install an SSH client, and remember your username + password

# 5. Shutdown the VM once it's initialized, and launch again
sudo qemu-system-x86_64 -hda ubuntu.img --enable-kvm -m 8G -smp 4 -cpu host -net nic -net user,hostfwd=tcp::8888-:22 --name ubuntu
# - On a system with GUI: A new screen will open for your VM
# - On a system without GUI (or if you prefer a terminal): Do "ssh [username]@localhost -p 8888"
```