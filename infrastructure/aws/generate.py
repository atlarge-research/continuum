"""Generate a Terraform configuration for AWS"""

# 0. Header

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


# 1️. Vpc

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

# 2️. Subnets

CLOUD_NETWORK = """
resource "aws_subnet" "subnetwork_cloud" {
    cidr_block        = "10.0.0.0/24"
    vpc_id            = aws_vpc.vpc_network.id
    availability_zone = %s
    tags = {
        Name = "aws_continuum_cloud_subnet"
    }
}
"""

EDGE_NETWORK = """
resource "aws_subnet" "subnetwork_edge" {
    cidr_block        = "10.0.1.0/24"
    vpc_id            = aws_vpc.vpc_network.id
    availability_zone = %s
    tags = {
        Name = "aws_continuum_edge_subnet"
    }
}
"""
ENDPOINT_NETWORK = """
resource "aws_subnet" "subnetwork_endpoint" {
    cidr_block        = "10.0.2.0/24"
    vpc_id            = aws_vpc.vpc_network.id
    availability_zone = %s
    tags = {
        Name = "aws_continuum_endpoint_subnet"
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

# 3️. Security groups

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
            f.write(CLOUD_NETWORK % (config["infrastructure"]["aws_zone"]))

        if config["infrastructure"]["edge_nodes"] > 0:
            f.write(EDGE_NETWORK % (config["infrastructure"]["aws_zone"]))

        if config["infrastructure"]["endpoint_nodes"] > 0:
            f.write(ENDPOINT_NETWORK % (config["infrastructure"]["aws_zone"]))

        f.write(SECURITY_GROUP)


# 4. SSH key

KEY = """
resource "aws_key_pair" "public_ssh_key" {
  key_name   = "public_ssh_key"
  public_key = file("%s")
}
"""


def generate_key(config):
    """Write the public SSH key to use to access VMs

    Args:
        config (dict): Parsed configuration
    """
    with open(".tmp/sshkey.tf", mode="w", encoding="utf-8") as f:
        f.write(KEY % (config["ssh_key"] + ".pub"))


# 5. Instances

USER = """
provisioner "remote-exec" {
    inline = [
        "sudo useradd -d /home/%s${count.index}/ -G ubuntu,adm,sudo,lxd -s/bin/bash -m %s${count.index}",
        "sudo mkdir -p /home/%s${count.index}/.ssh",
        "sudo cp /home/ubuntu/.ssh/authorized_keys /home/%s${count.index}/.ssh/authorized_keys",
        "sudo chown -R %s${count.index}:%s${count.index} /home/%s${count.index}/.ssh",
        "sudo chmod 700 /home/%s${count.index}/.ssh",
        "echo '%%sudo ALL=(ALL:ALL) NOPASSWD:ALL' | sudo EDITOR='tee -a' visudo",
   ]

    connection {
        type        = "ssh"
        user        = "ubuntu"
        private_key = "${file("%s")}"
        host        = self.public_ip
    }
}
"""

CLOUD = """
resource "aws_instance" "cloud" {
    count                       = %i
    instance_type               = %s
    ami                         = %s
    key_name                    = aws_key_pair.public_ssh_key.key_name
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
    %s
}
"""

EDGE = """
resource "aws_instance" "edge" {
    count                       = %i
    instance_type               = %s
    ami                         = %s
    key_name                    = aws_key_pair.public_ssh_key.key_name
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
    %s
}
"""

ENDPOINT = """
resource "aws_instance" "endpoint" {
    count                       = %i
    instance_type               = %s
    ami                         = %s
    key_name                    = aws_key_pair.public_ssh_key.key_name
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
    %s
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
                    USER % (8 * ("cloud",) + (config["ssh_key"],)),
                )
            )

    if config["infrastructure"]["edge_nodes"] > 0:
        with open(".tmp/edge_vm.tf", mode="w", encoding="utf-8") as f:
            f.write(
                EDGE
                % (
                    config["infrastructure"]["edge_nodes"],
                    config["infrastructure"]["aws_edge"],
                    config["infrastructure"]["aws_ami"],
                    USER % (8 * ("edge",) + (config["ssh_key"],)),
                )
            )

    if config["infrastructure"]["endpoint_nodes"] > 0:
        with open(".tmp/endpoint_vm.tf", mode="w", encoding="utf-8") as f:
            f.write(
                ENDPOINT
                % (
                    config["infrastructure"]["endpoint_nodes"],
                    config["infrastructure"]["aws_endpoint"],
                    config["infrastructure"]["aws_ami"],
                    USER % (8 * ("endpoint",) + (config["ssh_key"],)),
                )
            )


# 5. Output

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
    generate_key(config)
    generate_vm(config)
    generate_output(config)
