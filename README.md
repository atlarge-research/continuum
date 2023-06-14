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

---
# Demo
**This demo is for the BSc Computer Science at the VU Amsterdam, specifically the computer networks course in the academic year 2022-2023.**

**For other users, please use the main branch of the project instead**

This demo consists of three parts:
1. Access the servers
2. Deploy Kubernetes with Continuum
3. Inspect Kubernetes by hand
4. Observe Kubernetes with Grafana

### Part 1: Access the servers
For this demo, you will get access to VU compute servers.
We currently only support this demo on these servers.

1. Send a public SSH key to the provided email address. If you don't yet have a key, genertaing a new one can be as simple as executing `ssh-keygen`. Otherwise, search online on how to generate a new SSH key for you operating system. On Debian/Ubuntu-based systems, ssh keys are stored in `~/.ssh`. The default key is named `id_rsa.pub`, you can dispaly this one using `cat id_rsa.pub`.
2. You will receive a username `cn-nX-Y` with X and Y as numbers, and an IP address in the form of `192.168.ZZZ.2`. Remember these.
3. Add the following to your ssh config, typically in `~/.ssh/config`. Fill in the missing parts.
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

### Part 2: Deploy Kubernetes with Continuum
In this part, you will use the Continuum framework to deploy Kubernetes in the Compute Continuum.
You should already have received an explanation on this during the presentation.

1. Deploy the prepared configuration: `python3 continuum.py configuration/tutorial-cn.cfg`. It will take ~10 minutes to finish, so don't worry if it seems like the program is hanging. Contact the teaching staff if an error appeared.
2. Open a new SSH connection to nodeX and inspect the configuration (`cat configuration/tutorial-cn.cfg`). This configuration tells Continuum to create 2 VMs of type cloud, with 4 CPU cores and 16 GB memory each, and one VM of type endpoint with much less resources. On these VMs, the framework will deploy a Kubernetes cluster of 1 control node and 1 worker node. The control node controls the cluster, and only the worker node can execute applications. Finally, Continuum runs a benchmark with an image-classification application. With this, you emulate a camera device (endpoint) that generates 5 images per second for 1 minute, and each image will be analyized using machine learning on the cloud machine. You will test how well the application can be offloaded to cloud.
3. After the framework has completed, you will get output similar to this:
    ```
    ------------------------------------
    CLOUD OUTPUT
    ------------------------------------
    worker_id  total_time (s)  delay_avg (ms)  delay_stdev (ms)  proc_time/data (ms)
            0            61.4          123.85             34.06                125.1
    ------------------------------------
    ENDPOINT OUTPUT
    ------------------------------------
    connected_to  total_time (s)  preproc_time/data (ms)  data_size_avg (kb)  latency_avg (ms)
                0           61.73                    1.31               68.01            296.55

    To access the VMs:
        ssh cloud_controller_matthijs@192.168.100.2 -i /home/matthijs/.ssh/id_rsa_continuum
        ssh cloud0_matthijs@192.168.100.3 -i /home/matthijs/.ssh/id_rsa_continuum
        ssh endpoint0_matthijs@192.168.100.4 -i /home/matthijs/.ssh/id_rsa_continuum

    To access Grafana: ssh -L 3000:192.168.100.3:3000 cloud_controller_matthijs@192.168.100.2 -i /home/matthijs/.ssh/id_rsa_continuum
    To access Prometheus: ssh -L 9090:192.168.100.3:9090 cloud_controller_matthijs@192.168.100.2 -i /home/matthijs/.ssh/id_rsa_continuum
    ```
    For this example, 1 endpoint offloads its data to 1 cloud worker for about 1 minute. The endpoint geenrates 5 images per second, preprocesses each image for 1.3 ms on average (think compressing data before sending), sends the data of 68 kb per image to the cloud, which takes 123 ms on average to arrive in the cloud, then the cloud process the image for 125 ms and sends the result back to the endpoint, for a total end-to-end latency of 296 ms. The end-to-end latency is the time between (i) an endpoint generating an image and (ii) the endpoint receiving the processed output for that image. Depending on your application, you can now decide if 296 ms is a good enough latency or not.

### Part 3: Inspect Kubernetes by hand
In this part, you will inspect the Kubernetes cluster running on the provisioned VMs to see what the cluster actually does. 

1. SSH into the cloud_controller VM, which hosts Kubernetes' control plane. Use the SSH command related to the cloud_controller VM that should be printed at the bottom of Continuum's output. For the provided example above, this is `ssh cloud_controller_matthijs@192.168.100.2 -i /home/matthijs/.ssh/id_rsa_continuum`.
2. The main tool for users to inspect the current state of Kubernetes is called `kubectl`, which is installed in the cloud_controller VM. You can find a cheat sheet for kubectl here: https://kubernetes.io/docs/reference/kubectl/cheatsheet/#viewing-and-finding-resources. Try to answer the following questions using kubectl (hint: You need to use `kubectl get ...` or `kubectl describe ...` for all questions):
    1. How many nodes are in the Kubernetes cluster? And what is their name?
    2. How many applications are registered in the cluster?
    3. What is the current state of the application(s)? Are they still running or already finished?
    4. What is the output of these application(s)?
    5. How many resources did these applications use in terms of CPU and memory?
    6. Are there any other applications running on the worker node in the cluster?
    7. What control plane applications has Kubernetes running on the cloud_controller? Hint: these applications are deployed in the `kube-system` namespace.

### Part 4: Observe Kubernetes with Grafana
Continuum has installed Prometheus (https://prometheus.io/) and Grafana (https://grafana.com/). The former captures logs from Kubernetes, the latter visualizes these logs. In this step, you will inspect the current state of Kubernetes using Grafana Dashboards, with graphs and tables showing live Kubernetes metrics. You will open these dashboards on your own computer as the cluster obviously does not have a screen to look at.

Grafana is running on the cloud_controller VM, so we have to forward the data it is generating to our own computer using SSH port-forwarding.
1. In a new terminal, SSH to your assigned node using the command `ssh -L 3000:192.168.ZZZ.2:3000 nodeX`.
2. Next, SSH from nodeX to the cloud_controller using the Grafana command printed at the bottom of Continuum's output. For the example given in step 2, this is `ssh -L 3000:192.168.100.3:3000 cloud_controller_matthijs@192.168.100.2 -i /home/matthijs/.ssh/id_rsa_continuum`

Now we can interact with Grafana on our own computer
3. Go to `http://localhost:3000` in a browser. This will open the Grafana dashboard that visualizes the state of your cluster and the applications running in your cluster. Log in with username and password `admin`, and skip creating a new password.
4. Go to dashboard (the icon with the 4 boxes in the left navigation bar) -> manage -> default to open the available Granafa dashboards (different graphs and overviews).
5. You can open any dashboard, such as:

    1. Kubernetes/Compute Resources/Cluster: See the resource usage of all pods in the cluster. Pods are grouped here in namespaces -> default contains the user's applications (the one you just deployed), kube-system contains Kubernetes' control plane components, monitoring contains Prometheus' and Grafana's applications used to get the data used in these dashboards, etc. 
    2. Kubernetes/Compute Resources/Node (Pods): See the resource usage per node. If you select node -> cloud0<username> in the top left corner, you will see the resource usage of the worker node where you deployed your applications. If you select node -> cloudcontroller<username>, you will see the resource usage of the control plane components of Kubernetes. Alternatively, use Default/Node Exporter/Nodes for a different overview.
    3. Kubernetes/Compute Resources/Pod: See the resource usage of individual pods. You can select what pod you want to analyze in the top left corner.
    4. Kubernetes/Networking/Cluster: See the network traffic within the cluster and to sources outside of the cluster.
6. Important: You can select the in the top right corner of each dashboard the time range you want to see data of. You may want to see all data produced in the last hour, or maybe only from the last 5 minutes.
7. Keep the Grafana dashboard open for the remainder of the tutorial.

### Part 5: Deploy a new application
Finally, you will deploy 2 new applications on the Kubernetes cluster. The application you will use still uses image classification, but now processes its own images, so there is no endpoint sending images to the cloud. This approach is similar to big data processing in the cloud, where the cloud already has its own data that needs to be processed, and there is no need for endpoint devices to send live data to the cloud.

1. Create a new Kubernetes deployment file while in the cloud_controller VM:
```
cat > ~/new_job.yaml <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: image-classification-2
spec:
  parallelism: 2
  template:
    metadata:
      name: image-classification
    spec:
      containers:
      - name: image-classification
        image: 192.168.1.103:5000/image_classification_combined
        ports:
        - containerPort: 1883
        imagePullPolicy: Always
        resources:
          requests:
            memory: "2000Mi"
            cpu: 1.0
        env:
        - name: CPU_THREADS
          value: "1"
        - name: DURATION
          value: "60"
        - name: FREQUENCY
          value: "5"
      restartPolicy: Never
EOF
```
2. Inspect what the file: You will deploy 2 (`parallelism: 2`) applications, specifically the `image_classification_combined` container image. Each application will have 2 GB of memory (`memory: "2000Mi"`) and 1 CPU core (`cpu: 1.0`). The application will process 5 images per second (`FREQUENCY value: "5"`) for 60 seconds (`DURATION value: "60"`).
3. Deploy the application: `kubectl apply -f new_job.yml`
4. Check that the new applications (2 pods) are running using the correct kubectl commands.
5. Check the application's output using the correct kubectl command.
6. See in Grafana if you can monitor the live resource usage from the 2 applications. Is there a difference in resource usage between the applications?
