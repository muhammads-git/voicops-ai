# --- build_config: turns extracted services into deployable files ---

import logging

logger = logging.getLogger(__name__)

APP_RUNTIMES = {"nodejs", "fastapi", "flask", "django"}

RUNTIME_PORTS = {
    "nodejs": 3000,
    "fastapi": 8000,
    "flask": 5000,
    "django": 8000,
}

TEMPLATES = {
    "nodejs": {
        "dockerfile": (
            "FROM node:20-alpine\n"
            "WORKDIR /app\n"
            "COPY package*.json ./\n"
            "RUN npm install\n"
            "COPY . .\n"
            "EXPOSE 3000\n"
            'CMD ["npm", "start"]\n'
        ),
    },
    "fastapi": {
        "dockerfile": (
            "FROM python:3.12-slim\n"
            "WORKDIR /app\n"
            "COPY requirements.txt .\n"
            "RUN pip install --no-cache-dir -r requirements.txt\n"
            "COPY . .\n"
            "EXPOSE 8000\n"
            'CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]\n'
        ),
    },
    "flask": {
        "dockerfile": (
            "FROM python:3.12-slim\n"
            "WORKDIR /app\n"
            "COPY requirements.txt .\n"
            "RUN pip install --no-cache-dir -r requirements.txt\n"
            "COPY . .\n"
            "EXPOSE 5000\n"
            'CMD ["flask", "run", "--host=0.0.0.0"]\n'
        ),
    },
    "django": {
        "dockerfile": (
            "FROM python:3.12-slim\n"
            "WORKDIR /app\n"
            "COPY requirements.txt .\n"
            "RUN pip install --no-cache-dir -r requirements.txt\n"
            "COPY . .\n"
            "EXPOSE 8000\n"
            'CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]\n'
        ),
    },
    "postgresql": {
        "compose_service": (
            "  postgres:\n"
            "    image: postgres:16\n"
            "    environment:\n"
            "      POSTGRES_PASSWORD: changeme\n"
            "      POSTGRES_DB: appdb\n"
            "    ports:\n"
            '      - "5432:5432"\n'
        ),
    },
    "mysql": {
        "compose_service": (
            "  mysql:\n"
            "    image: mysql:8\n"
            "    environment:\n"
            "      MYSQL_ROOT_PASSWORD: changeme\n"
            "      MYSQL_DATABASE: appdb\n"
            "    ports:\n"
            '      - "3306:3306"\n'
        ),
    },
    "redis": {
        "compose_service": (
            "  redis:\n"
            "    image: redis:7\n"
            "    ports:\n"
            '      - "6379:6379"\n'
        ),
    },
    "mongodb": {
        "compose_service": (
            "  mongo:\n"
            "    image: mongo:7\n"
            "    ports:\n"
            '      - "27017:27017"\n'
        ),
    },
}


def build_config(services: list[str]) -> dict:
    """
    Takes the extracted services list, returns deployable files:
    {"dockerfile": str | None, "docker_compose": str | None}
    Never raises for bad/unknown input — logs and returns None fields instead.
    """
    if not isinstance(services, list):
        logger.error(f"build_config expected a list, got {type(services)}")
        return {"dockerfile": None, "docker_compose": None}

    dockerfile = None
    runtime = None
    compose_services = []
    matched_infra = []

    for service in services:
        if service not in TEMPLATES and service not in APP_RUNTIMES:
            logger.info(f"build_config: '{service}' has no template, skipping")
            continue

        if service in APP_RUNTIMES:
            dockerfile = TEMPLATES[service]["dockerfile"]
            runtime = service

        elif "compose_service" in TEMPLATES.get(service, {}):
            compose_services.append(TEMPLATES[service]["compose_service"])
            matched_infra.append(service)

    if not dockerfile and not compose_services:
        logger.warning(f"build_config: no matching templates for {services}")
        return {"dockerfile": None, "docker_compose": None}
#######################
    if dockerfile:
        port = RUNTIME_PORTS.get(runtime, 3000)
        depends_block = "".join(f"      - {s}\n" for s in matched_infra) or "      []\n"
        app_block = (
            "  app:\n"
            "    build: .\n"
            "    ports:\n"
            f'      - "{port}:{port}"\n'
            "    depends_on:\n"
            f"{depends_block}"
        )
        compose_services.insert(0, app_block)

    docker_compose = "version: '3.8'\nservices:\n" + "\n".join(compose_services) if compose_services else None

    return {
        "dockerfile": dockerfile,
        "docker_compose": docker_compose,
    }

""" Needed a FIX for speech recocgnition errors. sometimes misreads the wordings..."""