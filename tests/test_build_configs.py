# tests/test_build_configs.py — tests for Dockerfile and docker-compose generation

import pytest
from app.services.build_configs import build_config, TEMPLATES, APP_RUNTIMES, RUNTIME_PORTS


class TestBuildConfigRuntimes:
    def test_nodejs_generates_dockerfile(self):
        result = build_config(["nodejs"])
        assert result["dockerfile"] is not None
        assert "FROM node:20-alpine" in result["dockerfile"]
        assert "npm" in result["dockerfile"]

    def test_fastapi_generates_dockerfile(self):
        result = build_config(["fastapi"])
        assert result["dockerfile"] is not None
        assert "uvicorn" in result["dockerfile"]

    def test_flask_generates_dockerfile(self):
        result = build_config(["flask"])
        assert result["dockerfile"] is not None
        assert "flask" in result["dockerfile"].lower()

    def test_django_generates_dockerfile(self):
        result = build_config(["django"])
        assert result["dockerfile"] is not None
        assert "manage.py" in result["dockerfile"]

    def test_runtime_generates_compose_with_app_service(self):
        result = build_config(["nodejs"])
        assert result["docker_compose"] is not None
        assert "app:" in result["docker_compose"]
        assert "build: ." in result["docker_compose"]


class TestBuildConfigInfrastructure:
    def test_postgresql_generates_compose(self):
        result = build_config(["postgresql"])
        assert result["dockerfile"] is None
        assert result["docker_compose"] is not None
        assert "postgres:16" in result["docker_compose"]

    def test_mysql_generates_compose(self):
        result = build_config(["mysql"])
        assert result["docker_compose"] is not None
        assert "mysql:8" in result["docker_compose"]

    def test_redis_generates_compose(self):
        result = build_config(["redis"])
        assert result["docker_compose"] is not None
        assert "redis:7" in result["docker_compose"]

    def test_mongodb_generates_compose(self):
        result = build_config(["mongodb"])
        assert result["docker_compose"] is not None
        assert "mongo:7" in result["docker_compose"]


class TestBuildConfigMixed:
    def test_runtime_plus_infra(self):
        result = build_config(["fastapi", "redis", "postgresql"])
        assert result["dockerfile"] is not None
        assert result["docker_compose"] is not None
        assert "redis:7" in result["docker_compose"]
        assert "postgres:16" in result["docker_compose"]
        assert "app:" in result["docker_compose"]

    def test_compose_has_depends_on(self):
        result = build_config(["nodejs", "redis"])
        assert "depends_on:" in result["docker_compose"]

    def test_correct_port_in_compose(self):
        result = build_config(["flask"])
        assert "5000:5000" in result["docker_compose"]

    def test_fastapi_port(self):
        result = build_config(["fastapi"])
        assert "8000:8000" in result["docker_compose"]


class TestBuildConfigEdgeCases:
    def test_empty_list(self):
        result = build_config([])
        assert result["dockerfile"] is None
        assert result["docker_compose"] is None

    def test_unknown_services(self):
        result = build_config(["kafka", "rabbitmq"])
        assert result["dockerfile"] is None
        assert result["docker_compose"] is None

    def test_non_list_input(self):
        result = build_config("not a list")
        assert result["dockerfile"] is None
        assert result["docker_compose"] is None

    def test_none_input(self):
        result = build_config(None)
        assert result["dockerfile"] is None
        assert result["docker_compose"] is None

    def test_mixed_known_and_unknown(self):
        result = build_config(["redis", "kafka"])
        assert result["docker_compose"] is not None
        assert "redis:7" in result["docker_compose"]

    def test_all_runtimes_generate_dockerfiles(self):
        for runtime in APP_RUNTIMES:
            result = build_config([runtime])
            assert result["dockerfile"] is not None, f"{runtime} should generate a Dockerfile"

    def test_all_infra_services_in_templates(self):
        for svc in ["postgresql", "mysql", "redis", "mongodb"]:
            assert svc in TEMPLATES, f"{svc} should be in TEMPLATES"
            assert "compose_service" in TEMPLATES[svc]
