"""Generate a Terraform configuration for GCP"""

###################################################################################################

HEADER = """
terraform {
    required_version = ">= 1.3.6"
    required_providers {
        aws = {
        source  = "hashicorp/aws"
        version = "~> 5.0"
        }
    }
}
"""

PROVIDER = """
provider "aws" {
  credentials = file(%s)
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

# 1️⃣ Vpc
# ❓ What is the cidr block for the network


MAIN_NETWORK = """
resource "aws_vpc" "vpc_network" {
    name                    = "vpc-network"
    cidr_block              = "10.0.0.0/16"
}
"""

# 2️⃣ Subnets

CLOUD_NETWORK = """
resource "aws_subnet" "subnetwork_cloud" {
    name          = "subnetwork-cloud"
    ip_cidr_range = "10.0.0.0/24"
    vpc_id        = aws_vpc.vpc_network.id
}
"""

EDGE_NETWORK = """
resource "aws_subnet" "subnetwork_edge" {
    name          = "subnetwork-edge"
    ip_cidr_range = "10.0.1.0/24"
    vpc_id        = aws_vpc.vpc_network.id
}
"""
ENDPOINT_NETWORK = """
resource "aws_subnet" "subnetwork_endpoint" {
    name          = "subnetwork-endpoint"
    ip_cidr_range = "10.0.2.0/24"
    vpc_id        = aws_vpc.vpc_network.id
}
"""

# 3️⃣ Security groups


SECURITY_GROUP = """
resource "aws_security_group" "allow_all_ingress" {
    name      = "vpc-network-allow-all-ingress"
    vpc_id    = aws_vpc.vpc_network.id
    direction = "INGRESS"

    ingress {
        description = "Allow all inbound connection"
        from_port   = 0
        to_port     = 65535
        protocol    = "tcp"
        cidr_blocks = ["0.0.0.0/0"]
    }

    egress {
        description = "Allow all outbound connection"
        from_port   = 0
        to_port     = 0
        protocol    = "-1"
        cidr_blocks = ["0.0.0.0/0"]
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

        f.write(SECURITY_GROUP)


###################################################################################################

# 4️⃣ Elastic IP Addresses
# ❓ Should there be any associations with the instances here?
CLOUD_IP = """
resource "aws_eip" "cloud_static_ip" {
    name = "cloud${count.index}-static-ip"
    count = %i
}
"""

EDGE_IP = """
resource "aws_eip" "edge_static_ip" {
    name = "edge${count.index}-static-ip"
    count = %i
}
"""

ENDPOINT_IP = """
resource "aws_eip" "endpoint_static_ip" {
    name = "endpoint${count.index}-static-ip"
    count = %i
}
"""

# 5️⃣ Instances
# ❓ Would service accounts be necessary
# ❓ Do you need another block device attached to the instance

AMI = """
data "aws_ami" "ubuntu" {
  most_recent = true

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-focal-20.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }

  owners = ["099720109477"] # Canonical
}
"""

CLOUD = """
resource "aws_network_interface" "cloud_interface" {
    count       = %i
    subnet_id   = aws_subnet.subnetwork_cloud.id
    private_ips = element(aws_eip.cloud_static_ip.*.address, count.index)
}

resource "aws_instance" "cloud" {
    name          = "cloud${count.index}"
    instance_type = %s
    ami           = data.aws_ami.ubuntu.id
    count         = %i

    root_block_device {
        volume_size = 30,
        volume_type = gp3
    }

    network_interface {
        network_interface_id = aws_network_interface.cloud_interface.id
        device_index         = 0
    }
}
"""

EDGE = """
resource "aws_network_interface" "edge_interface" {
    count       = %i
    subnet_id   = aws_subnet.subnetwork_edge.id
    private_ips = element(aws_eip.edge_static_ip.*.address, count.index)
}

resource "aws_instance" "edge" {
    name          = "edge${count.index}"
    instance_type = %s
    ami           = data.aws_ami.ubuntu.id
    count         = %i

    root_block_device {
        volume_size = 30,
        volume_type = gp3
    }

    network_interface {
        network_interface_id = aws_network_interface.edge_interface.id
        device_index         = 0
    }
}
"""

ENDPOINT = """
resource "aws_network_interface" "endpoint_interface" {
    count       = %i
    subnet_id   = aws_subnet.subnetwork_endpoint.id
    private_ips = element(aws_eip.endpoint_static_ip.*.address, count.index)
}

resource "aws_instance" "endpoint" {
    name          = "endpoint${count.index}"
    instance_type = %s
    ami           = data.aws_ami.ubuntu.id
    count         = %i

    root_block_device {
        volume_size = 30,
        volume_type = gp3
    }

    network_interface {
        network_interface_id = aws_network_interface.endpoint_interface.id
        device_index         = 0
    }
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
