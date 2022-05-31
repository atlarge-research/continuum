# Issues
This document lists issues and known problems related to using the benchmark and installing the software needed for the benchmark. This list is not exhaustive. Please first read this document before contacting the authors.

General tips for debugging:
1. Check the generated log file in /edge-benchmark-RM/logs/<timestamp.log>.
2. If the benchmark hangs on an VM related command, delete the VMs (`virsh delete ...`), delete the VMs images and disks (in `/var/lib/libvirt/images`) and try running the benchmark again.

## Terrafrom (can also apply for Libvirt/KVM/QEMU)
For Terraform support, please contact the developers. Currently, Terraform support is not publicly available.

1. Command `terraform apply` outputs `Could not open '/var/lib/libvirt/images/<FILE_NAME>': Permission denied`

    You can find the solution here: [link](https://github.com/dmacvicar/terraform-provider-libvirt/commit/22f096d9). A restart may require the following command: `systemctl restart libvirtd.service` <br>
    If this does not work, move the storage pool to a non-root location (see known problems #3)

2. Command `terraform apply` outputs  `Error defining libvirt domain: operation failed: domain '<domain_name>' already exists with uuid ...`

    A VM is already running with this name and needs to be deleted first. If you do not know the name of the VM involved yet: `virsh list --all` <br>
    Then delete the domain: `virsh destroy <domain_name>` and `virsh undefine <domain_name>`

3. Command `terraform apply` outputs `Error: can't find storage pool 'default'`

    The storage pool for VM disks does not exist. [Create](https://serverfault.com/questions/840519/how-to-change-the-default-storage-pool-from-libvirt) a default storage pool. <br>
    This may cause some permission errors, which can be fixed by following [these steps](https://ostechnix.com/solved-cannot-access-storage-file-permission-denied-error-in-kvm-libvirt/) or by following known problems #1.

4. `Error creating libvirt volume for cloudinit device <name>.iso: storage volume <name>.iso exists already`

    In a succesful benchmark run, generated files get cleaned up. However, when a benchmark run crashes, intermediate files get left behind and need to be deleted by hand. In directory `/var/lib/libvirt/images/`, delete all generated .iso files manually.

5. `Can't retrieve network 'default'`

    Libvirt needs a default network to connect the VMs to. This network is called 'default', and usually gets created when installing Libvirt and associated packages. First, check if the following file exists: `/etc/libvirt/qemu/networks/default.xml`. If it does not exist, create the file:
    ```
    <network>
      <name>default</name>
      <uuid>9a05da11-e96b-47f3-8253-a3a482e445f5</uuid>
      <forward mode='nat'/>
      <bridge name='virbr0' stp='on' delay='0'/>
      <mac address='52:54:00:0a:cd:21'/>
      <ip address='192.168.122.1' netmask='255.255.255.0'>
        <dhcp>
          <range start='192.168.122.2' end='192.168.122.254'/>
        </dhcp>
      </ip>
    </network>
    ```
    Now use this file to create the network: 
    ```
    sudo virsh net-define --file default.xml
    sudo virsh net-start default
    sudo virsh net-autostart --network default
    ```
    Finally, check if the network has been correctly started: `virsh net-list`

## Libvirt/KVM/QEMU
1. During QEMU execution, output `error : cannot execute binary /usr/local/bin/qemu-img: Permission denied`
    
    [Add permission](https://github.com/kubevirt/kubevirt/issues/4303#issuecomment-830365183) to AppArmor 

2. Command `qemu-system-x86_64` (or any other qemu command) results in `IBVERBS_1.8 not found`

    This is a [known issue](https://docs.mellanox.com/display/MLNXOFEDv492240/Known%20Issues) related to QEMU and Mellanox on Ubuntu 20.04. This requires you to build QEMU from source instead of installing it via `apt install` (it comes with the qemu-kvm package).

    The following steps may be followed to install QEMU from source and make it work with the benchmark:
    ```
    # Install QEMU / KVM / LibVirt like usual: 
    # https://help.ubuntu.com/community/KVM/Installation

    # Build QEMU from source with spice support
    sudo apt install libspice-protocol-dev libspice-server-dev meson
    wget https://download.qemu.org/qemu-6.1.0.tar.xz
    tar xvf qemu-6.1.0.tar.xz
    rm qemu-6.1.0.tar.xz
    cd qemu-6.1.0/
    mkdir build
    cd build

    # Delete the QEMU files installed via the qemu-kvm package
    rm /usr/bin/qemu-*
    rm /usr/local/bin/qemu-*

    # This can be changed based on your system / OS
    ../configure --target-list=x86_64-softmmu --enable-kvm --enable-linux-aio  \
        --enable-trace-backend=log --disable-werror --disable-gtk --enable-spice
    make -j 

    # Now, either add the qemu binary to your PATH, 
    # or move it to the /bin folder. We show the latter here. 
    # Note that /local/bin, the default installation target, is most often not on PATH.
    make install
    mv /usr/local/bin/qemu-* /usr/bin/

    # Same with the /share folder
    rm -rf /usr/share/qemu
    mv /usr/local/share/qemu /usr/share/
    ```

3. VM can't be accessed, `Destination Host Unreachable` and/or `No route to host`

    There can be many reasons for VMs not being accessible, such as a network still being active in Libvirt
    ```
    # List all available networks in Libvirt
    virsh net-list

    # Delete (default) network
    virsh net-destroy default 
    virsh net-undefine default
    ```

4. CPU core pinning fails, `Unable to write to '/sys/fs/cgroup/cpuset/machine.slice/machine-qemu*/cpuset.cpus': Permission denied`

    CPU core pinning can only use those cores described in `/sys/fs/cgroup/cpuset/cpuset.cpus` and/or `/sys/fs/cgroup/cpuset/machine.slice/cpuset.cpus`.
    If one of these files does not contain `0-X` with X being the number of CPU cores on your machine - 1 (zero indexed), CPU core pinning will most likely fail.


## Docker
1. `server gave HTTP response to HTTPS client` after trying to pull a Docker container from a local registry

    The local Docker registry expects all requests to be HTTPS, while a request was made with type HTTP. We can disable this security featue by updating a Docker configuration file
    ```
    # Edit Docker configuration file
    vim /etc/docker/daemon.json

    # Result should be similar to the following, with registry_ip being the ip of the machine where the registry runs on
    { "insecure-registries":["registry_ip:5000"] }

    # Finish by restarting Docker
    systemctl restart docker
    ```
## Ansible
1. Benchmark hangs on Ansible Playbooks such as controller_startup.yml

    There can be many reasons for Ansible Playbooks to hang during execution, one of which is a bad network connection. If you can't ping the VM, then there most likely is a problem with the network bridge, see NETWORK.md. If you can ping the VM, the VM might not have an internet connection. This causes Ansible to hang when trying to download software from the internet. As described in NETWORK.md, execute the following:
    ```
    # Disable netfilter, which might block internet access to the VM
    # Important: First check if these lines are already there. 
    # If so, only execute the last command in this code snippet
    cat >> /etc/sysctl.conf <<EOF
    net.bridge.bridge-nf-call-ip6tables = 0
    net.bridge.bridge-nf-call-iptables = 0
    net.bridge.bridge-nf-call-arptables = 0
    EOF

    # Reset network filter
    sysctl -p /etc/sysctl.conf
    ```

2. Ansible Playbook crashes on permission denied error

    The framework should be executed without sudo, however the Ansible playbooks will execute commands with superuser rights (this is required for installing packages, booting up VMs, etc.). To make this work, you need to set up passwordless sudo access. On most operating systems this can be managed via the `sudo visudo` command, where the sudo/wheel group (depending on your OS the group name changes) should have `NOPASSWD: ALL` in the last column. Most often this option is commented out in the `sudo visudo` file in favor of a version without this option. Please comment the NOPASSWD version out, and comment out the out the other one.
