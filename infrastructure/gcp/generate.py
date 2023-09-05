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
  credentials = file(%s)
  project     = %s
  region      = %s
  zone        = %s
}
"""


def generate_header(config):
    """Write the Terraform config header

    Args:
        config (dict): Parsed configuration
    """
    with open(".tmp/header.tf", mode="w", encoding="utf-8") as f:
        f.write(HEADER)

        f.write(
            PROVIDER
            % (
                config["infrastructure"]["gcp_credentials"],
                config["infrastructure"]["gcp_project"],
                config["infrastructure"]["gcp_region"],
                config["infrastructure"]["gcp_zone"],
            )
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

EDGE_NETWORK = """
resource "google_compute_subnetwork" "subnetwork_edge" {
    name          = "subnetwork-edge"
    ip_cidr_range = "10.0.1.0/24"
    network       = google_compute_network.vpc_network.id
}
"""

ENDPOINT_NETWORK = """
resource "google_compute_subnetwork" "subnetwork_endpoint" {
    name          = "subnetwork-endpoint"
    ip_cidr_range = "10.0.2.0/24"
    network       = google_compute_network.vpc_network.id
}
"""

INGRESS = """
resource "google_compute_firewall" "allow_all_ingress" {
    name      = "vpc-network-allow-all-ingress"
    network   = google_compute_network.vpc_network.name
    direction = "INGRESS"

    allow {
        protocol = "all"
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
        protocol = "all"
    }
}
"""


def generate_network(config):
    """Write the Terraform config network

    Args:
        config (dict): Parsed configuration
    """
    with open(".tmp/network.tf", mode="w", encoding="utf-8") as f:
        f.write(MAIN_NETWORK)

        if config["infrastructure"]["cloud_nodes"] > 0:
            f.write(CLOUD_NETWORK)

        if config["infrastructure"]["edge_nodes"] > 0:
            f.write(EDGE_NETWORK)

        if config["infrastructure"]["endpoint_nodes"] > 0:
            f.write(ENDPOINT_NETWORK)

        f.write(INGRESS)
        f.write(EGRESS)


###################################################################################################

CLOUD_IP = """
resource "google_compute_address" "cloud_static_ip" {
    name = "cloud${count.index}-static-ip"
    count = %i
}
"""

EDGE_IP = """
resource "google_compute_address" "edge_static_ip" {
    name = "edge${count.index}-static-ip"
    count = %i
}
"""

ENDPOINT_IP = """
resource "google_compute_address" "endpoint_static_ip" {
    name = "endpoint${count.index}-static-ip"
    count = %i
}
"""

CLOUD = """
resource "google_compute_instance" "cloud" {
    name         = "cloud${count.index}"
    machine_type = %s
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
            nat_ip = element(google_compute_address.cloud_static_ip.*.address, count.index)
        }
    }

    service_account {
        scopes = ["cloud-platform"]
    }

    metadata = {
        ssh-keys = "cloud${count.index}:${file("%s")}"
    }

    can_ip_forward = true
}
"""

EDGE = """
resource "google_compute_instance" "edge" {
    name         = "edge${count.index}"
    machine_type = %s
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
        subnetwork = google_compute_subnetwork.subnetwork_edge.name
        access_config {
            nat_ip = element(google_compute_address.edge_static_ip.*.address, count.index)
        }
    }

    service_account {
        scopes = ["cloud-platform"]
    }

    metadata = {
        ssh-keys = "edge${count.index}:${file("%s")}"
    }

    can_ip_forward = true
}
"""

ENDPOINT = """
resource "google_compute_instance" "endpoint" {
    name         = "endpoint${count.index}"
    machine_type = %s
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
        subnetwork = google_compute_subnetwork.subnetwork_endpoint.name
        access_config {
            nat_ip = element(google_compute_address.endpoint_static_ip.*.address, count.index)
        }
    }

    service_account {
        scopes = ["cloud-platform"]
    }

    metadata = {
        ssh-keys = "endpoint${count.index}:${file("%s")}"
    }

    can_ip_forward = true
}
"""


def generate_vm(config):
    """Write the Terraform config cloud VM configuration

    Args:
        config (dict): Parsed configuration
    """
    if config["infrastructure"]["cloud_nodes"] > 0:
        with open(".tmp/cloud_vm.tf", mode="w", encoding="utf-8") as f:
            f.write(CLOUD_IP % (config["infrastructure"]["cloud_nodes"]))
            f.write(
                CLOUD
                % (
                    config["infrastructure"]["gcp_cloud"],
                    config["infrastructure"]["cloud_nodes"],
                    "%s.pub" % (config["ssh_key"]),
                )
            )

    if config["infrastructure"]["edge_nodes"] > 0:
        with open(".tmp/edge_vm.tf", mode="w", encoding="utf-8") as f:
            f.write(EDGE_IP % (config["infrastructure"]["edge_nodes"]))
            f.write(
                EDGE
                % (
                    config["infrastructure"]["gcp_edge"],
                    config["infrastructure"]["edge_nodes"],
                    "%s.pub" % (config["ssh_key"]),
                )
            )

    if config["infrastructure"]["endpoint_nodes"] > 0:
        with open(".tmp/endpoint_vm.tf", mode="w", encoding="utf-8") as f:
            f.write(ENDPOINT_IP % (config["infrastructure"]["endpoint_nodes"]))
            f.write(
                ENDPOINT
                % (
                    config["infrastructure"]["gcp_endpoint"],
                    config["infrastructure"]["endpoint_nodes"],
                    "%s.pub" % (config["ssh_key"]),
                )
            )


###################################################################################################

OUTPUT_CLOUD = """
output "cloud_ip_internal" {
  value = ["${google_compute_instance.cloud.*.network_interface.0.network_ip}"]
}

output "cloud_ip_external" {
  value = ["${google_compute_address.cloud_static_ip.*.address}"]
}
"""

OUTPUT_EDGE = """
output "edge_ip_internal" {
  value = ["${google_compute_instance.edge.*.network_interface.0.network_ip}"]
}

output "edge_ip_external" {
  value = ["${google_compute_address.edge_static_ip.*.address}"]
}
"""

OUTPUT_ENDPOINT = """
output "endpoint_ip_internal" {
  value = ["${google_compute_instance.endpoint.*.network_interface.0.network_ip}"]
}

output "endpoint_ip_external" {
  value = ["${google_compute_address.endpoint_static_ip.*.address}"]
}
"""


def generate_output(config):
    """Write the Terraform config output definition

    Args:
        config (dict): Parsed configuration
    """
    with open(".tmp/outputs.tf", mode="w", encoding="utf-8") as f:
        if config["infrastructure"]["cloud_nodes"] > 0:
            f.write(OUTPUT_CLOUD)

        if config["infrastructure"]["edge_nodes"] > 0:
            f.write(OUTPUT_EDGE)

        if config["infrastructure"]["endpoint_nodes"] > 0:
            f.write(OUTPUT_ENDPOINT)


###################################################################################################


def start(config, _machines):
    """Generate Terraform configuration files for the Continuum configuration
    The configuration is spread over multiple files to make reading easier.

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    generate_header(config)
    generate_network(config)
    generate_vm(config)
    generate_output(config)
