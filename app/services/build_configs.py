# --- build_config: turns extracted services into deployable files ---

import logging

logger = logging.getLogger(__name__)

APP_RUNTIMES = {"nodejs", "fastapi", "flask", "django"}

TEMPLATES = {
    "nodejs": {
        "dockerfile": """FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
EXPOSE 3000
CMD ["npm", "start"]
""",
    },
    "fastapi": {
        "dockerfile": """FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
""",
    },
    "flask": {
        "dockerfile": """FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 5000
CMD ["flask", "run", "--host=0.0.0.0"]
""",
    },
    "django": {
        "dockerfile": """FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
""",
    },
    "postgresql": {
        "compose_service": """  postgres:
    image: postgres:16
    environment:
      POSTGRES_PASSWORD: changeme
      POSTGRES_DB: appdb
    ports:
      - "5432:5432"
""",
    },
    "mysql": {
        "compose_service": """  mysql:
    image: mysql:8
    environment:
      MYSQL_ROOT_PASSWORD: changeme
      MYSQL_DATABASE: appdb
    ports:
      - "3306:3306"
""",
    },
    "redis": {
        "compose_service": """  redis:
    image: redis:7
    ports:
      - "6379:6379"
""",
    },
    "mongodb": {
        "compose_service": """  mongo:
    image: mongo:7
    ports:
      - "27017:27017"
""",
    },
}


def build_config(services: list[str]) -> dict:
    """
    Takes the extracted services list, returns deployable files:
    {"dockerfile": str | None, "docker_compose": str | None}
    Never raises for bad/unknown input — an empty or unmatched list
    is a valid (if useless) case, not a crash. Logs anything unexpected
    so you can see it during testing without the request failing.
    """
    if not isinstance(services, list):
        logger.error(f"build_config expected a list, got {type(services)}")
        return {"dockerfile": None, "docker_compose": None}

    dockerfile = None
    compose_services = []
    matched_infra = []

    for service in services:
        if service not in TEMPLATES and service not in APP_RUNTIMES:
            # e.g. "docker" itself, or anything that slipped through
            # extract_intent's validation — log it, don't crash
            logger.info(f"build_config: '{service}' has no template, skipping")
            continue

        if service in APP_RUNTIMES:
            dockerfile = TEMPLATES[service]["dockerfile"]
        elif "compose_service" in TEMPLATES.get(service, {}):
            compose_services.append(TEMPLATES[service]["compose_service"])
            matched_infra.append(service)

    if not dockerfile and not compose_services:
        # Nothing usable came through at all
        logger.warning(f"build_config: no matching templates for {services}")
        return {"dockerfile": None, "docker_compose": None}

    # If an app runtime was requested, add it as its own compose service,
    # depending on whatever infra services were also requested.
    if dockerfile:
        depends_block = "".join(f"      - {s}\n" for s in matched_infra) or "      []\n"
        app_block = f"""  app:
    build: .
    ports:
      - "3000:3000"
    depends_on:
{depends_block}"""
        compose_services.insert(0, app_block)

    docker_compose = "version: '3.8'\nservices:\n" + "\n".join(compose_services) if compose_services else None

    return {
        "dockerfile": dockerfile,
        "docker_compose": docker_compose,
    }