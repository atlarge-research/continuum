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

## Citation
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
    doi       = {},
    url       = {https://atlarge-research.com/pdfs/2023-fastcontinuum-continuum.pdf},
}
```

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
    doi       = {},
    url       = {https://atlarge-research.com/pdfs/2023-ccgrid-refarch.pdf},
}
```

### Acknowledgment
This work is funded by NWO TOP OffSense (OCENW.KLEIN.209).

## Observability
Continuum has integrated support for Prometheus and Grafana on top of Kubernetes and OpenFaas.
Continuum will automatically install these software packages and configure them when using `observability = True` in the configuration file, see `configuration/template.cfg`. 
After Continuum has finished, you can use your browser to open the Grafana dashboard using `localhost:3000` and Prometheus using `localhost:9090`. 
The Grafana dashboard requires a username and password, both are `admin` by default.
In case you run Continuum on a machine without a graphical user interface, connect to the machine from a device with one, and port-forward the 3000 and 9090 ports. 
For example, to port-forward the 3000 port, use `ssh -L 3000:XXX.XXX.XXX.XXX:3000 username@address -i /path/to/ssh_key`, with XXX.XXX.XXX.XXX the IP of the cloud controller VM that is printed after Continuum has finished (typically 192.168.100.2), username@address the IP address of the server you can Continuum on and the username of your account on the server, and the corresponding SSH key.

---
# Demo
**This demo is for the BSc Computer Science at the VU Amsterdam, specifically the networks course in the academic year 2022/2023.**

**For other users, please use the main branch of the project instead**

This demo consists of three parts:
1. Access the servers
2. Deploy Continuum with Kubernetes and KubeEdge
3. Deploy Continuum with OpenFaaS

### Part 1: Access the servers
For this demo, you will get access to VU compute servers.
We currently only support this demo on these servers.

1. Send a public SSH key to the provided email address. You will receive a username `cn-nX-Y` with X and Y as numbers, and an IP address in the form of `192.168.ZZZ.2`.
2. Add the following to your ssh config, typically in `~/.ssh/config`. Fill in X, Y, and Z.
```
Host al01
	HostName al01.anac.cs.vu.nl
	User cn-nX-Y <-- Fill in X and Y
	IdentityFile /path/to/your/ssh/key (example: ~/.ssh/id_rsa. May need .pub if not working)

Host nodeX <-- Fill in X
	HostName nodeX <-- Fill in X
	User cn-nX-Y <-- Fill in X and Y
	ProxyJump al01
	IdentityFile /path/to/your/ssh/key (example: ~/.ssh/id_rsa. May need .pub if not working)
```
3. Access the node where you will work on: `ssh nodeX`
4. Now you are in your home directory on the node. The Continuum repository should already be cloned for you, you can check this with `ls`. Move into the repository with `cd continuum` and continue with part 2 of the demo.


### Part 2: See below
Run continuum with kube to get the cluster with 1 example running

### Part 3: Observe Kubernetes
Connect grafana and inspect what is happening

### Part 4: Modify Kubernetes
Now modify the deployment file, like 20 apps in parallel with 0.05 cpu and 0.5 mem




### Part 2: Deploy Continuum with Kubernetes
In this part, you will use the Continuum framework to deploy Kubernetes in the Compute Continuum.
You should already have received an explanation on this during the presentation.

1. Deploy the prepared configuration: `python3 continuum.py configuration/tutorial-cn.cfg`. It will take ~10 minutes to finish, so don't worry if it seems like the program is hanging. Contact the teaching staff if an error appeared.
2. Open the configuration (`cat configuration/tutorial-cn.cfg`) and inspect it. This configuration tells Continuum to create 2 VMs of type cloud, with 4 CPU cores and 16 GB memory each, and one VM of type endpoint with much less resources. On these VMs, the framework will deploy a Kubernetes cluster

1. Use Continuum to create 1 endpoint VM, which is used to run a machine learning application, namely image recognition. With this, you emulate a (security) camera device that generates 5 images per second for 5 minutes (300 seconds), and each image will be analyized using machine learning. You will test how well the application can be run on an endpoint without offloading to cloud or edge. While in the Continuum repository, do `python3 main.py configuration/endpoint.cfg`. This will start the Continuum framework, and may take serveral minutes to complete.
2. After the framework has completed, you will get output similar to this:
    ```
    ------------------------------------
    ENDPOINT OUTPUT
    ------------------------------------
    endpoint_id  total_time (s)  proc_time/data (ms)  latency_avg (ms)  latency_stdev (ms)
            0          472.41               263.21          62203.04            26674.06

    ```
    For this particular example, one endpoint was deployed (with ID 0), and it took 472 seconds to finish the ML application. The application is set to only run for 300 seconds, so an execution time of 472 seconds shows that real-time processing is not possible. This is confirmed by looking at the time it took to process a single image, 263.21 ms. With 5 images per second being generated, the endpoint should process each image in 200 ms to achieve real-time processing, which was not possible. This has caused the average end-to-end latency (the time it takes from generating and image to it being processed by a machine learning algorithm) to be 62 seconds, as a queue of workload starts forming.
3. Repeat step 1 and 2 for deployments where this application is offloaded to cloud and edge resources. By offloading the ML tasks to sites with more processing power, the deployment may achieve real-time processing. However, by offloading computation to a far-away location, end-to-end latency may increase. This is undesired for applications that require low end-to-end latency such as VR or cognitive assistance. Do `python3 main.py configuration/kubernetes-cloud.cfg` and `python3 main.py configuration/kubeedge-edge.cfg`
4. An example output of offloading to cloud follows below:
    ```
    ------------------------------------
    CLOUD OUTPUT
    ------------------------------------
    worker_id  total_time (s)  delay_avg (ms)  delay_stdev (ms)  proc_time/data (ms)
        0          306.72          127.76             32.77               149.53
    ------------------------------------
    ENDPOINT OUTPUT
    ------------------------------------
    connected_to  total_time (s)  preproc_time/data (ms)  data_size_avg (kb)  latency_avg (ms)  latency_stdev (ms)
        0           307.1                    1.29               68.01            317.91               37.55

    ```
    In this case, 1 cloud worker processes each image in 127 ms, which is well below the deadline of 200 ms. This is possible because of the high compute power in clouds. The end-to-end latency is 317 ms on average, so 0.3 seconds. Depending on the application, this may be or not be sufficient.
5. After you have finished running your final deployment, and there is still time until the next tutorial, you can further inspect Kubernetes and the application. You can SSH to the `cloud_controller` machine using the SSH command printed at the end of Continuum's output. You are now in the head node of the Kubernetes cluster.

    1. How does your cluster look like? `kubectl get nodes`. There is one cloud controller, and one worker machine. You can inspect the status of each machine by doing `kubectl describe node <name>`, using the names from the first command. This shows the current status of the nodes, their resources, recent events, etc.
    2. Now we can inspect the applications (called pods) that ran on the cluster. Do `kubectl get pods` to list all applications. You can also get more info on these by doing `kubectl describe pod <podname>`.

## Part 3: Deploy Continuum with OpenFaaS
1. Start Continuum with Kubernetes and OpenFaaS, while inside the Continuum repository: `python3 main.py configuration/openfaas-cloud.cfg`. Wait for this to complete.
2. Open an SSH tunnel in a new terminal:
    1. To the headnode of the cluster, from your local computer: `ssh -L 3000:192.168.ZZZ.2:3000 asci-nX-Y@al01.anac.cs.vu.nl -i <path to your public key>`, using the X and ZZZ from step 1.
    3. From the headnode to the specific machine: `ssh -L 3000:192.168.ZZZ.2:3000 nodeX`, using the X and ZZZ from step 1.
2. No application has started yet in step 1. We will do that now. Go to `cd DS-serverless/deployment`. Here we will start the serverless functions inside our Kubernetes / OpenFaaS cluster, and monitor the state of the applications. Do `pyinfra inventory.py deploy.py`. If it crashes during execution, execute this command again (this may sometimes happen). If it still doesn't work after several retries, please contact the teaching staff. 
3. If you used the correct SSH commands noted at the start of this demo, you should open the following URL in your browser on your local computer: `http://localhost:3000`. This will open the Grafana dashboard that visualizes the state of your cluster and the applications running in your cluster. Log in with username and password `admin`, skip creating a new password, go to the dashboard (the icon with the 4 boxes in the left navigation bar), and under Default open Function Dashboard DS2022. This will show you a live view of the resource usage of each application. Each application has a different resource usage, and you can inspect how these applications affect each other. 
4. You can also go to "Logs Fibonacchi" under Dashboard, which shows the average execution time per serverless function, split up per application. Can you see the variation in execution time? Why would this happen?
5. Go back to the Continuum repository, and run OpenFaas at the edge: `python3 main.py configuration/openfaas-edge.cfg`. Now repeat steps 2-4. Can you see any differences?





# TO PROCESS
```
------------------------------------
CLOUD OUTPUT
------------------------------------
 worker_id  total_time (s)  delay_avg (ms)  delay_stdev (ms)  proc_time/data (ms)
         0            61.4          123.85             34.06                125.1
------------------------------------
ENDPOINT OUTPUT
------------------------------------
 connected_to  total_time (s)  preproc_time/data (ms)  data_size_avg (kb)  latency_avg (ms)  latency_stdev (ms)
            0           61.73                    1.31               68.01            296.55                38.9

To access the VMs:
	ssh cloud_controller_matthijs@192.168.100.2 -i /home/matthijs/.ssh/id_rsa_continuum
	ssh cloud0_matthijs@192.168.100.3 -i /home/matthijs/.ssh/id_rsa_continuum
	ssh endpoint0_matthijs@192.168.100.4 -i /home/matthijs/.ssh/id_rsa_continuum

To access Grafana: ssh -L 3000:192.168.100.3:3000 cloud_controller_matthijs@192.168.100.2 -i /home/matthijs/.ssh/id_rsa_continuum
To access Prometheus: ssh -L 9090:192.168.100.3:9090 cloud_controller_matthijs@192.168.100.2 -i /home/matthijs/.ssh/id_rsa_continuum
```