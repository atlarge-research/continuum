# Experiments on Kubernetes Control Plane
This directory contains experiments to benchmark the Kubernetes control plane.
More specifically, we measure how long it takes to deploy X pods in parallel, with X being >= 1.
We use the following three experiments:

1. Constant_total_pods: Test strong scalability. We deploy 100 pods, with 1 container each, over an increasing number of Kubernetes workers.
2. Nodes: Test weak scalability. We deploy 100 pods, with 1 container each, per node, with an increasing number of Kubernetes workers.
3. Pods_per_node: Test workload in a single machine. We deploy an increasing number of pods, with 1 container each, on a single machine.
4. Versions: Test differences between Kubernetes versions. We deploy 100 pods, with 1 container each, on a single machine, and for Kubernetes 1.23 - 1.27.
5. pod_1_container_100.cfg: Test multiple containers per pod. Deploy 1 pod on a single node, with 1 to 100 containers inside that single pod.