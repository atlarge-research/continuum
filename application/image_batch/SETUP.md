# Setup: from host accounts to a running service

Follow this once before the [live walkthrough](README.md). You have course accounts on two prepared Linux nodes with about 20 CPU cores each. Account permissions, group membership, SSH access, host tools and networking are already set up. Run commands in Bash on the **first physical node**, unless stated otherwise. Continuum creates the VMs and Kubernetes; you then install the reference application.

## Get Continuum and create the configuration

Clone the reference branch on the first host:

~~~bash
git clone --branch codex/fns-2026-10-08 --single-branch \
  https://github.com/atlarge-research/continuum.git
cd continuum
mkdir -p logs/student-demo "$HOME/.ssh"
touch "$HOME/.ssh/known_hosts"

python3.10 -m venv logs/student-demo/provision
logs/student-demo/provision/bin/pip install -r requirements.txt
~~~

Keep provisioning dependencies separate from the forecasting/reporting environment created below: their NumPy and Matplotlib versions differ.

Create `logs/student-demo/cluster.cfg` from the template below, replacing the host, storage path and address fields with your course-assigned values. Use literal values: the configuration file does not expand shell variables.

~~~ini
[infrastructure]
provider = qemu
external_physical_machines = SAME_USERNAME@SECOND_NODE
base_path = /ABSOLUTE/NODE_LOCAL/TEAM_PATH

cloud_nodes = 7
cloud_cores = 5
cloud_memory = 8
cloud_quota = 1.0

endpoint_nodes = 1
endpoint_cores = 2
endpoint_memory = 4
endpoint_quota = 1.0

cpu_pin = True
network_emulation = False

prefixIP = 192.168
middleIP = 210
middleIP_base = 211
delete = False

[benchmark]
resource_manager = kubernetes
resource_manager_only = True
observability = True
~~~

Set these fields for your team:

| Field | Value to use |
| --- | --- |
| `external_physical_machines` | Your account and the second node's address, using the same username as on the first node. List only the second node; Continuum includes the first automatically. |
| `base_path` | Your assigned absolute node-local storage path, such as `/mnt/sdc/ACCOUNT` or `/home/ACCOUNT` if the home directory is local. Use the same path on both nodes, with each node keeping its own VM files. |
| `prefixIP` | The first two parts of the assigned guest IP range. Replace `192.168` if your course uses another prefix. |
| `middleIP` and `middleIP_base` | The distinct values assigned to your team for guest VMs and temporary base images. Replace the example `210` and `211` with those values. |

This creates **one control plane, six workers and one endpoint**. Each cloud VM has five vCPUs and 8 GiB RAM; the endpoint has two vCPUs and 4 GiB RAM. On two otherwise suitable 20-core hosts, expected placement is control plane plus three workers on the first host, and three workers plus endpoint on the second. The endpoint is outside Kubernetes. The worker model reserves one core per worker, leaving four application slots.

The first run downloads and builds images. Network shaping is disabled so you can study compute-side control independently; [network emulation](../../docs/NETWORK.md) is an optional later experiment.

## Provision VMs and Kubernetes

From the first physical node, verify the second node's SSH host-key fingerprint against a trusted source, such as the course operator or the worker's console. Add the verified key to `~/.ssh/known_hosts` under the exact hostname or IP address used in `external_physical_machines`. Physical-worker provisioning rejects missing or changed keys. If a worker is rebuilt or its key rotates, verify the replacement fingerprint before updating the entry.

~~~bash
source logs/student-demo/provision/bin/activate
python continuum.py logs/student-demo/cluster.cfg
deactivate
~~~

Expect eight final VMs, a seven-node Kubernetes cluster, and Prometheus/Grafana in namespace `monitoring`. Continuum prints guest SSH commands and writes its generated inventory beneath `base_path/.continuum/inventory_vms`.

Provisioning is a rebuild operation: another Continuum run can replace guests associated with your account. Collect experiment evidence first, and keep each team's provisioning separate. A guest reboot/rebuild also changes assumptions about images, clocks and application readiness, so repeat the checks below afterward.

## Prepare the demo application

Remain at the repository root on the first host:

~~~bash
bash application/image_batch/scripts/student_demo.sh prepare
~~~

The [demo helper](scripts/student_demo.sh) reads `logs/student-demo/cluster.cfg` and Continuum's generated Ansible inventory. It creates a separate Python environment for forecasting and reporting, builds the application and pinned OpenDC images, distributes them to the guests, enables metrics and worker packing, and starts the service. Use `--help` to see the commands and the optional configuration-file override.

The first preparation can take time, especially compiling OpenDC. Docker reuses cached build layers on later runs. The helper keeps image archives and scheduler backups in `logs/student-demo/setup`; the original scheduler backup is also preserved at `/etc/kubernetes/kube-scheduler.before-student.yaml` on the controller, outside the static-Pod manifest directory.

Continuum installs Prometheus. The helper additionally installs [metrics-server v0.7.2](https://github.com/kubernetes-sigs/metrics-server/tree/v0.7.2) and enables `--kubelet-insecure-tls` for the isolated laboratory cluster, whose kubelet serving certificates are not signed by a trusted CA. See the [metrics-server requirements](https://github.com/kubernetes-sigs/metrics-server/blob/v0.7.2/README.md#requirements). The [packing profile](manifests/scheduler-packing.yaml) is mounted into the existing scheduler so Jobs fill workers before spreading to additional ones.

Preparation prints guest time-synchronization status and checks node readiness. Captures also require a conservative host/guest clock-offset bound of one second, including SSH delay. Let time synchronization settle before timed workloads; do not change clocks during an experiment.

Run preparation after provisioning or rebuilding guests, and before experiments. It changes cluster configuration, rebuilds images and replaces the template service Pod, discarding its manual requests and observer data. Finish collecting any current experiment first, and keep image identities unchanged during a matched trio experiment of forecast digital twin, reactive, and baseline actuation.

## Inspect the running service

Use the helper to run kubectl on the control plane:

~~~bash
bash application/image_batch/scripts/student_demo.sh kubectl get nodes -o wide
bash application/image_batch/scripts/student_demo.sh kubectl get pods,services -n fns-demo
bash application/image_batch/scripts/student_demo.sh url
~~~

Expect seven Ready Kubernetes nodes, one adapter Pod with adapter and observer containers, and a service URL ending in `:30080`. The endpoint remains outside Kubernetes. The helper derives guest addresses and SSH settings from the inventory, so these commands work in a new terminal without sourcing anything.

Return to [submit a batch and inspect the service](README.md#2-submit-a-batch-and-inspect-the-service), then use the check below before measured captures.

## Check the service and forecast inputs

After the manual four-image batch completes, run:

~~~bash
bash application/image_batch/scripts/student_demo.sh check
~~~

Expect an eligible completed execution profile and a message that the demo is ready for captures. The check requires seven Ready Kubernetes nodes, control-plane isolation, working node metrics, no active Jobs, Ready adapter/observer containers with zero restarts, and advancing observer state.

The profile must contain four images, 128 inference repetitions, at least three resource samples, and valid resource fragments. A succeeded Job alone does not establish this. Allow time for profile emission; if it remains ineligible, inspect observer errors, Prometheus reachability and scraping before spending time on a full trio:

~~~bash
bash application/image_batch/scripts/student_demo.sh kubectl logs -n fns-demo \
  deployment/image-batch-adapter -c opendt-observer --tail=20
~~~

The workload must run long enough on the assigned hardware to collect those samples. The template's `/data` and `/var/lib/opendt` are ephemeral; replacing its Pod discards them. Measured captures collect their own copies automatically.

Return to [capture a matched policy comparison](README.md#3-capture-a-matched-policy-comparison).
