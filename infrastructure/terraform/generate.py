"""Generate a Terraform configuration for GCP"""


###################################################################################################

HEADER = """
terraform {
    required_version = ">= 1.3.6"
    required_providers {
        google = {
            source  = "hashicorp/google"
            version = "4.46.0"
        }
    }
}
"""

PROVIDER = """
provider "google" {
  credentials = file("%s")
  project     = "%s"
  region      = "%s"
  zone        = "%s"
}
"""


def generate_header(config):
    """Write the Terraform config header

    Args:
        config (dict): Parsed configuration
    """
    with open("header.tf", mode="w", encoding="utf-8") as f:
        f.write(HEADER)

        f.write(
            PROVIDER % (config["credentials"], config["project"], config["region"], config["zone"])
        )


###################################################################################################

MAIN_NETWORK = """
resource "google_compute_network" "vpc_network" {
    name                    = "vpc-network"
    routing_mode            = "GLOBAL"
    auto_create_subnetworks = false
}
"""

CLOUD_NETWORK = """
resource "google_compute_subnetwork" "subnetwork_cloud" {
    name          = "subnetwork-cloud"
    ip_cidr_range = "10.0.0.0/24"
    network       = google_compute_network.vpc_network.id
}
"""

# ENDPOINT_NETWORK = """
# resource "google_compute_subnetwork" "subnetwork_edge" {
#     name          = "subnetwork-edge"
#     ip_cidr_range = "10.0.1.0/24"
#     network       = google_compute_network.vpc_network.id
# }
# """

INGRESS = """
resource "google_compute_firewall" "allow_all_ingress" {
    name      = "vpc-network-allow-all-ingress"
    network   = google_compute_network.vpc_network.name
    direction = "INGRESS"

    allow {
        protocol = "icmp"
    }

    allow {
        protocol = "tcp"
        ports    = ["0-65535"]
    }

    source_ranges = ["0.0.0.0/0"]
}
"""

EGRESS = """
resource "google_compute_firewall" "allow_all_egress" {
    name      = "vpc-network-allow-all-egress"
    network   = google_compute_network.vpc_network.name
    direction = "EGRESS"

    allow {
        protocol = "icmp"
    }

    allow {
        protocol = "tcp"
        ports    = ["0-65535"]
    }
}
"""


def generate_network(_config):
    """Write the Terraform config network

    Args:
        config (dict): Parsed configuration
    """
    with open("network.tf", mode="w", encoding="utf-8") as f:
        f.write(MAIN_NETWORK)
        f.write(CLOUD_NETWORK)
        # f.write(ENDPOINT_NETWORK % (config["region"]))
        f.write(INGRESS)
        f.write(EGRESS)


###################################################################################################

CLOUD_CONTROLLER_IP = """
resource "google_compute_address" "k8s_controlplane_static_ip" {
    name = "k8s-controlplane-static-ip"
}
"""

# NOTE: Create multiple when having count > 1
CLOUD_WORKER_IP = """
resource "google_compute_address" "k8s_worker_static_ip" {
    name = "k8s-worker-static-ip"
}
"""

CLOUD_CONTROLLER = """
resource "google_compute_instance" "k8s_controlplane" {
    name         = "k8s-controlplane"
    machine_type = "e2-small"

    boot_disk {
        initialize_params {
            size  = "30"
            type  = "pd-standard"
            image = "ubuntu-os-cloud/ubuntu-2004-lts"
        }
    }

    network_interface {
        network    = google_compute_network.vpc_network.name
        subnetwork = google_compute_subnetwork.subnetwork_cloud.name
        access_config {
            nat_ip = google_compute_address.k8s_controlplane_static_ip.address
        }
    }

    service_account {
        scopes = ["cloud-platform"]
    }

    metadata = {
        ssh-keys = "redplanet00:${file("~/.ssh/id_rsa_benchmark.pub")}"
    }
}
"""

CLOUD_WORKER = """
resource "google_compute_instance" "k8s_worker" {
    name         = "k8s-worker"
    machine_type = "e2-small"
    count        = %i

    boot_disk {
        initialize_params {
            size  = "30"
            type  = "pd-standard"
            image = "ubuntu-os-cloud/ubuntu-2004-lts"
        }
    }

    network_interface {
        network    = google_compute_network.vpc_network.name
        subnetwork = google_compute_subnetwork.subnetwork_cloud.name
        access_config {
            nat_ip = google_compute_address.k8s_worker_static_ip.address
        }
    }

    service_account {
        scopes = ["cloud-platform"]
    }

    metadata = {
        ssh-keys = "redplanet00:${file("~/.ssh/id_rsa_benchmark.pub")}"
    }
}
"""


def generate_cloud(config):
    """Write the Terraform config cloud VM configuration

    Args:
        config (dict): Parsed configuration
    """
    with open("cloud_vm.tf", mode="w", encoding="utf-8") as f:
        f.write(CLOUD_CONTROLLER_IP)
        f.write(CLOUD_WORKER_IP)
        f.write(CLOUD_CONTROLLER)
        f.write(CLOUD_WORKER % (config["cloud_nodes"]))


###################################################################################################

OUTPUT = """
output "subnetwork_1_name" {
  value = google_compute_subnetwork.subnetwork_cloud.name
}

output "ip_controller" {
  value = google_compute_instance.k8s_controlplane.network_interface.0.network_ip
}

output "ip_worker" {
  value = ["${google_compute_instance.k8s_worker.*.network_interface.0.network_ip}"]
}

output "stattic_ip_controller" {
    value = google_compute_address.k8s_controlplane_static_ip.address
}

output "stattic_ip_worker" {
    value = google_compute_address.k8s_worker_static_ip.address
}
"""

# output "subnetwork_2_name" {
#   value = google_compute_subnetwork.subnetwork_edge.name
# }


def generate_output(_config):
    """Write the Terraform config output definition

    Args:
        config (dict): Parsed configuration
    """
    with open("outputs.tf", mode="w", encoding="utf-8") as f:
        f.write(OUTPUT)


###################################################################################################


def start(_config, _machines):
    """Generate Terraform configuration files for the Continuum configuration
    The configuration is spread over multiple files to make reading easier.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    manual_config = {
        "region": "europe-west4",
        "zone": "europe-west4-a",
        "project": "continuum-372108",
        "credentials": "/home/redplanet00/.ssh/continuum-372108-9f6a709ba92c.json",
        "cloud_nodes": 1,
        "endpoint_nodes": 1,
    }

    generate_header(manual_config)
    generate_network(manual_config)
    generate_cloud(manual_config)
    # generate_endpoint(config)
    generate_output(manual_config)


# TODO
# Step 1: Infra
# - Generate correct configurations, without software installation
# - Process the output (or manually run terraform output) to print SSH commands to the VMs on GCP
# - Check if all those steps work within the Continuum framework
#
# Step 2: Software
# - Convince Ansible to work with the Terraform / GCP stack
# - Update Ansible YML files to work with these VMs
#   - Think of usernames, network edits, etc.
#   - What are the infra / os differences between QEMU / TF GCP
#   - Would be nice to keep using a single .yml file no matter the infra
# - Check if software works, so rm_only = True
#
# Step 3: Benchmark
# - Check if you can run the benchmark as expected
# - Compare results with QEMU runs
