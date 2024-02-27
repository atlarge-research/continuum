# Continuum
Continuum is a deployment and benchmarking framework for the edge-cloud compute continuum.
Continuum offers the following features:

1. Continuum automates the creation of a cluster of cloud, edge, and endpoint virtual machines to emulate a compute continuum environment.
2. Users can freely configure the specifications of the virtual machines and the network connecting them through a single configuration file.
3. Continuum automatically installs operating services, resource managers, and applications inside the emulated cluster based on the user's preference. Supported operating services include MQTT, resource managers include Kubernetes, KubeEdge, and OpenFaaS, and applications include machine learning.
4. Continuum can automatically benchmark the resource managers and applications installed in the emulated cluster, and report metrics and logs back to the user.
5. Continuum is easily extendable, allowing users to add support for more infrastructure providers, operating services, resource managers, and applications.

## Features
Continuum supports the following software:

1. **Infrastructure**: Virtual machine provisioning through QEMU/KVM on local bare-metal devices.
2. **Operating Services**: Continuum can set up an MQTT broker on edge device for lightweight communication to endpoint users.
3. **Resource Manager**: Continuum can deploy containerized applications via Docker and Containerd using the resource managers Kubernetes and KubeEdge. OpenFaaS is supported for deploying serverless functions.
4. **Applications and application back-ends**: Continuum supports any application that can be deployed on VMs, containers, or serverless functions. As an example, a machine learning application is included.

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

## Who Uses Continuum
The Continuum framework has been used for scientific research, leading to (i) publications, (ii) Bachelor and Master of Science projects and theses, (iii) has been the topic of multiple demos, and (iv) has been awarded artifact reproducibility badges. More information on the Continuum project and its contributors can be found [here](https://atlarge-research.com/continuum/).

### Citation
When using Continuum for research, please cite the work as follows:
```
@inproceedings{2023-jansen-continuum,
    author    = {Matthijs Jansen and
                 Linus Wagner and
                 Animesh Trivedi and
                 Alexandru Iosup},
    title     = {Continuum: Automate Infrastructure Deployment and Benchmarking in the Compute Continuum},
    booktitle = {Proceedings of the First FastContinuum Workshop, in conjuncrtion with ICPE, Coimbra, Portugal, April, 2023},
    year      = {2023},
    url       = {https://atlarge-research.com/pdfs/2023-fastcontinuum-continuum.pdf},
}
```
The presentation slides of this work can be found [here](https://atlarge-research.com/talks/2023-continuum-framework-fastcontinuum.html)

Other work on the Continuum framework includes:
```
@inproceedings{2023-jansen-refarch,
    author    = {Matthijs Jansen and
                 Auday Al-Duilamy and
                 Allesandro Vittorio Papadopoulos and
                 Animesh Trivedi and
                 Alexandru Iosup},
    title     = {The {SPEC-RG} Reference Architecture for the Compute Continuum},
    booktitle = {The 23rd IEEE/ACM International Symposium on Cluster, Cloud and Internet Computing, CCGRID 2023, Bangalore, India, May 1-4, 2023},
    year      = {2023},
    url       = {https://atlarge-research.com/pdfs/2023-ccgrid-refarch.pdf},
}
```
The presentation slides of this work can be found [here](https://atlarge-research.com/talks/pres-2022-compsys-mjansen.html) and [here](https://atlarge-research.com/talks/poster-2022-ictopen-mjansen.html).

### Student Work
The Continuum framework has been used by many students from the Vrije University Amsterdam:

**Bachelor Thesis**
* Daniel Berzak: Embedded Domain Specific Language: A Streamlined Approach for Framework Abstraction

**Master Thesis**
* Edgardo Reinoso Campos: Serverless Computing at the Edge in Precise Agriculture (ongoing)
* Antonios Sklavos: Exploring the Performance-Isolation Trade-off for Isolation Mechanisms (ongoing)
* Tim van Kemenade: A Comparison of Scheduling Algorithms in the Compute Continuum (ongoing)

**Student Research Projects**
* Felix Goosens: Edge Continuum Framework on an ARM Raspberry Pi Cluster
* David Freina et al: Serverless Computing in the Edge Continuum
* Andreas Frangos et al: Performance Variability and Resource Analysis in Serverless Applications

### Demo
The Continuum framework has been part of four classes with a demo, organized by the VU Amsterdam Bachelor and Master program Computer Science, as well as the Dutch Research School for high-quality research and education in computer systems and Imaging (ASCI).

for over 100 students and researchers in total. Specifically, it has been demoed in the following occasions:
* Distributed Systems (2021) - Part of the VU Amsterdam MSc program Computer Science
* ASCI A24 (2022) - A course in the Dutch Research School for high-quality research and education in computer systems and Imaging (ASCI)
* Distributed Systems (2022) - Part of the VU Amsterdam MSc program Computer Science
* ASCI A22 (2023) - A course in the Dutch Research School for high-quality research and education in computer systems and Imaging (ASCI)
* Computer Networks (2023) - Part of the VU Amsterdam BSc program Computer Science

<p>
  <img src="./docs/images/Open_Research.png" width="100" align="right" />
  <img src="./docs/images/Research_Objects.png" width="100" align="right" />
</p>

### Artifact
The Continuum framework has been awarded the IEEE reproducibility badges for Open Research Objects (ORO) and Reusable/Research Objects Reviewed (ROR).
These badges have been awarded by independent reviewers as part of the CCGRID 2023 Artifact Track.
For more information on these badges, see [here](https://ccgrid2023.iisc.ac.in/call-for-artifacts/).
The code and instructions for this artifact are available on GitHub [here](https://github.com/atlarge-research/continuum/tree/CCGRID2023-Artifact-Evaluation). 

## Demo
Continuum supports multiple virtual machine infrastructure deployment platforms, most notably QEMU for execution on local hardware or Google Cloud for execution in the cloud.
In this demo, we present how to use Continuum using QEMU. 
If you want to use Google Cloud instead, which requires much fewer installation steps, please see the extensive README [here](https://github.com/atlarge-research/continuum/tree/CCGRID2023-Artifact-Evaluation).

This demo requires a single machine and a Linux operating system that supports QEMU/KVM and Libvirt.
We recommend running the demo on an Ubuntu 20.04 machine. 
If you don't have access to such a machine, see the Appendix for tips on how to install this in a VM.
We recommend installing the framework bare-metal for more reliable performance metrics.

The demo contains two parts:

1. Install the framework
2. Use the framework

In part one, we install the Continuum framework and use the framework in part 2.
The framework does support execution on multiple physical machines through a network bridge.
We leave this multi-machine execution out of this tutorial; consult the documentation for more information.
For more questions, open a GitHub Issue or mail m.s.jansen@vu.nl.

Software versions tested:

- QEMU 6.1.0
- Libvirt 6.0.0
- Docker 20.10.12
- Python 3.8.10
- Ansible 2.13.2

### Part 1: Install the framework
We start by installing all requirements for the Continuum framework.
We assume the operating system is Ubuntu 20.04, either natively or via a VM.

```bash
# 1. Install the VM requirements
sudo apt update
sudo apt install qemu-kvm libvirt-daemon-system libvirt-clients bridge-utils

# 1.1. Give your user sufficient permissions
# After these steps, refresh you session to make the group addition take effect.
sudo adduser $USER libvirt
sudo adduser $USER kvm

# 1.2. Check if the installation was succesful
# If not, you may need to use `sudo systemctl enable --now libvirtd`
qemu-system-x86_64 --version
sudo systemctl status libvirtd

# 1.3. Force libvirt to use QEMU.
echo 'export LIBVIRT_DEFAULT_URI="qemu:///system"' >> ~/.bashrc
source ~/.bashrc

# 2. Install Docker (see Docker website for alternative instructions)
sudo apt-get install ca-certificates curl gnupg lsb-release

sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | \
    sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install docker-ce docker-ce-cli containerd.io docker-compose-plugin

# After these steps, refresh you session to make the group addition take effect.
sudo groupadd docker
sudo usermod -aG docker $USER
sudo systemctl enable docker.service
sudo systemctl enable containerd.service
# Now refresh you SSH session by logging in / out

# Continuum creates a local docker registry using http
# Http support needs to be enabled
http_ip=$(hostname -I | awk '{print $1;}')
echo '{ "insecure-registries":["${http_ip}:5000"] }' | sudo tee -a /etc/docker/daemon.json
sudo systemctl restart docker

# 3. Install the Continuum framework
mkdir ~/.ssh
touch ~/.ssh/known_hosts

git clone https://github.com/atlarge-research/continuum.git
cd continuum

# 4. Install Python and some packages, including Ansible
sudo apt install python3 python3-pip
pip3 install -r requirements.txt

# 5. Edit the Ansible configuration as follows:
# Under `[defaults]`, add `callback_enabled = profile_tasks`
# Under `[defaults]`, add `command_warnings = False`
sudo vim /etc/ansible/ansible.cfg

# 6. Setup up bridged networking on the machine
# First, delete any virtual bridges
virsh net-destroy default
virsh net-undefine default

# Check that no bridges exist anymore
virsh net-list --all

# Now create the new bridge itself
# Make a backup of the old network settings, then edit the new one
# Use `ip -a` to find the name of your network interface, for example, ens3
# and to find its IP, for example, 10.0.2.15
# Find the gateway address using `ip r` (the first IP on the first line)
# An example command could look like this:
sudo cp /etc/netplan/00-installer-config.yaml /etc/netplan/00-installer-config.yaml.bak

sudo su
cat > /etc/netplan/00-installer-config.yaml <<EOF
network:
    ethernets:
    ens3:
        dhcp4: false
        dhcp6: false
    bridges:
    br0:
        interfaces: [ens3]
        addresses: [10.0.2.15/16]
        gateway4: 10.0.2.2
        nameservers:
        addresses: [1.1.1.1, 8.8.8.8]
        search: []
        parameters:
        stp: true
        dhcp4: false
        dhcp6: false
    version: 2
EOF
exit

# Apply the changes
sudo netplan generate
sudo netplan apply

# Check if the bridge br0 was successfully created
# And check that the network interface, for example, ens3, doesn't have an IP listed anymore, but br0 does instead.
brctl show
ip a

# Enable IP forwarding
sudo su
cat >> /etc/sysctl.conf <<EOF
net.bridge.bridge-nf-call-ip6tables = 0
net.bridge.bridge-nf-call-iptables = 0
net.bridge.bridge-nf-call-arptables = 0
EOF
exit

# Then execute this command
sudo sysctl -p /etc/sysctl.conf
```

### Part 2: Use the framework
Continuum comes with many pre-made configuration files that can be used to deploy infrastructures and benchmark with Continuum. You can find these files in `/configuration`.
For example:
1. Go the the continuum framework: `cd continuum`
2. Check how the framework can be used: `python3 continuum.py --help`
3. We use a configuration that deploys 2 virtual machines, installs Kubernetes on them, and starts a third machine that emulates an IoT device that sends data periodically to the Kubernetes cluster for processing. The framework starts a processing application on the cluster, which processes the incoming data and sends the result back to the IoT device: `python3 continuum.py configuration/bench_cloud.cfg`.
4. If the program executes correctly, the results will be printed at the end, as well as the ssh commands needed to log into the created VMs.

Please explore what the Continuum framework can do, see `configuration/template.cfg` for a list of all configuration parameters. These include deploying infrastructure on Google Cloud, installing Prometheus and Grafana on VMs, or running serverless benchmarks. All components can be easily extended - open a GitHub Issue or send us a mail at m.s.jansen@vu.nl if you have any questions.

### Appendix
The Continuum framework is supposed to be run from an Ubuntu-like operating system.
The framework has been extensively tested on Ubuntu 20.04.
In this part, we show how to create an Ubuntu 20.04 VM that you can use to run Continuum in.
This example is supposed to be executed on a Linux machine.
```bash
# Install the VM software QEMU, KVM, and Libvirt
sudo apt update 
sudo apt install qemu-kvm libvirt-daemon-system libvirt-clients bridge-utils`

# Give your user sufficient permissions - this may require you to refresh your session
sudo adduser $USER libvirt
sudo adduser $USER kvm

# Check if the installation was succesful
# If not, you may need to use `sudo systemctl enable --now libvirtd`
qemu-system-x86_64 --version
sudo systemctl status libvirtd

# Download the Ubuntu 20.04 server image
wget https://releases.ubuntu.com/20.04.3/ubuntu-20.04.3-live-server-amd64.iso

# Create a QCOW disk as storage for your VM (at least 20 GB of disk space is advised)
qemu-img create -f qcow2 ubuntu.img 20G

# Boot the VM
# 1. On a system with a GUI
# - This will open a new window for the VM
# - Use at least 4 GB of RAM and 4 CPUs
sudo qemu-system-x86_64 -hda ubuntu.img --enable-kvm -m 8G -smp 4 -boot d -cdrom ubuntu-20.04.3-live-server-amd64.iso -cpu host -net nic -net user

# 2. On a system without a GUI
sudo qemu-system-x86_64 -hda ubuntu.img --enable-kvm -m 8G -smp 4 -boot d -cdrom ubuntu-20.04.3-live-server-amd64.iso -cpu host -net nic -net user,hostfwd=tcp::7777-:22

# 2.1. Access the VM from an OS with GUI: You can now SSH in to machine
ssh -p 7777 ubuntu@127.0.0.1

# 2.2 On the VM, execute remmina so you can see the GUI of the VM on your machine
sudo apt install remmina
remmina

# 2.3 This should open the Remmina screen for you. Click on the + icon to create a new connection. Under protocol, select “VNC”, and then under server, add the VNC address displayed in the terminal where you started the VM (for example, 127.0.0.1:5900). Click save and connect to connect to the VM.

-----
# Fininish the initialization of the VM
# Don't forget to install the open-SSH client during the installation
# Then, shut the VM down and re-launch
sudo qemu-system-x86_64 -hda ubuntu.img --enable-kvm -m 8G -smp 4 -cpu host -net nic -net user,hostfwd=tcp::7777-:22 --name ubuntu

# On a system with a GUI: The VM should open automatically
# On a system without a GUI: 
ssh [username]@localhost -p 7777
```

# Acknowledgment
This work is funded by NWO TOP OffSense (OCENW.KLEIN.209).
