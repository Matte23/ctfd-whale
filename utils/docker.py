import json
import random
import uuid
from collections import OrderedDict

import docker
from flask import current_app

from CTFd.utils import get_config

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


class DockerUtils:
    @staticmethod
    def init():
        try:
            DockerUtils.client = get_docker_client()
        except Exception:
            raise WhaleError(
                "Docker Connection Error\n"
                "Please ensure the docker api url (first config item) is correct\n"
                "if you are using unix:///var/run/docker.sock, check if the socket is correctly mapped"
            )
        credentials = get_config("whale:docker_credentials")
        if credentials and credentials.count(":") == 1:
            try:
                DockerUtils.client.login(*credentials.split(":"))
            except Exception:
                raise WhaleError("docker.io failed to login, check your credentials")

    @staticmethod
    def add_container(container):
        use_swarm = get_config("whale:docker_use_swarm", False)

        if container.challenge.docker_image.startswith("{"):
            if use_swarm:
                DockerUtils._create_grouped_container_swarm(
                    DockerUtils.client, container
                )
            else:
                DockerUtils._create_grouped_container_classic(
                    DockerUtils.client, container
                )
        else:
            if use_swarm:
                DockerUtils._create_standalone_container_swarm(
                    DockerUtils.client, container
                )
            else:
                DockerUtils._create_standalone_container_classic(
                    DockerUtils.client, container
                )

    @staticmethod
    def _create_standalone_container_swarm(client, container):
        dns = get_config("whale:docker_dns", "").split(",")
        node = DockerUtils.choose_node(
            container.challenge.docker_image,
            get_config("whale:docker_swarm_nodes", "").split(","),
        )

        client.services.create(
            image=container.challenge.docker_image,
            name=f"{container.user_id}-{container.uuid}",
            env={"FLAG": container.flag},
            dns_config=docker.types.DNSConfig(nameservers=dns),
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
            labels={"whale_id": f"{container.user_id}-{container.uuid}"},
            constraints=["node.labels.name==" + node],
            endpoint_spec=docker.types.EndpointSpec(mode="dnsrr", ports={}),
        )

    @staticmethod
    def _create_grouped_container_swarm(client, container):
        range_prefix = CacheProvider(app=current_app).get_available_network_range()

        ipam_pool = docker.types.IPAMPool(subnet=range_prefix)
        ipam_config = docker.types.IPAMConfig(
            driver="default", pool_configs=[ipam_pool]
        )
        network_name = f"{container.user_id}-{container.uuid}"
        network = client.networks.create(
            network_name,
            internal=True,
            ipam=ipam_config,
            attachable=True,
            labels={"prefix": range_prefix},
            driver="overlay",
            scope="swarm",
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
        try:
            images = json.loads(
                container.challenge.docker_image, object_pairs_hook=OrderedDict
            )
        except json.JSONDecodeError:
            raise WhaleError(
                "Challenge Image Parse Error\nplease check the challenge image string"
            )

        for name, image in images.items():
            if has_processed_main:
                container_name = f"{container.user_id}-{uuid.uuid4()}"
            else:
                container_name = f"{container.user_id}-{container.uuid}"
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
                env={"FLAG": container.flag},
                dns_config=docker.types.DNSConfig(nameservers=dns),
                resources=docker.types.Resources(
                    mem_limit=DockerUtils.convert_readable_text(
                        container.challenge.memory_limit
                    ),
                    cpu_limit=int(container.challenge.cpu_limit * 1e9),
                ),
                labels={"whale_id": f"{container.user_id}-{container.uuid}"},
                hostname=name,
                constraints=["node.labels.name==" + node],
                endpoint_spec=docker.types.EndpointSpec(mode="dnsrr", ports={}),
            )

    @staticmethod
    def _create_standalone_container_classic(client, container):
        dns = [d for d in get_config("whale:docker_dns", "").split(",") if d]
        network_name = get_config("whale:docker_auto_connect_network", "bridge")

        client.containers.run(
            image=container.challenge.docker_image,
            name=f"{container.user_id}-{container.uuid}",
            environment={"FLAG": container.flag},
            detach=True,
            network=network_name,
            dns=dns if dns else None,
            mem_limit=DockerUtils.convert_readable_text(
                container.challenge.memory_limit
            ),
            init=container.challenge.init,
            privileged=container.challenge.privileged,
            nano_cpus=int(container.challenge.cpu_limit * 1e9),
            labels={"whale_id": f"{container.user_id}-{container.uuid}"},
        )

    @staticmethod
    def _create_grouped_container_classic(client, container):
        try:
            images = json.loads(
                container.challenge.docker_image, object_pairs_hook=OrderedDict
            )
        except json.JSONDecodeError:
            raise WhaleError(
                "Challenge Image Parse Error\nplease check the challenge image string"
            )

        range_prefix = CacheProvider(app=current_app).get_available_network_range()
        ipam_pool = docker.types.IPAMPool(subnet=range_prefix)
        ipam_config = docker.types.IPAMConfig(
            driver="default", pool_configs=[ipam_pool]
        )
        network_name = f"{container.user_id}-{container.uuid}"

        network = client.networks.create(
            network_name,
            internal=True,
            ipam=ipam_config,
            attachable=True,
            labels={"prefix": range_prefix},
            driver="bridge",
        )

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
                cname = f"{container.user_id}-{container.uuid}"
                has_processed_main = True

            client.containers.run(
                image=image,
                name=cname,
                environment={"FLAG": container.flag},
                detach=True,
                network=network_name,
                hostname=name,
                dns=dns if dns else None,
                mem_limit=DockerUtils.convert_readable_text(
                    container.challenge.memory_limit
                ),
                nano_cpus=int(container.challenge.cpu_limit * 1e9),
                labels={"whale_id": f"{container.user_id}-{container.uuid}"},
            )

    @staticmethod
    def remove_container(container):
        whale_id = f"{container.user_id}-{container.uuid}"
        use_swarm = get_config("whale:docker_use_swarm", False)

        if use_swarm:
            for s in DockerUtils.client.services.list(
                filters={"label": f"whale_id={whale_id}"}
            ):
                s.remove()
        else:
            for c in DockerUtils.client.containers.list(
                all=True, filters={"label": f"whale_id={whale_id}"}
            ):
                try:
                    c.remove(force=True)
                except Exception:
                    pass

        networks = DockerUtils.client.networks.list(names=[whale_id])
        if len(networks) > 0:
            auto_containers = get_config(
                "whale:docker_auto_connect_containers", ""
            ).split(",")
            redis_util = CacheProvider(app=current_app)
            for network in networks:
                for c in auto_containers:
                    try:
                        network.disconnect(c, force=True)
                    except Exception:
                        pass
                redis_util.add_available_network_range(
                    network.attrs["Labels"]["prefix"]
                )
                network.remove()

    @staticmethod
    def convert_readable_text(text):
        lower_text = text.lower()
        if lower_text.endswith("k"):
            return int(text[:-1]) * 1024
        if lower_text.endswith("m"):
            return int(text[:-1]) * 1024 * 1024
        if lower_text.endswith("g"):
            return int(text[:-1]) * 1024 * 1024 * 1024
        return 0

    @staticmethod
    def choose_node(image, nodes):
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
                "If you are using Whale for the first time,\n"
                "Please setup swarm nodes correctly and label them with:\n"
                'docker node update --label-add "name=linux-1" $(docker node ls -q)'
            )
