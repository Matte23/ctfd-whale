"""Settings page checks. They must only read: the page runs them on every load."""

import requests
from docker.errors import APIError, DockerException, TLSParameterError

from .config import whale_config
from .docker import build_docker_client, docker_login
from .routers import ROUTERS, get_router


def check_docker_api():
    # a fresh client, to test the settings as they are now
    try:
        client = build_docker_client()
    except TLSParameterError as e:
        return f"Docker TLS Parameters incorrect ({e})"
    except DockerException as e:
        return f"Docker API url incorrect ({e})"
    try:
        client.ping()
    except (APIError, requests.RequestException):
        return "Unable to connect to Docker API, check your API connectivity"

    try:
        docker_login(client)
    except DockerException:
        return "Unable to log into docker registry, check your credentials"
    if whale_config("docker_use_swarm"):
        swarm = client.info()["Swarm"]
        if not swarm["ControlAvailable"]:
            return "Docker swarm not available. You should initialize a swarm first. ($ docker swarm init)"


def check_router_connection():
    router_type = whale_config("router_type")
    if router_type not in ROUTERS:
        return "invalid router type: " + router_type
    ok, msg = get_router().check_availability()
    if not ok:
        return msg


def run_checks():
    checks = (check_docker_api, check_router_connection)
    return [error for error in (check() for check in checks) if error]
