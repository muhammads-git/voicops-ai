# tests/test_build_terraform.py — tests for Terraform main.tf generation

import pytest
from app.services.build_terraform import build_terraform, INFRA_PORTS


class TestBuildTerraformWithRuntimes:
    def test_nodejs_generates_terraform(self):
        result = build_terraform(["nodejs"])
        assert result is not None
        assert "alicloud" in result
        assert "alicloud_vpc" in result
        assert "alicloud_security_group" in result
        assert "alicloud_instance" in result  # ECS instance for runtimes

    def test_fastapi_generates_ecs(self):
        result = build_terraform(["fastapi"])
        assert result is not None
        assert "alicloud_instance" in result
        assert "8000" in result  # FastAPI port

    def test_includes_ssh_port(self):
        result = build_terraform(["nodejs"])
        assert "22" in result  # SSH always open

    def test_includes_runtime_port(self):
        result = build_terraform(["flask"])
        assert "5000" in result


class TestBuildTerraformInfraOnly:
    def test_postgresql_no_ecs(self):
        result = build_terraform(["postgresql"])
        assert result is not None
        assert "5432" in result
        assert "alicloud_instance" not in result  # No ECS for infra-only

    def test_redis_opens_port(self):
        result = build_terraform(["redis"])
        assert "6379" in result

    def test_mongodb_opens_port(self):
        result = build_terraform(["mongodb"])
        assert "27017" in result

    def test_mysql_opens_port(self):
        result = build_terraform(["mysql"])
        assert "3306" in result


class TestBuildTerraformMixed:
    def test_runtime_plus_infra(self):
        result = build_terraform(["fastapi", "redis", "postgresql"])
        assert result is not None
        assert "alicloud_instance" in result  # runtime present
        assert "8000" in result  # fastapi port
        assert "6379" in result  # redis port
        assert "5432" in result  # postgresql port

    def test_no_duplicate_ports(self):
        """fastapi and django both use 8000 — should appear only once."""
        result = build_terraform(["fastapi", "django"])
        # Count occurrences of port 8000 in ingress rules
        count = result.count("to_port     = 8000")
        assert count == 1


class TestBuildTerraformEdgeCases:
    def test_empty_list_returns_none(self):
        assert build_terraform([]) is None

    def test_unknown_services_returns_none(self):
        assert build_terraform(["kafka", "rabbitmq"]) is None

    def test_non_list_returns_none(self):
        assert build_terraform("not a list") is None

    def test_contains_provider_block(self):
        result = build_terraform(["nodejs"])
        assert 'provider "alicloud"' in result

    def test_contains_vpc(self):
        result = build_terraform(["redis"])
        assert "alicloud_vpc" in result
        assert "alicloud_vswitch" in result

    def test_contains_output_for_ecs(self):
        result = build_terraform(["nodejs"])
        assert "ecs_public_ip" in result
