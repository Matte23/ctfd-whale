"""Checks run when an admin saves a docker challenge.

Without them a broken challenge is saved silently and only fails when a
player launches it ("Docker Creation Error").
"""

import json
import re

from docker.errors import DockerException
from jinja2.exceptions import TemplateError

from .config import whale_config
from .docker import DockerUtils
from .exceptions import WhaleError
from .templates import render_flag

REDIRECT_TYPES = ("http", "direct")

# Characters a docker image reference can contain: name[:tag][@digest],
# optionally with a registry host[:port]/ prefix.
_IMAGE_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@-]*$")

# Fields of DockerChallenges checked here, with the value used on creation
# when the form doesn't send one (same as the model defaults).
CHALLENGE_FIELDS = {
    "docker_image": None,
    "memory_limit": "128m",
    "cpu_limit": 0.5,
    "redirect_type": None,
    "redirect_port": None,
    "flag_template": "",
    "privileged": False,
}


def _is_true(value):
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "on", "yes")
    return bool(value)


def _check_image_reference(image, label="Docker image"):
    if not _IMAGE_REFERENCE.match(image):
        raise ValueError(f"{label} {image!r} is not a valid image reference")


def _check_image(image):
    image = (image or "").strip() if isinstance(image, str) else ""
    if not image:
        raise ValueError("Docker image is required")
    if not image.startswith("{"):
        _check_image_reference(image)
        return
    # grouped containers: {"<hostname>": "<image>", ...}
    try:
        images = json.loads(image)
    except json.JSONDecodeError as e:
        raise ValueError(f"Docker image looks like JSON but doesn't parse: {e}")
    if not isinstance(images, dict) or not images:
        raise ValueError(
            'Grouped docker image must be a JSON object like {"web": "image:tag"}'
        )
    for name, value in images.items():
        if not name or not isinstance(value, str) or not value.strip():
            raise ValueError(f"Grouped docker image: invalid entry {name!r}")
        _check_image_reference(value.strip(), f"Grouped docker image {name!r}:")


def _check_memory(memory_limit):
    try:
        DockerUtils.convert_readable_text(str(memory_limit or ""))
    except (WhaleError, DockerException) as e:
        raise ValueError(f"Invalid memory limit {memory_limit!r}: {e}")


def _check_cpu(cpu_limit):
    try:
        cpu = float(cpu_limit)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid CPU limit {cpu_limit!r}: must be a number")
    if cpu <= 0:
        raise ValueError("CPU limit must be greater than 0")


def _check_redirect(redirect_type, redirect_port):
    if redirect_type not in REDIRECT_TYPES:
        raise ValueError(
            f"Invalid redirect type {redirect_type!r}: use one of {', '.join(REDIRECT_TYPES)}"
        )
    try:
        port = int(redirect_port)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid redirect port {redirect_port!r}: must be a number")
    if not 1 <= port <= 65535:
        raise ValueError("Redirect port must be between 1 and 65535")


def _check_flag_template(flag_template):
    if not flag_template:
        return  # the global flag template is used
    try:
        flag = render_flag(flag_template)
    except TemplateError as e:
        raise ValueError(f"Flag template error: {e}")
    if not flag.strip():
        raise ValueError("Flag template renders to an empty flag")


def validate_challenge(values):
    """Raise ValueError with a message for the admin if ``values`` is invalid.

    ``values``: the challenge fields as they will be saved (stored values
    merged with the submitted ones).
    """
    _check_image(values.get("docker_image"))
    _check_memory(values.get("memory_limit"))
    _check_cpu(values.get("cpu_limit"))
    _check_redirect(values.get("redirect_type"), values.get("redirect_port"))
    _check_flag_template(values.get("flag_template"))
    if _is_true(values.get("privileged")) and whale_config("docker_use_swarm"):
        raise ValueError(
            "Privileged mode isn't supported with Swarm: docker services can't run privileged"
        )
