# --- build_terraform: turns extracted services into Alibaba Cloud main.tf ---

import logging
from app.services.build_configs import RUNTIME_PORTS, APP_RUNTIMES

logger = logging.getLogger(__name__)

INFRA_PORTS = {
    "postgresql": 5432,
    "mysql": 3306,
    "redis": 6379,
    "mongodb": 27017,
}


def build_terraform(services: list[str]) -> str | None:
    """
    Takes the extracted services list, returns a complete main.tf
    for Alibaba Cloud (Alicloud) with VPC, VSwitch, Security Group,
    and optionally an ECS instance if an app runtime is detected.
    Returns None if no services matched.
    """
    if not isinstance(services, list):
        logger.error(f"build_terraform expected a list, got {type(services)}")
        return None

    # Classify which services are app runtimes vs infrastructure
    matched_runtimes = [s for s in services if s in APP_RUNTIMES]
    matched_infra = [s for s in services if s in INFRA_PORTS]

    if not matched_runtimes and not matched_infra:
        logger.warning(f"build_terraform: no matching services for {services}")
        return None

    # Collect all ports that need to be opened in the security group
    open_ports = [22]  # Always open SSH
    for runtime in matched_runtimes:
        port = RUNTIME_PORTS.get(runtime, 3000)
        if port not in open_ports:
            open_ports.append(port)
    for infra in matched_infra:
        port = INFRA_PORTS[infra]
        if port not in open_ports:
            open_ports.append(port)

    # --- Build the file in sections ---

    # 1. Provider + variables
    provider_block = (
        'variable "region" {\n'
        '  description = "Alibaba Cloud region"\n'
        '  default     = "ap-southeast-1"\n'
        '}\n'
        '\n'
        'variable "instance_type" {\n'
        '  description = "ECS instance type"\n'
        '  default     = "ecs.t6-c1m1.large"\n'
        '}\n'
        '\n'
        'provider "alicloud" {\n'
        '  region = var.region\n'
        '}\n'
    )

    # 2. VPC + VSwitch
    vpc_block = (
        '\n'
        'resource "alicloud_vpc" "voicops_vpc" {\n'
        '  vpc_name   = "voicops-vpc"\n'
        '  cidr_block = "172.16.0.0/16"\n'
        '}\n'
        '\n'
        'resource "alicloud_vswitch" "voicops_vsw" {\n'
        '  vpc_id     = alicloud_vpc.voicops_vpc.id\n'
        '  cidr_block = "172.16.0.0/24"\n'
        '  zone_id    = "ap-southeast-1a"\n'
        '}\n'
    )

    # 3. Security Group with ingress rules for each port
    ingress_rules = ""
    port_descriptions = {
        22: "SSH",
        3000: "Node.js app",
        5000: "Flask app",
        8000: "FastAPI/Django app",
        5432: "PostgreSQL",
        3306: "MySQL",
        6379: "Redis",
        27017: "MongoDB",
    }
    for port in open_ports:
        desc = port_descriptions.get(port, f"Port {port}")
        ingress_rules += (
            '\n'
            '  ingress {\n'
            f'    description = "{desc}"\n'
            '    from_port   = ' + str(port) + '\n'
            '    to_port     = ' + str(port) + '\n'
            '    ip_protocol = "tcp"\n'
            '    cidr_blocks = ["0.0.0.0/0"]\n'
            '  }\n'
        )

    sg_block = (
        '\n'
        'resource "alicloud_security_group" "voicops_sg" {\n'
        '  name   = "voicops-sg"\n'
        '  vpc_id = alicloud_vpc.voicops_vpc.id\n'
        f'{ingress_rules}'
        '}\n'
    )

    # 4. ECS Instance (only if an app runtime is detected)
    ecs_block = ""
    if matched_runtimes:
        runtime = matched_runtimes[0]  # Primary runtime
        ecs_block = (
            '\n'
            'resource "alicloud_instance" "voicops_ecs" {\n'
            '  instance_name        = "voicops-app"\n'
            '  instance_type        = var.instance_type\n'
            '  image_id             = "ubuntu_22_04_x64_20G_alibase_20231221.vhd"\n'
            '  vswitch_id           = alicloud_vswitch.voicops_vsw.id\n'
            '  security_groups      = [alicloud_security_group.voicops_sg.id]\n'
            '  system_disk_category = "cloud_efficiency"\n'
            '  system_disk_size     = 40\n'
            '}\n'
            '\n'
            'output "ecs_public_ip" {\n'
            '  value = alicloud_instance.voicops_ecs.public_ip\n'
            '}\n'
        )

    terraform_content = provider_block + vpc_block + sg_block + ecs_block

    return terraform_content
