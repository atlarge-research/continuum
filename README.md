# Continuum
For information on how the Continuum framework works, please see the main branch of this repository.

---
# Demo
**This demo is for the MSc program Computer Science at the VU Amsterdam, specifically the distributed systems course in the academic year 2023-2024.**

**For other users, please use the main branch of this project instead**

This demo consists of three parts:
1. Access the servers
2. Deploy Kubernetes with Continuum
3. Inspect Kubernetes by hand
4. Observe Kubernetes with Grafana

### Part 1: Access the servers
For this demo, you will get access to servers at the VU (not the DAS). \
We currently only support this demo on these servers.

1. Send a public SSH key to the email address mentioned in the presentation of this demo. If you don't yet have a key, generating a new one can be as simple as executing `ssh-keygen`. Otherwise, search online on how to generate a new SSH key for your operating system or ask another student in the demo session. On Debian/Ubuntu-based systems, ssh keys are stored in `~/.ssh`. The default key is named `id_rsa.pub`, you can display the key with `cat id_rsa.pub`.
2. You will receive a username `ds-nX-Y` with X and Y as numbers, and an IP address in the form of `192.168.ZZZ.2`. Remember these.
3. Access the cluster as follows:
    ```
    ssh -i /path/to/your/ssh/key/key.pub ds-nX-Y@al01.anac.cs.vu.nl
    # Example: ssh -i ~/.ssh/id_rsa.pub ds-n6-2@al01.anac.cs.vu.nl

    # Now you are on the head node of the cluster, which should not be used for the demo.
    # From here, you need to jump to the server you will use for the demo
    ssh nodeX
    ```
    Fill in the missing parts of the commands (e.g., X, Y, the path to your key). \
    You may need to pass your key with or without the .pub extension, this is operating systems-specific.
4. Now you are in your home directory on the node. The Continuum repository should already be cloned for you, you can check this with `ls`. Move into the repository with `cd continuum` and continue with part 2 of the demo.

### Part 2: Deploy Kubernetes with Continuum
In this part, you will use the Continuum framework to deploy Kubernetes in the Compute Continuum.
You should already have received an explanation about this during the presentation.

1. Deploy the prepared configuration: `python3 continuum.py configuration/tutorial-ds.cfg`. It will take ~10 minutes to finish, so don't worry if it seems like the program is hanging. Contact the teaching staff if an error appears.
2. Open an SSH connection in a new terminal to nodeX and inspect the configuration (`cat configuration/tutorial-ds.cfg`). This configuration tells Continuum to create 2 VMs of type cloud, with 4 CPU cores and 16 GB memory each, and one VM of type endpoint with much fewer resources. On these VMs, Continuum will deploy a Kubernetes cluster of 1 control node and 1 worker node. The control node controls the cluster, and only the worker node can execute applications. Finally, Continuum runs a benchmark with an image-classification application. With this, you emulate a camera device (endpoint) that generates 5 images per second for 1 minute, and each image will be analyzed using machine learning on the cloud machine. You will test how well the application can be offloaded to the cloud.
3. After the framework run has been completed, you will get output similar to this:
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
    For this example, 1 endpoint offloads its data to 1 cloud worker for 1 minute. The endpoint generates 5 images per second, preprocesses each image for 1.3 ms on average (e.g., compressing data before sending), and sends the data of 68 kb per image on average to the cloud, which takes 123 ms on average to arrive in the cloud. Then, the cloud processes the image for 125 ms and sends the result back to the endpoint, for a total end-to-end latency of 296 ms. The end-to-end latency is the time between (i) an endpoint generating an image and (ii) the endpoint receiving the processed output for that image. Depending on your application, you can now decide if 296 ms is a good enough latency or not.

### Part 3: Inspect Kubernetes by hand
In this part, you will inspect the Kubernetes cluster running on the provisioned VMs to see what the cluster does under the hood. 

1. SSH into the cloud_controller VM, which hosts Kubernetes' control plane. Use the SSH command related to the cloud_controller VM that should be printed at the bottom of Continuum's output. For the provided example above, this is `ssh cloud_controller_matthijs@192.168.100.2 -i /home/matthijs/.ssh/id_rsa_continuum`. If you can't find the output of your Continuum run anymore, it is also saved in `continuum/logs/`.
2. The main tool for users to inspect the current state of Kubernetes is called `kubectl`, which is installed in the cloud_controller VM. You can find a cheat sheet for kubectl here: https://kubernetes.io/docs/reference/kubectl/cheatsheet/#viewing-and-finding-resources. Try to answer the following questions using kubectl (hint: You need to use `kubectl get ...` or `kubectl describe ...` for all questions):
    1. How many nodes are in the Kubernetes cluster? And what is their name?
    2. How many applications are registered in the cluster?
    3. What is the current state of the application(s)? Are they still running or already finished?
    4. What is the output of these application(s)?
    5. How many resources did these applications use in terms of CPU and memory?
    6. Are there any other applications running on the worker node in the cluster?
    7. What control plane applications has Kubernetes running on the cloud_controller? Hint: these applications are deployed in the `kube-system` namespace.

### Part 4: Observe Kubernetes with Grafana
Continuum has installed Prometheus (https://prometheus.io/) and Grafana (https://grafana.com/) in the VM where Kubernetes' control plane runs. The former captures logs from Kubernetes, the latter visualizes these logs. In this step, you will inspect the current state of Kubernetes using Grafana Dashboards, with graphs and tables showing live Kubernetes metrics. You will open these dashboards on your own computer as the cluster does not have a screen to look at.

Grafana is running on the cloud_controller VM, so we have to forward the data it is generating to your own computer using SSH port-forwarding.
1. In a new terminal, SSH to your assigned node using these commands:
    ```
    # From your local computer to the head node of the VU cluster:
    ssh -L 3000:192.168.ZZZ.2:3000 -i /path/to/your/ssh/key/key.pub ds-nX-Y@al01.anac.cs.vu.nl

    # Then, to the node where you run Continuum:
    ssh -L 3000:192.168.ZZZ.2:3000 nodeX

    # Then, from the node where Continuum runs to the cloud controller VM
    ssh -L 3000:192.168.ZZZ.2:3000 cloud_controller_ds-nX-Y@192.168.ZZZ.2 -i ~/.ssh/id_rsa_continuum
    ```
    The first two SSH commands are similar to those you use to access the cluster, as described in section 1.3. The last command is printed at the end of the Continuum run, see `continuum/logs/`. NOTE: The IP in the -L argument should end with .2, not .3 as printed by Continuum, this is a bug. For more information on the variables X, Y, and Z, see section 1.2.
3. Now, you can interact with Grafana on your own computer. Go to `http://localhost:3000` in a browser. This will open the Grafana dashboard that visualizes the state of your cluster and the applications running in your cluster. Log in with username and password `admin`, and skip creating a new password.
4. Go to 'dashboard' (the icon with the 4 boxes in the left navigation bar) -> manage -> default to open the available Granafa dashboards (different graphs and overviews).
5. You can open any dashboard, such as:
    1. Kubernetes/Compute Resources/Cluster: See the resource usage of all pods in the cluster. Pods are grouped here in namespaces -> default contains the user's applications (the one you just deployed), kube-system contains Kubernetes' control plane components, monitoring contains Prometheus' and Grafana's applications used to get the data used in these dashboards, etc. 
    2. Kubernetes/Compute Resources/Node (Pods): See the resource usage per node. If you select node -> cloud0<username> in the top left corner, you will see the resource usage of the worker node where you deployed your applications. If you select node -> cloudcontroller<username>, you will see the resource usage of the control plane components of Kubernetes. Alternatively, use Default/Node Exporter/Nodes for a different overview.
    3. Kubernetes/Compute Resources/Pod: See the resource usage of individual pods. You can select what pod you want to analyze in the top left corner.
    4. Kubernetes/Networking/Cluster: See the network traffic within the cluster and to sources outside of the cluster.
6. Important: You can select in the top right corner of each dashboard the time range you want to see data in. You may want to see all data produced in the last hour, or maybe only from the last 5 minutes.
7. Keep the Grafana dashboard open for the remainder of the tutorial.

### Part 5: Deploy a new application
Finally, you will deploy a new application on the Kubernetes cluster. We will not use the endpoint virtual machine anymore. The application still uses image classification but generates and processes data all by itself. This approach is similar to big data processing in the cloud, where the cloud already has data that needs to be processed and there is no need for endpoint devices to send live data to the cloud.

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
2. Inspect the file: You will deploy 2 (`parallelism: 2`) applications, specifically the `image_classification_combined` container image. Each application will have 2 GB of memory (`memory: "2000Mi"`) and 1 CPU core (`cpu: 1.0`). The application will process 5 images per second (`FREQUENCY value: "5"`) for 60 seconds (`DURATION value: "60"`).
3. Deploy the application: `kubectl apply -f new_job.yml`
4. Check that the new applications (2 pods) are running using the correct kubectl commands.
5. Check the application's output using the correct kubectl command.
6. See in Grafana if you can monitor the live resource usage from the 2 applications. Is there a difference in resource usage between the applications?
