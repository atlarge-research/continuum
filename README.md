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
**This demo is for the Distributed Systems course at the Vrije Universiteit Amsterdam, part of the 2022 - 2023 curriculum of the Computer Science Master.**

**For other users, please use the main branch of the project instead**

This demo consists of two parts:
1. Access the servers
2. Use OpenFaaS

### Part 1: Access the servers
For this demo, you will get access to VU compute servers. If you don't have access yet, please read and reply to the announcement that was sent to you before the start of this tutorial. For this tutorial, we assume you have access to the compute cluster already.

1. Reply to the announcement that was sent to all students of the Distributed Systems course, and send us a public SSH key. Save the public and private key locally, you will need it later. You will send you back your username on our cluster, as well as the specific machine you will use in our cluster.
2. Access the headnode of the cluster over SSH: `ssh <username>@al01.anac.cs.vu.nl -i <path to your public key>`
3. Access the specific server: `ssh nodeX`, with X being the specific machine ID we sent you via email together with your username.
4. Now you are in your home directory on one of the servers. Most likely, the continuum repository is already cloned for you, you can check this with `ls`. Move into the repository with `cd continuum` and continue with part 2 of the demo.

### Part 2: Use OpenFaaS
In this part, you will use the Continuum framework to create multiple virtual machines (VMs), that together form a Kubernetes cluster. On top of this Kubernetes cluster you will install and use [OpenFaaS](https://docs.openfaas.com/).

1. Run Continuum with a configuration for OpenFaas. These configurations are stored in the `/configuration` folder. Specifically, we will use the `configuration/tutorial_openfaas.cfg` configuration. The `resource_manager_only = true` flag and `model = openFaas` in section `execution_model` are critical here. **NOTE**: Do not change the following parameters in the configuration file under any circumstances, this will stop Continuum from working for you and possibly other students: `base_path, prefixIP, middleIP, middleIP_base`.
    ```bash
    python3 main.py configuration/tutorial_openfaas.cfg
    ```

2. From your host system, SSH onto the `cloud_controller` node. This is the headnode of your just-created Kubernetes cluster. The following command is an example, the actual command is printed at the end of the Continuum framework as output:
   ```bash
   ssh cloud_controller@192.168.100.2 -i ~/.ssh/id_rsa_benchmark
   ```

3. On the `cloud_controller` make port 8080 from the Kubernetes cluster available on the node:
   ```bash
   nohup kubectl port-forward -n openfaas svc/gateway 8080:8080 &
   ```
   After execution, hit either `enter` or `Strg+C` to exit the dialog.

4. Give the `faas-cli` access to the OpenFaas deployment:
   ```bash
   PASSWORD=$(kubectl get secret -n openfaas basic-auth -o jsonpath="{.data.basic-auth-password}" | base64 --decode; echo)
   echo -n $PASSWORD | faas-cli login --username admin --password-stdin
   ```

Congratulations! As long as you don't reset the cluster, you can now access the OpenFaas deployment through the `cloud_controller` node and `faas-cli`.  

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
