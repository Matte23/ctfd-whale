import ipaddress
import json
import random
import time
import uuid
from collections import OrderedDict

import docker
from docker.utils import parse_bytes
from flask import current_app

from ..models import WhaleContainer
from .config import whale_config
from .db import DBContainer
from .exceptions import WhaleError
from .state import whale_state

# Label identifying the docker resources (containers, services, networks) of a
# WhaleContainer; value: WhaleContainer.name. Resources created by older
# versions carry LEGACY_LABEL instead: still looked for on removal.
LABEL = "ctfd-whale.id"
LEGACY_LABEL = "whale_id"

# How long a Swarm launch waits for its tasks to run before reporting
# "still starting" (a first pull of a big image can take longer).
SWARM_START_TIMEOUT_SECONDS = 60
_FAILED_TASK_STATES = ("failed", "rejected")


def _split(value) -> list:
    """Comma-separated setting -> list of non-empty, stripped items."""
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


# Settings the docker client is built from: when one changes, it is rebuilt.
CLIENT_SETTINGS = (
    "docker_api_url",
    "docker_use_ssl",
    "docker_ssl_ca_cert",
    "docker_ssl_client_cert",
    "docker_ssl_client_key",
    "docker_credentials",
)


def build_docker_client():
    """A new, not logged in, docker client from the current settings."""
    if whale_config("docker_use_ssl"):
        tls_config = docker.tls.TLSConfig(
            verify=True,
            ca_cert=whale_config("docker_ssl_ca_cert") or None,
            client_cert=(
                whale_config("docker_ssl_client_cert"),
                whale_config("docker_ssl_client_key"),
            ),
        )
        return docker.DockerClient(
            base_url=whale_config("docker_api_url"),
            tls=tls_config,
        )
    return docker.DockerClient(base_url=whale_config("docker_api_url"))


def docker_login(client):
    """Log in with whale:docker_credentials, if set.

    Format: "username:password" (Docker Hub) or "username:password:registry".
    The registry may include a port, e.g. "user:pass:registry.example.com:5000".
    """
    credentials = whale_config("docker_credentials")
    if not credentials or ":" not in str(credentials):
        return
    username, rest = str(credentials).split(":", 1)
    password, _, registry = rest.partition(":")
    client.login(username=username, password=password, registry=registry or None)


def docker_client():
    """The shared, logged in docker client of this process.

    Rebuilt when one of CLIENT_SETTINGS changes, however it was changed.
    Only cached once the login succeeded, so a failed login is retried.
    """
    state = whale_state()
    key = tuple(whale_config(setting) for setting in CLIENT_SETTINGS)
    cached = state.get("docker")
    if cached is not None and cached[0] == key:
        return cached[1]
    try:
        client = build_docker_client()
    except Exception:
        raise WhaleError(
            "Docker Connection Error\n"
            + "Please ensure the docker api url (first config item) is correct\n"
            + "if you are using unix:///var/run/docker.sock, check if the socket is correctly mapped"
        )
    try:
        docker_login(client)
    except Exception:
        raise WhaleError("Docker registry login failed, check your credentials")
    state["docker"] = (key, client)
    return client


class DockerUtils:
    @staticmethod
    def add_container(container: WhaleContainer) -> bool:
        """Create the docker resources of the container.

        Returns False when they are created but still starting (Swarm only);
        raises WhaleError if they fail to start.
        """
        client = docker_client()
        swarm = whale_config("docker_use_swarm")
        images = DockerUtils._images(container)
        if container.challenge.docker_image.startswith("{"):
            # grouped: a private network, plus the helper containers
            network = DockerUtils._create_network(
                client,
                container,
                **(
                    {"driver": "overlay", "scope": "swarm"}
                    if swarm
                    else {"driver": "bridge"}
                ),
            )
            network_name = network.name
            dns = DockerUtils._connect_helpers(client, network, swarm)
        else:
            network_name = whale_config("docker_auto_connect_network")
            dns = _split(whale_config("docker_dns"))

        if not swarm:
            for hostname, image, name in images:
                DockerUtils._run_container(
                    client, container, image, name, network_name, hostname, dns
                )
            return True

        # all services of one instance on the same node, chosen for the main image
        main_image = images[0][1]
        constraints = DockerUtils.node_constraints(
            main_image,
            DockerUtils.choose_node(
                main_image, _split(whale_config("docker_swarm_nodes"))
            ),
        )
        for hostname, image, name in images:
            DockerUtils._create_service(
                client, container, image, name, network_name, hostname, dns, constraints
            )
        # services.create() returns at once: wait for the tasks to run,
        # so e.g. a missing image is reported instead of a dead instance
        return DockerUtils._wait_for_services(client, container)

    @staticmethod
    def _images(container: WhaleContainer):
        """(hostname, image, docker name) of each container to start.

        A single image: one entry without hostname. Grouped ('{"web":
        "img:1", ...}'): one per entry; the first one is the main container
        and carries the WhaleContainer's name.
        """
        image = container.challenge.docker_image
        if not image.startswith("{"):
            return [(None, image.strip(), container.name)]
        try:
            images = json.loads(image, object_pairs_hook=OrderedDict)
        except json.JSONDecodeError:
            raise WhaleError(
                "Challenge Image Parse Error\nplease check the challenge image string"
            )
        return [
            (
                hostname,
                value.strip(),
                container.name if i == 0 else f"{container.user_id}-{uuid.uuid4()}",
            )
            for i, (hostname, value) in enumerate(images.items())
        ]

    @staticmethod
    def _connect_helpers(client, network, swarm: bool):
        """Connect the auto-connect containers to the network.

        Returns the IPs of those serving DNS (see _is_dns_helper).
        """
        dns = []
        for name in _split(whale_config("docker_auto_connect_containers")):
            try:
                network.connect(name)
                if not DockerUtils._is_dns_helper(name, swarm):
                    continue
                attrs = client.containers.get(name).attrs
                details = attrs["NetworkSettings"]["Networks"].get(network.name)
                if details and details.get("IPAddress"):
                    dns.append(details["IPAddress"])
            except Exception:
                current_app.logger.warning(
                    "[CTFd Whale] could not connect %s to network %s",
                    name,
                    network.name,
                    exc_info=True,
                )
        return dns

    @staticmethod
    def _is_dns_helper(name: str, swarm: bool) -> bool:
        explicit = _split(whale_config("docker_dns_containers"))
        if explicit:
            return name in explicit
        # setting empty: the behavior of older versions
        return "dns" in name if swarm else True

    @staticmethod
    def _create_service(
        client, container, image, name, network_name, hostname, dns, constraints
    ):
        challenge = container.challenge
        # grouped containers: reachable by their short name on the network
        extra = {}
        if hostname:
            extra["hostname"] = hostname
            network = docker.types.NetworkAttachmentConfig(
                network_name, aliases=[hostname]
            )
        else:
            network = network_name
        client.services.create(
            image=image,
            name=name,
            env={"FLAG": container.flag.content},
            networks=[network],
            **extra,
            dns_config=docker.types.DNSConfig(nameservers=dns) if dns else None,
            resources=docker.types.Resources(
                mem_limit=DockerUtils.convert_readable_text(challenge.memory_limit),
                cpu_limit=int(challenge.cpu_limit * 1e9),
            ),
            init=challenge.init,
            labels={LABEL: container.name},
            constraints=constraints,
            endpoint_spec=docker.types.EndpointSpec(mode="dnsrr", ports={}),
        )

    @staticmethod
    def _run_container(client, container, image, name, network_name, hostname, dns):
        challenge = container.challenge
        extra = {"hostname": hostname} if hostname else {}
        client.containers.run(
            image=image,
            name=name,
            environment={"FLAG": container.flag.content},
            detach=True,
            network=network_name,
            **extra,
            dns=dns or None,
            mem_limit=DockerUtils.convert_readable_text(challenge.memory_limit),
            nano_cpus=int(challenge.cpu_limit * 1e9),
            init=challenge.init,
            privileged=challenge.privileged,
            labels={LABEL: container.name},
        )

    @staticmethod
    def _wait_for_services(client, container: WhaleContainer) -> bool:
        """Wait until every service of the container has a running task.

        Returns True when all run, False if some are still starting after
        SWARM_START_TIMEOUT_SECONDS; raises WhaleError with Docker's error
        when a task fails.
        """
        deadline = time.monotonic() + SWARM_START_TIMEOUT_SECONDS
        while True:
            pending = False
            for service in client.services.list(
                filters={"label": f"{LABEL}={container.name}"}
            ):
                tasks = service.tasks()
                states = [t["Status"]["State"] for t in tasks]
                if "running" in states:
                    continue
                failed = [
                    t for t in tasks if t["Status"]["State"] in _FAILED_TASK_STATES
                ]
                if failed:
                    status = failed[-1]["Status"]
                    error = status.get("Err") or status.get("Message") or "task failed"
                    raise WhaleError(f"Service {service.name} failed to start: {error}")
                pending = True
            if not pending:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(1)

    @staticmethod
    def remove_container(container: WhaleContainer):
        whale_id = container.name
        client = docker_client()
        # current and legacy label: docker can't OR label filters
        label_filters = [f"{LABEL}={whale_id}", f"{LEGACY_LABEL}={whale_id}"]

        if whale_config("docker_use_swarm"):
            for label in label_filters:
                for s in client.services.list(filters={"label": label}):
                    s.remove()
        else:
            for label in label_filters:
                for c in client.containers.list(all=True, filters={"label": label}):
                    try:
                        c.remove(force=True)
                    except docker.errors.NotFound:
                        pass
                    except Exception:
                        # the network removal below then fails ("in use") and
                        # the whole removal is retried by auto-clean
                        current_app.logger.warning(
                            "[CTFd Whale] could not remove container %s",
                            c.name,
                            exc_info=True,
                        )

        networks = client.networks.list(names=[whale_id])
        if len(networks) > 0:
            auto_containers = whale_config("docker_auto_connect_containers").split(",")
            for network in networks:
                for c in auto_containers:
                    if not c:
                        continue
                    try:
                        network.disconnect(c, force=True)
                    except docker.errors.NotFound:
                        pass
                    except Exception:
                        current_app.logger.warning(
                            "[CTFd Whale] could not disconnect %s from network %s",
                            c,
                            whale_id,
                            exc_info=True,
                        )
                # the subnet is freed with the container row, deleted only
                # once this succeeded
                DockerUtils._remove_network(network)

    @staticmethod
    def _used_subnets(client):
        """Subnets of every existing docker network, ours or not."""
        used = []
        for network in client.networks.list():
            for config in (network.attrs.get("IPAM") or {}).get("Config") or []:
                if config.get("Subnet"):
                    try:
                        used.append(
                            ipaddress.ip_network(config["Subnet"], strict=False)
                        )
                    except ValueError:
                        pass
        return used

    @staticmethod
    def _create_network(client, container: WhaleContainer, **kwargs):
        # Overlapping networks are skipped, not only exact matches: this also
        # covers networks created before subnets were stored in the database.
        used = DockerUtils._used_subnets(client)
        candidates = [
            str(subnet)
            for subnet in ipaddress.ip_network(whale_config("docker_subnet")).subnets(
                new_prefix=int(whale_config("docker_subnet_new_prefix"))
            )
            if not any(subnet.version == u.version and subnet.overlaps(u) for u in used)
        ]
        subnet = DBContainer.allocate_subnet(container, candidates)
        if subnet is None:
            raise WhaleError("No available subnets for challenge networks")
        ipam_pool = docker.types.IPAMPool(subnet=subnet)
        ipam_config = docker.types.IPAMConfig(
            driver="default", pool_configs=[ipam_pool]
        )
        # on failure the subnet stays on the row until the container is
        # discarded, which frees it
        return client.networks.create(
            container.name,
            internal=True,
            ipam=ipam_config,
            attachable=True,
            labels={LABEL: container.name},
            **kwargs,
        )

    @staticmethod
    def _remove_network(network):
        # Swarm removes services asynchronously: right after removing them the
        # network can still be "in use". Then this raises, the container is
        # marked as removing and auto-clean retries shortly, instead of the
        # request waiting for it.
        try:
            network.remove()
        except docker.errors.NotFound:
            pass

    @staticmethod
    def convert_readable_text(text: str):
        # Docker treats 0 as "no limit": never let a bad value turn into that.
        text = (text or "").strip()
        if not text:
            raise WhaleError("Challenge memory limit is empty")
        limit = parse_bytes(text)  # raises DockerException on invalid values
        if limit <= 0:
            raise WhaleError(f"Invalid challenge memory limit: {text}")
        return limit

    @staticmethod
    def _image_tag(image: str) -> str:
        """The tag of an image reference ("" if none).

        Only the last path segment can carry the tag: in
        "registry:5000/team/img:windows" the ":5000" is the registry port.
        """
        name = image.split("@", 1)[0].rsplit("/", 1)[-1]
        return name.split(":", 1)[1] if ":" in name else ""

    @staticmethod
    def choose_node(image: str, nodes: list[str]):
        """Pick a swarm node label for the image: windows-* for windows tags."""
        nodes = [n.strip() for n in nodes if n.strip()]
        windows = DockerUtils._image_tag(image).startswith("windows")
        candidates = [n for n in nodes if n.startswith("windows") == windows]
        if not candidates:
            kind = "windows" if windows else "linux"
            raise WhaleError(
                f"No suitable {kind} swarm node in the Swarm Nodes setting "
                f"({', '.join(nodes) or 'empty'}).\n"
                + "Set it, e.g. to linux-1, and label your nodes with:\n"
                + 'docker node update --label-add "name=linux-1" $(docker node ls -q)'
            )
        return random.choice(candidates)

    @staticmethod
    def node_constraints(image: str, node: str) -> list:
        """Swarm constraints: the chosen labelled node, and the matching OS.

        The OS constraint guards against a node labelled for the wrong OS.
        """
        os_name = (
            "windows"
            if DockerUtils._image_tag(image).startswith("windows")
            else "linux"
        )
        return [f"node.labels.name=={node}", f"node.platform.os=={os_name}"]
