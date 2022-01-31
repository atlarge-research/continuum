# Contributing
This file describes which technologies are used in this project and provides pointers to learn more about these technologies. It describes all technologies used in all different versions of the benchmark. Reading this file is not required when only using the benchmark but may deepen your understanding of the benchmark. It is advised to read this file if you want to contribute to this project.

Please read the other documentation files as well. These contain important information such as software versions, installation guides, and common issues.

## General information
This project makes use of:
* Kubernetes
* KubeEdge
* Terraform
* QEMU, KVM, Libvirt
* Ansible

The main functionality of this benchmark is four-fold:
* Setting up virtualized hardware to mimic real-world cloud-edge-endpoint infrastructure
* Deploying Kubernetes and KubeEdge on virtualized hardware
* Running applications on Kubernetes and KubeEdge, 
* Benchmark both the infrastructure, the resource managers, and the applications

The general execution plan of the benchmark is as follows: A user defines how many cloud/edge/endpoints VMs and containers have to be used, how many resources per virtualized resource should be allocated, etc. The program then generates either Terraform or QEMU configuration files and executes these configurations to create the virtual infrastructure. The use of Terraform or QEMU depends on which version of the benchmark you are using and on what hardware the benchmark is running. Kubernetes and KubeEdge are then installed on the virtual resources using Ansible configuration files. Afterward, the requested application is scheduled and run on the virtualized infrastructure using Kubernetes/KubeEdge. Finally, both system- and application-level metrics are gathered and presented to the user.

## Further information
Here we provide more information about the technologies used and provide pointers to more information.

### Kubernetes
Kubernetes is a cluster orchestration system for cloud and cloud-like infrastructure (minimum requirements are 2 CPU cores and 2 GB RAM).

More information
* [Kubernetes - Basics](https://kubernetes.io/docs/tutorials/kubernetes-basics/)
* [Kubernetes - Setup](https://kubernetes.io/docs/setup/)
* [Containers and Cloud: From LXC to Docker to Kubernetes (2014)](https://sicoya.com/wp-content/uploads/2016/07/07036275.pdf)

### KubeEdge
KubeEdge extends native containerized application orchestration capabilities to the Edge. It does this by extending the well-known cluster orchestration system Kubernetes in a lightweight manner. While the Kubernetes control plane still needs to run on at least one machine, all KubeEdge worker nodes do not require Kubernetes code and so work with much smaller devices. KubeEdge does not provide an API to users by itself but makes use of Kubernetes' API.

More information
* [KubeEdge - Documentation and setup](https://kubeedge.io/en/docs/)
* [KubeEdge - Source code](https://github.com/kubeedge/kubeedge)

### Terraform
Terraform is an infrastructure-as-a-service, enabling the deployment of hundreds of VMs, networks, and more by writing simple configuration files. It supports 1000+ providers, such as AWS, Google Cloud, OpenStack, Libvirt, and more. Depending on the benchmark version, either the Libvirt provider (for execution on local infrastructure) or the Google Cloud provider (for execution in Google Cloud) is used.

More information
* [Terraform - Get Started](https://www.terraform.io/)
* [Terraform Libvirt - Documentation](https://registry.terraform.io/providers/dmacvicar/libvirt/latest/docs)
* [Terraform Libvirt - Source code](https://github.com/dmacvicar/terraform-provider-libvirt)
* [Terraform Google Cloud - Get Started](https://learn.hashicorp.com/collections/terraform/gcp-get-started)
* [Terraform Google Cloud - Documentation](https://registry.terraform.io/providers/hashicorp/google/latest/docs)

### QEMU, KVM, Libvirt
For setting up the virtualized infrastructure, either Terraform or QEMU/KVM/Libvirt is used. Terraform with the Libvirt provider only supports execution on one local physical machine (due to network bridging problems). In contrast, QEMU/KVM/Libvirt supports execution up to many physical machines. When using cloud resources, please use Terraform with the Google Cloud provider.

QEMU, KVM, and Libvirt cooperate with each other. QEMU is a low-level emulator of virtual hardware. QEMU's emulation performance can be increased by using KVM, providing hardware acceleration of QEMU's emulation functions. Finally, Libvirt provides an abstraction layer on top of QEMU and KVM, improving the ease of use. As such, the benchmark only directly interacts with Libvirt while relying on QEMU and KVM for the actual emulation.

More information
* [QEMU - Installation](https://www.qemu.org/download/)
* [QEMU - Documentation](https://www.qemu.org/docs/master/)
* [KVM - Documentation](https://www.linux-kvm.org/page/Documents)
* [Libvirt - Documentation](https://libvirt.org/docs.html)
* [Libvirt - XML format](https://libvirt.org/formatdomain.html)

### Ansible
Ansible is a software provisioning, configuration management, and application-deployment tool. By writing playbooks, you can automate software installation and execution of software, filesystem operations, and much more on many machines, either physical or virtual, at the same time. It does this by executing Ansible Playbooks, high-level configuration files, but with the option to execute regular bash scripts if needed. By abstracting the exact command execution away from the user and by executing commands step-by-step, it provides a fail-safe execution environment,

More information
* [Ansible - How it works](https://www.ansible.com/overview/how-ansible-works)
* [Ansible - Installation](https://docs.ansible.com/ansible/latest/installation_guide/intro_installation.html)
* [Ansible - Intro to playbooks](https://docs.ansible.com/ansible/latest/user_guide/playbooks_intro.html)
