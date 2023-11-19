"""Generate a Terraform  settings.configuration for GCP"""

import settings

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


def generate_header():
    """Write the Terraform config header"""
    with open(".tmp/header.tf", mode="w", encoding="utf-8") as f:
        f.write(HEADER)

        f.write(
            PROVIDER
            % (
                settings.config["infrastructure"]["gcp_credentials"],
                settings.config["infrastructure"]["gcp_project"],
                settings.config["infrastructure"]["gcp_region"],
                settings.config["infrastructure"]["gcp_zone"],
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


def generate_network():
    """Write the Terraform  settings.config network"""
    with open(".tmp/network.tf", mode="w", encoding="utf-8") as f:
        f.write(MAIN_NETWORK)

        if settings.config["infrastructure"]["cloud_nodes"] > 0:
            f.write(CLOUD_NETWORK)

        if settings.config["infrastructure"]["edge_nodes"] > 0:
            f.write(EDGE_NETWORK)

        if settings.config["infrastructure"]["endpoint_nodes"] > 0:
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


def generate_vm():
    """Write the Terraform cloud VM configuration"""
    if settings.config["infrastructure"]["cloud_nodes"] > 0:
        with open(".tmp/cloud_vm.tf", mode="w", encoding="utf-8") as f:
            f.write(CLOUD_IP % (settings.config["infrastructure"]["cloud_nodes"]))
            f.write(
                CLOUD
                % (
                    settings.config["infrastructure"]["gcp_cloud"],
                    settings.config["infrastructure"]["cloud_nodes"],
                    "%s.pub" % (settings.config["ssh_key"]),
                )
            )

    if settings.config["infrastructure"]["edge_nodes"] > 0:
        with open(".tmp/edge_vm.tf", mode="w", encoding="utf-8") as f:
            f.write(EDGE_IP % (settings.config["infrastructure"]["edge_nodes"]))
            f.write(
                EDGE
                % (
                    settings.config["infrastructure"]["gcp_edge"],
                    settings.config["infrastructure"]["edge_nodes"],
                    "%s.pub" % (settings.config["ssh_key"]),
                )
            )

    if settings.config["infrastructure"]["endpoint_nodes"] > 0:
        with open(".tmp/endpoint_vm.tf", mode="w", encoding="utf-8") as f:
            f.write(ENDPOINT_IP % (settings.config["infrastructure"]["endpoint_nodes"]))
            f.write(
                ENDPOINT
                % (
                    settings.config["infrastructure"]["gcp_endpoint"],
                    settings.config["infrastructure"]["endpoint_nodes"],
                    "%s.pub" % (settings.config["ssh_key"]),
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


def generate_output():
    """Write the Terraform  settings.config output definition"""
    with open(".tmp/outputs.tf", mode="w", encoding="utf-8") as f:
        if settings.config["infrastructure"]["cloud_nodes"] > 0:
            f.write(OUTPUT_CLOUD)

        if settings.config["infrastructure"]["edge_nodes"] > 0:
            f.write(OUTPUT_EDGE)

        if settings.config["infrastructure"]["endpoint_nodes"] > 0:
            f.write(OUTPUT_ENDPOINT)


###################################################################################################


def start():
    """Generate Terraform  settings.configuration files for the Continuum  settings.configuration
    The  settings.configuration is spread over multiple files to make reading easier.
    """
    generate_header()
    generate_network()
    generate_vm()
    generate_output()
