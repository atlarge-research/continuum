# Experiments on Kubernetes Control Plane
This directory contains experiments to benchmark the Kubernetes control plane.
More specifically, we measure how long it takes to deploy X pods in parallel, with X being >= 1.
We use the following three experiments:

1. Containers_per_node: We deploy from 1 pod to 50 pods in parallel on a single Kubernetes worker.
    * Containers = 1, 10, 20, 30, 40, 50
    * Question: How does pod startup time scale on a single worker?
        * Subquestion: How does the central control plane scale?
        * Subquestion: How does the kubelet / container runtime scale on the worker?
2. Nodes: We deploy 50 pods per worker, and increase the number of Kubernetes workers to >= 1.
    * Nodes = 1, 2, 4, 8, 16
    * Question: How does pod startup time scale with multiple nodes and constant containers/node?
        * Similar subquestions as before, but with more stress on the control plane
3. Total_containers: We deploy 50 containers in total, divided over >= 1 nodes.
    * Total containers = 16
    * Nodes = 1, 2, 4, 8, 16
    * Pods/node = 16, 8, 4, 2, 1