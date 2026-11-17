import json
import random
import time
import uuid
from collections import OrderedDict

import docker
from CTFd.utils import get_config
from docker.utils import parse_bytes
from flask import current_app

from ..models import WhaleContainer
from .cache import CacheProvider
from .exceptions import WhaleError


def get_docker_client():
    if get_config("whale:docker_use_ssl", False):
        tls_config = docker.tls.TLSConfig(
            verify=True,
            ca_cert=get_config("whale:docker_ssl_ca_cert") or None,
            client_cert=(
                get_config("whale:docker_ssl_client_cert"),
                get_config("whale:docker_ssl_client_key"),
            ),
        )
        return docker.DockerClient(
            base_url=get_config("whale:docker_api_url"),
            tls=tls_config,
        )
    else:
        return docker.DockerClient(base_url=get_config("whale:docker_api_url"))


def docker_login(client):
    """Log in with whale:docker_credentials, if set.

    Format: "username:password" (Docker Hub) or "username:password:registry".
    The registry may include a port, e.g. "user:pass:registry.example.com:5000".
    """
    credentials = get_config("whale:docker_credentials")
    if not credentials or ":" not in str(credentials):
        return
    username, rest = str(credentials).split(":", 1)
    password, _, registry = rest.partition(":")
    client.login(username=username, password=password, registry=registry or None)


class DockerUtils:
    client = None
    # whale:refresh is set to a new token on every settings save (assets/config.js);
    # each worker compares it with the token its client was built with.
    _refresh = None

    @staticmethod
    def init():
        refresh = get_config("whale:refresh")
        try:
            DockerUtils.client = get_docker_client()
        except Exception:
            raise WhaleError(
                "Docker Connection Error\n"
                + "Please ensure the docker api url (first config item) is correct\n"
                + "if you are using unix:///var/run/docker.sock, check if the socket is correctly mapped"
            )
        # only mark as up to date once the new client exists; a failed login
        # below keeps the (anonymous) client, as before
        DockerUtils._refresh = refresh
        try:
            docker_login(DockerUtils.client)
        except Exception:
            raise WhaleError("Docker registry login failed, check your credentials")

    @staticmethod
    def get_client():
        if (
            DockerUtils.client is None
            or DockerUtils._refresh != get_config("whale:refresh")
        ):
            DockerUtils.init()
        return DockerUtils.client

    @staticmethod
    def add_container(container: WhaleContainer):
        use_swarm = get_config("whale:docker_use_swarm", False)

        if container.challenge.docker_image.startswith("{"):
            if use_swarm:
                DockerUtils._create_grouped_container_swarm(
                    DockerUtils.get_client(), container
                )
            else:
                DockerUtils._create_grouped_container_classic(
                    DockerUtils.get_client(), container
                )
        else:
            if use_swarm:
                DockerUtils._create_standalone_container_swarm(
                    DockerUtils.get_client(), container
                )
            else:
                DockerUtils._create_standalone_container_classic(
                    DockerUtils.get_client(), container
                )

    @staticmethod
    def _create_standalone_container_swarm(client, container: WhaleContainer):
        dns = [d for d in get_config("whale:docker_dns", "").split(",") if d]
        node = DockerUtils.choose_node(
            container.challenge.docker_image,
            get_config("whale:docker_swarm_nodes", "").split(","),
        )

        client.services.create(
            image=container.challenge.docker_image,
            name=container.name,
            env={"FLAG": container.flag.content},
            dns_config=docker.types.DNSConfig(nameservers=dns) if dns else None,
            networks=[
                get_config("whale:docker_auto_connect_network", "ctfd_frp-containers")
            ],
            resources=docker.types.Resources(
                mem_limit=DockerUtils.convert_readable_text(
                    container.challenge.memory_limit
                ),
                cpu_limit=int(container.challenge.cpu_limit * 1e9),
            ),
            init=container.challenge.init,
            labels={"whale_id": container.name},
            constraints=["node.labels.name==" + node],
            endpoint_spec=docker.types.EndpointSpec(mode="dnsrr", ports={}),
        )

    @staticmethod
    def _create_grouped_container_swarm(client, container: WhaleContainer):
        try:
            images = json.loads(
                container.challenge.docker_image, object_pairs_hook=OrderedDict
            )
        except json.JSONDecodeError:
            raise WhaleError(
                "Challenge Image Parse Error\nplease check the challenge image string"
            )

        network_name = container.name
        network = DockerUtils._create_network(
            client, network_name, driver="overlay", scope="swarm"
        )

        dns = []
        containers = get_config("whale:docker_auto_connect_containers", "").split(",")
        for c in containers:
            if not c:
                continue
            network.connect(c)
            if "dns" in c:
                network.reload()
                for name in network.attrs["Containers"]:
                    if network.attrs["Containers"][name]["Name"] == c:
                        dns.append(
                            network.attrs["Containers"][name]["IPv4Address"].split("/")[
                                0
                            ]
                        )

        has_processed_main = False
        for name, image in images.items():
            if has_processed_main:
                container_name = f"{container.user_id}-{uuid.uuid4()}"
            else:
                container_name = container.name
                node = DockerUtils.choose_node(
                    image, get_config("whale:docker_swarm_nodes", "").split(",")
                )
                has_processed_main = True

            client.services.create(
                image=image,
                name=container_name,
                networks=[
                    docker.types.NetworkAttachmentConfig(network_name, aliases=[name])
                ],
                env={"FLAG": container.flag.content},
                dns_config=docker.types.DNSConfig(nameservers=dns) if dns else None,
                resources=docker.types.Resources(
                    mem_limit=DockerUtils.convert_readable_text(
                        container.challenge.memory_limit
                    ),
                    cpu_limit=int(container.challenge.cpu_limit * 1e9),
                ),
                init=container.challenge.init,
                labels={"whale_id": container.name},
                hostname=name,
                constraints=["node.labels.name==" + node],
                endpoint_spec=docker.types.EndpointSpec(mode="dnsrr", ports={}),
            )

    @staticmethod
    def _create_standalone_container_classic(client, container: WhaleContainer):
        dns = [d for d in get_config("whale:docker_dns", "").split(",") if d]
        network_name = get_config("whale:docker_auto_connect_network", "bridge")

        client.containers.run(
            image=container.challenge.docker_image,
            name=container.name,
            environment={"FLAG": container.flag.content},
            detach=True,
            network=network_name,
            dns=dns if dns else None,
            mem_limit=DockerUtils.convert_readable_text(
                container.challenge.memory_limit
            ),
            init=container.challenge.init,
            privileged=container.challenge.privileged,
            nano_cpus=int(container.challenge.cpu_limit * 1e9),
            labels={"whale_id": container.name},
        )

    @staticmethod
    def _create_grouped_container_classic(client, container: WhaleContainer):
        try:
            images = json.loads(
                container.challenge.docker_image, object_pairs_hook=OrderedDict
            )
        except json.JSONDecodeError:
            raise WhaleError(
                "Challenge Image Parse Error\nplease check the challenge image string"
            )

        network_name = container.name
        network = DockerUtils._create_network(client, network_name, driver="bridge")

        dns = []
        auto_containers = get_config("whale:docker_auto_connect_containers", "").split(
            ","
        )
        for c in auto_containers:
            if not c:
                continue
            try:
                network.connect(c)
                c_data = client.containers.get(c)
                for net_name, details in c_data.attrs["NetworkSettings"][
                    "Networks"
                ].items():
                    if net_name == network_name:
                        dns.append(details["IPAddress"])
            except Exception:
                pass

        has_processed_main = False
        for name, image in images.items():
            if has_processed_main:
                cname = f"{container.user_id}-{uuid.uuid4()}"
            else:
                cname = container.name
                has_processed_main = True

            client.containers.run(
                image=image,
                name=cname,
                environment={"FLAG": container.flag.content},
                detach=True,
                network=network_name,
                hostname=name,
                dns=dns if dns else None,
                mem_limit=DockerUtils.convert_readable_text(
                    container.challenge.memory_limit
                ),
                nano_cpus=int(container.challenge.cpu_limit * 1e9),
                init=container.challenge.init,
                privileged=container.challenge.privileged,
                labels={"whale_id": container.name},
            )

    @staticmethod
    def remove_container(container: WhaleContainer):
        whale_id = container.name
        use_swarm = get_config("whale:docker_use_swarm", False)

        if use_swarm:
            for s in DockerUtils.get_client().services.list(
                filters={"label": f"whale_id={whale_id}"}
            ):
                s.remove()
        else:
            for c in DockerUtils.get_client().containers.list(
                all=True, filters={"label": f"whale_id={whale_id}"}
            ):
                try:
                    c.remove(force=True)
                except Exception:
                    pass

        networks = DockerUtils.get_client().networks.list(names=[whale_id])
        if len(networks) > 0:
            auto_containers = get_config(
                "whale:docker_auto_connect_containers", ""
            ).split(",")
            redis_util = CacheProvider(app=current_app)
            for network in networks:
                for c in auto_containers:
                    if not c:
                        continue
                    try:
                        network.disconnect(c, force=True)
                    except Exception:
                        pass
                prefix = (network.attrs.get("Labels") or {}).get("prefix")
                DockerUtils._remove_network(network, attempts=10 if use_swarm else 1)
                # only now is the subnet actually free again
                if prefix:
                    redis_util.add_available_network_range(prefix)

    @staticmethod
    def _create_network(client, network_name: str, **kwargs):
        range_prefix = CacheProvider(app=current_app).get_available_network_range()
        if not range_prefix:
            raise WhaleError("No available subnets for challenge networks")
        ipam_pool = docker.types.IPAMPool(subnet=range_prefix)
        ipam_config = docker.types.IPAMConfig(
            driver="default", pool_configs=[ipam_pool]
        )
        try:
            return client.networks.create(
                network_name,
                internal=True,
                ipam=ipam_config,
                attachable=True,
                labels={"prefix": range_prefix},
                **kwargs,
            )
        except Exception:
            # no network carries this subnet's label, so nothing else would return it
            CacheProvider(app=current_app).add_available_network_range(range_prefix)
            raise

    @staticmethod
    def _remove_network(network, attempts: int):
        # Swarm removes services asynchronously: the network stays "in use"
        # until their tasks have stopped, so give it a few seconds.
        for attempt in range(attempts):
            try:
                network.remove()
                return
            except docker.errors.NotFound:
                return
            except docker.errors.APIError:
                if attempt == attempts - 1:
                    raise
                time.sleep(1)

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
    def choose_node(image: str, nodes: list[str]):
        win_nodes, linux_nodes = [], []
        for node in nodes:
            (win_nodes if node.startswith("windows") else linux_nodes).append(node)
        try:
            tag = image.split(":")[1:]
            if len(tag) and tag[0].startswith("windows"):
                return random.choice(win_nodes)
            return random.choice(linux_nodes)
        except IndexError:
            raise WhaleError(
                "No Suitable Nodes.\n"
                + "If you are using Whale for the first time,\n"
                + "Please setup swarm nodes correctly and label them with:\n"
                + 'docker node update --label-add "name=linux-1" $(docker node ls -q)'
            )
