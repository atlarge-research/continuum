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
This demo requires a single machine and a Linux operating system that supports QEMU/KVM and Libvirt.
The demo contains three parts:

1. Prepare the environment
2. Install the framework
3. Use the framework

In the first part, we prepare an Ubuntu 20.04 virtual machine using QEMU/KVM.
In part two, we install the Continuum framework inside this VM and finally use the framework in part 3.
If you have access to a machine with Ubuntu 20.04, you can skip part 1, "Prepare the environment", and start with part 2. 
Continuum has been tested on Ubuntu 20.04, and correct functioning on other operating systems can not be guaranteed.

If you want to use Continuum for research, you should install it directly on your machine, without using a virtual machine, as this reduces performance.
The framework does support execution on multiple physical machines through a network bridge.
We leave this multi-machine execution out of this tutorial; consult the documentation for more information.

Software versions tested:

- QEMU 6.1.0
- Libvirt 6.0.0
- Docker 20.10.12
- Python 3.8.10
- Ansible 2.13.2


### Part 1: Prepare the environment
We prepare a virtual machine with Ubuntu 20.04 in this step.
The only requirement for this part is installing QEMU/KVM and Libvirt.
You can execute this part on any operating system that supports these software packages; our demo focuses on Ubuntu 20.04.

1. Install requirements
    1. Install QEMU, KVM, and Libvirt: `sudo apt update && sudo apt install qemu-kvm libvirt-daemon-system libvirt-clients bridge-utils`
    2. Give permissions to LibVirt and KVM to run virtual machines (use your own username): `sudo adduser [username] libvirt &&` `sudo adduser [username] kvm`. You may need to log in and out to refresh your group memberships.
    3. Check if the installation was successful: `qemu-system-x86_64 --version`
    4. Check if libvirt is running: `sudo systemctl status libvirtd`. If not, activate it using `sudo systemctl enable --now libvirtd`
2. Download the Ubuntu 20.04 server image: `wget https://releases.ubuntu.com/20.04.3/ubuntu-20.04.3-live-server-amd64.iso`
3. Create a QCOW disk as storage for your VM: `qemu-img create -f qcow2 ubuntu.img 20G`
    1. At least 20 GB of disk space is required for this tutorial
4. Boot the VM
    1. On a system with a GUI: `sudo qemu-system-x86_64 -hda ubuntu.img --enable-kvm -m 8G -smp 4 -boot d -cdrom ubuntu-20.04.3-live-server-amd64.iso -cpu host -net nic -net user`
        1. This should automatically open up a new window for the VM.
        2. Memory requirements: At least 4 GB (in this example -m 8G = 8 GB)
        3. CPU requirements: At least 4 (in this example -smp 4 = 4 CPUs)
    2. On a system without a GUI: `sudo qemu-system-x86_64 -hda ubuntu.img --enable-kvm -m 8G -smp 4 -boot d -cdrom ubuntu-20.04.3-live-server-amd64.iso -cpu host -net nic -net user,hostfwd=tcp::7777-:22`
        1. Open up a new SSH session into the GUI-less machine using `ssh -X`. The machine that you are SSH’ing from should have a GUI.
        2. Install Remmina on the GUI-less machine: `sudo apt install remmina` and run Remmina `remmina`
        3. This should open the Remmina screen for you. Click on the + icon to create a new connection. Under protocol, select “VNC”, and then under server, add the VNC address displayed in the terminal where you started the VM (for example, 127.0.0.1:5900). Click save and connect to connect to the VM.
5. Initialize the VM: Do not forget to install the open-SSH client during the installation! Remember the username and password you create for later. You can ignore all (security) updates for this demo.
6. Shut the VM down once the initial setup is done, and launch again: `sudo qemu-system-x86_64 -hda ubuntu.img --enable-kvm -m 8G -smp 4 -cpu host -net nic -net user,hostfwd=tcp::8888-:22 --name ubuntu`
    1. On a system with a GUI: A new screen should automatically open, and after some time the VM will be done booting up. If you don’t want to use a GUI for the VM, open up a new terminal and use `ssh [username]@localhost -p 8888`
    2. On a system without  a GUI: Open up a new terminal and use `ssh [username]@localhost -p 8888`

### Part 2: Install the framework
We start installing all requirements for the Continuum framework.
We assume the operating system is Ubuntu 20.04, either natively or via a VM.

1. Install VM requirements
    1. Install QEMU, KVM and Libvirt: `sudo apt update && sudo apt install qemu-kvm libvirt-daemon-system libvirt-clients bridge-utils`
    2. Give permissions to LibVirt and KVM to run virtual machines (use your own username): `sudo adduser [username] libvirt` and `sudo adduser [username] kvm`. You may need to log in and out to refresh your group memberships.
    3. Check if the installation was successful: `qemu-system-x86_64 --version`. 
    4. Check if libvirt is running: `sudo systemctl status libvirtd`. If not, activate it using `sudo systemctl enable --now libvirtd`
2. Install Docker (see Docker website for alternative instructions)
    ```bash
    sudo apt-get install \
        ca-certificates \
        curl \
        gnupg \
        lsb-release
    
    sudo mkdir -p /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    
    sudo apt-get update
    sudo apt-get install docker-ce docker-ce-cli containerd.io docker-compose-plugin
    
    sudo groupadd docker
    sudo usermod -aG docker $USER
    sudo systemctl enable docker.service
    sudo systemctl enable containerd.service
    # Now refresh you SSH session by logging in / out
    
    # support https
    hostname -I # copy first IP in list, paste in next command under IP_HERE
    echo '{ "insecure-registries":["IP_HERE:5000"] }' | sudo tee -a /etc/docker/daemon.json
    sudo systemctl restart docker
    ```
    
3. Get Pip: `sudo apt install python3-pip`
4. Get Ansible: `sudo apt install ansible`
    1. Check if Ansible works: `ansible --version`
    2. Edit the ansible configuration: `sudo vim /etc/ansible/ansible.cfg`
        1. Under `[ssh_connection]`, add `retries = 5`
        2. Under `[defaults]`, add `callback_whitelist = profile_tasks`
5. Install the Continuum repository
    1. `git clone https://github.com/atlarge-research/continuum.git`
    2. Get python requirements: `cd continuum && pip3 install -r requirements.txt`
    3. Create an .ssh directory: `mkdir ~/.ssh`
    4. Create a known hosts file: `touch ~/.ssh/known_hosts`
6. Delete the virtual bridge
    1. `virsh net-destroy default` and `virsh net-undefine default`
    2. Check that virbr0 no longer exists: `virsh net-list --all`
7. Create a network bridge
    1. Make a backup of the current network configuration: `sudo cp /etc/netplan/00-installer-config.yaml /etc/netplan/00-installer-config.yaml.bak`
    2. Edit the network configuration to create a bridge (`sudo vim /etc/netplan/00-installer-config.yaml`). Use `ip a` to get your machine’s network interface (e.g., ens3, enp0s3) and IP (for this example, the IP listed under ens3) and `ip r` to get the gateway address (the first IP on the first line). An example file could look like this:
        
        ```bash
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
        ```
        
    3. Enforce this new network policy with `sudo netplan generate` and `sudo netplan apply`
    4. Use `brctl show` to check that bridge br0 now exists, and `ip a` to check that ens3 does not have a listed ip anymore, but br0 does instead.
    5. If your ip listed under “addresses” does not start with 192.168, one change in the framework is required: Edit main.py (vim main.py), search for the “add_constants” function and change config[”prefixIP”] to your prefix (e.g., for this example “10.0”
    6. Enable IP forwarding from VMs to the bridge
        
        ```bash
        # This is one command
        # If permission denied, execute "sudo su" first. 
        cat >> /etc/sysctl.conf <<EOF
        net.bridge.bridge-nf-call-ip6tables = 0
        net.bridge.bridge-nf-call-iptables = 0
        net.bridge.bridge-nf-call-arptables = 0
        EOF
        # If sudo su was used, do "exit" now
        
        # Then execute this command
        sudo sysctl -p /etc/sysctl.conf
        ```

### Part 3: Use the framework
Inside the continuum framework:

1. Check the input parameters of the framework: `python3 main.py -h`.
2. The configuration files are stored in /configuration. Check /configuration/template.cfg for the template that these configuration files follow.
3. Run one of these configurations, such as a simple edge computing benchmark: `python3 main.py -v configuration/bench_edge.cfg`
4. If the program executes correctly, the results will be printed at the end, as well as the ssh commands needed to log into the created VMs.

### Part 4: Install OpenFaaS
In this part, you will setup [OpenFaaS](https://docs.openfaas.com/), a serverless framework, in the Kubernetes cluster that `Continuum` created for you.  
For the moment, we only allow OpenFaaS to be installed outside of the framework. In the future, we will integrate it in the framework.

1. From your host-system execute the Ansible playbook to install OpenFaaS. Make sure that you are in the project root and that you have a cluster running with Kubernetes installed.
   ```bash
    ansible-playbook -i ~/.continuum/inventory_vms execution_models/openFaas.yml
   ```

2. From your host-system ssh onto the `cloudcontroller` node:
   ```bash
   ssh cloud_controller@192.168.122.10 -i ~/.ssh/id_rsa_benchmark 
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
