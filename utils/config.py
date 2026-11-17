"""Plugin settings: the single place that knows every key and its default."""

from CTFd.models import Configs
from CTFd.utils import get_config, set_config

PREFIX = "whale:"

# Every setting of the plugin, with the value used when none is stored.
# Values are typed like CTFd's get_config() returns them: digit strings
# become int and "true"/"false" become bool.
DEFAULTS = {
    # docker
    "docker_api_url": "unix:///var/run/docker.sock",
    "docker_credentials": "",
    "docker_use_swarm": False,
    "docker_swarm_nodes": "linux-1",
    "docker_use_ssl": False,
    "docker_ssl_ca_cert": "",
    "docker_ssl_client_cert": "",
    "docker_ssl_client_key": "",
    "docker_auto_connect_network": "ctfd_containers",
    "docker_auto_connect_containers": "",
    # auto-connect containers serving DNS to grouped challenges; empty: with
    # Swarm those whose name contains "dns", without Swarm all of them
    "docker_dns_containers": "",
    # empty: use docker's default DNS
    "docker_dns": "",
    "docker_subnet": "174.1.0.0/16",
    "docker_subnet_new_prefix": 24,
    # limits
    "docker_max_container_count": 100,
    "docker_max_renew_count": 5,
    "docker_timeout": 3600,
    # router
    "router_type": "frp",
    "frp_api_url": "http://frpc:7400",
    "frp_config_template": "",
    "frp_http_port": 8080,
    "frp_http_domain_suffix": "127.0.0.1.nip.io",
    "frp_direct_ip_address": "127.0.0.1",
    "frp_direct_port_minimum": 10000,
    "frp_direct_port_maximum": 10100,
    "trp_api_url": "",
    "trp_domain_suffix": "127.0.0.1.nip.io",
    "trp_listening_port": 1443,
    # challenges
    "template_http_subdomain": "{{ container.uuid }}",
    "template_chall_flag": '{{ "flag{"+uuid.uuid4()|string+"}" }}',
}


def whale_config(key):
    """Return the plugin setting ``key``, or its default.

    Note: CTFd treats an empty stored value as missing, so an emptied
    setting falls back to its default.
    """
    return get_config(PREFIX + key, DEFAULTS[key])


def _serialize(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def fill_missing_configs():
    """Store the default of every setting that has no row yet.

    Runs on every startup, so settings added by newer versions get a value
    too. Checks the table directly: a value an admin emptied on purpose has
    a row and is left alone.
    """
    keys = [PREFIX + key for key in DEFAULTS]
    existing = {
        key
        for (key,) in Configs.query.with_entities(Configs.key).filter(
            Configs.key.in_(keys)
        )
    }
    for key, value in DEFAULTS.items():
        if PREFIX + key not in existing:
            set_config(PREFIX + key, _serialize(value))
