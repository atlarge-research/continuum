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
  region      = %s
  access_key  = %s
  secret_key  = %s
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
                config["infrastructure"]["aws_region"],
                config["infrastructure"]["aws_access_keys"],
                config["infrastructure"]["aws_secret_access_keys"],
            )
        )


###################################################################################################

# 1️⃣ Vpc


MAIN_NETWORK = """
resource "aws_vpc" "vpc_network" {
    cidr_block              = "10.0.0.0/16"
    tags = {
        Name = "aws_continuum_vpc"
    }
}

resource "aws_internet_gateway" "igw" {
    vpc_id = aws_vpc.vpc_network.id
    tags = {
        Name = "aws_continuum_igw"
    }
}
"""

# 2️⃣ Subnets

CLOUD_NETWORK = """
resource "aws_subnet" "subnetwork_cloud" {
    cidr_block        = "10.0.0.0/24"
    vpc_id            = aws_vpc.vpc_network.id
    availability_zone = "eu-central-1a"
    tags = {
        Name = "aws_columbo_cloud_subnet"
    }
}
"""

EDGE_NETWORK = """
resource "aws_subnet" "subnetwork_edge" {
    cidr_block        = "10.0.1.0/24"
    vpc_id            = aws_vpc.vpc_network.id
    availability_zone = "eu-central-1b"
    tags = {
        Name = "aws_columbo_edge_subnet"
    }
}
"""
ENDPOINT_NETWORK = """
resource "aws_subnet" "subnetwork_endpoint" {
    cidr_block        = "10.0.2.0/24"
    vpc_id            = aws_vpc.vpc_network.id
    availability_zone = "eu-central-1c"
    tags = {
        Name = "aws_columbo_endpoint_subnet"
    }
}
"""

ROUTE_TABLES = """
resource "aws_route_table" "route_table" {
    vpc_id = aws_vpc.vpc_network.id
    tags = {
        Name = "route_table_cloud"
    }
}

resource "aws_route" "route_igw" {
    route_table_id         = aws_route_table.route_table.id
    gateway_id             = aws_internet_gateway.igw.id
    destination_cidr_block = "0.0.0.0/0"
}

resource "aws_route_table_association" "route_table_associations" {
    subnet_id      = aws_subnet.subnetwork_cloud.id
    route_table_id = aws_route_table.route_table.id
}
"""

# 3️⃣ Security groups

# for all
SECURITY_GROUP = """
resource "aws_security_group" "allow_all_ingress_egress" {
    name      = "vpc-network-allow-all-ingress"
    vpc_id    = aws_vpc.vpc_network.id

    ingress {
        description = "Allow all inbound connection"
        from_port   = 0
        to_port     = 0
        protocol    = "-1"
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

        f.write(ROUTE_TABLES)

        if config["infrastructure"]["cloud_nodes"] > 0:
            f.write(CLOUD_NETWORK)

        if config["infrastructure"]["edge_nodes"] > 0:
            f.write(EDGE_NETWORK)

        if config["infrastructure"]["endpoint_nodes"] > 0:
            f.write(ENDPOINT_NETWORK)

        f.write(SECURITY_GROUP)


###################################################################################################

# 4️⃣ Elastic IP Addresses

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
resource "aws_instance" "cloud" {
    count                       = %i
    instance_type               = %s
    ami                         = %s
    key_name                    = %s
    security_groups             = [ aws_security_group.allow_all_ingress_egress.id ]
    subnet_id                   = aws_subnet.subnetwork_cloud.id
    associate_public_ip_address = true

    root_block_device {
        volume_size = 30
        volume_type = "gp3"
    }

    tags = {
        Name = "cloud_${count.index}"
    }
}
"""

EDGE = """
resource "aws_instance" "edge" {
    count                       = %i
    instance_type               = %s
    ami                         = %s
    key_name                    = %s
    security_groups             = [ aws_security_group.allow_all_ingress_egress.id ]
    subnet_id                   = aws_subnet.subnetwork_cloud.id
    associate_public_ip_address = true

    root_block_device {
        volume_size = 30
        volume_type = "gp3"
    }

    tags = {
        Name = "edge_${count.index}"
    }
}
"""

ENDPOINT = """
resource "aws_instance" "endpoint" {
    count                       = %i
    instance_type               = %s
    ami                         = %s
    key_name                    = %s
    security_groups             = [ aws_security_group.allow_all_ingress_egress.id ]
    subnet_id                   = aws_subnet.subnetwork_cloud.id
    associate_public_ip_address = true

    root_block_device {
        volume_size = 30
        volume_type = "gp3"
    }

    tags = {
        Name = "endpoint_${count.index}"
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
            f.write(
                CLOUD
                % (
                    config["infrastructure"]["cloud_nodes"],
                    config["infrastructure"]["aws_cloud"],
                    config["infrastructure"]["aws_ami"],
                    config["infrastructure"]["aws_key"],
                )
            )

    if config["infrastructure"]["edge_nodes"] > 0:
        with open(".tmp/edge_vm.tf", mode="w", encoding="utf-8") as f:
            f.write(EDGE_IP % (config["infrastructure"]["edge_nodes"]))
            f.write(
                EDGE
                % (
                    config["infrastructure"]["edge_nodes"],
                    config["infrastructure"]["aws_edge"],
                    config["infrastructure"]["aws_ami"],
                    config["infrastructure"]["aws_key"],
                )
            )

    if config["infrastructure"]["endpoint_nodes"] > 0:
        with open(".tmp/endpoint_vm.tf", mode="w", encoding="utf-8") as f:
            f.write(ENDPOINT_IP % (config["infrastructure"]["endpoint_nodes"]))
            f.write(
                ENDPOINT
                % (
                    config["infrastructure"]["endpoint_nodes"],
                    config["infrastructure"]["aws_endpoint"],
                    config["infrastructure"]["aws_ami"],
                    config["infrastructure"]["aws_key"],
                )
            )


###################################################################################################

OUTPUT_CLOUD = """
output "cloud_ip_internal" {
  value = ["${aws_instance.cloud.*.private_ip}"]
}
output "cloud_ip_external" {
  value = ["${aws_instance.cloud.*.public_ip}"]
}
"""

OUTPUT_EDGE = """
output "edge_ip_internal" {
  value = ["${aws_instance.edge.*.private_ip}"]
}
output "edge_ip_external" {
  value = ["${aws_instance.edge.*.public_ip}"]
}
"""

OUTPUT_ENDPOINT = """
output "endpoint_ip_internal" {
  value = ["${aws_instance.endpoint.*.private_ip}"]
}

output "endpoint_ip_external" {
  value = ["${aws_instance.endpoint.*.public_ip}"]
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
