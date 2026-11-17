from .config import fill_missing_configs
from .db import DBRedirectTemplate


def setup_default_configs():
    """Fill in missing settings and redirect templates. Safe to run on every startup."""
    fill_missing_configs()
    DBRedirectTemplate.create_template(
        "http",
        "http://{{ container.http_subdomain }}."
        + '{{ get_config("whale:frp_http_domain_suffix", "") }}'
        + '{% if get_config("whale:frp_http_port") != 80 %}:{{ get_config("whale:frp_http_port") }}{% endif %}/',
        """
[http_{{ container.user_id|string }}-{{ container.uuid }}]
type = http
local_ip = {{ container.name }}
local_port = {{ container.challenge.redirect_port }}
subdomain = {{ container.http_subdomain }}
use_compression = true
""",
    )
    DBRedirectTemplate.create_template(
        "direct",
        'nc {{ get_config("whale:frp_direct_ip_address", "127.0.0.1") }} {{ container.port }}',
        """
[direct_{{ container.user_id|string }}-{{ container.uuid }}]
type = tcp
local_ip = {{ container.name }}
local_port = {{ container.challenge.redirect_port }}
remote_port = {{ container.port }}
use_compression = true

[direct_{{ container.user_id|string }}-{{ container.uuid }}_udp]
type = udp
local_ip = {{ container.name }}
local_port = {{ container.challenge.redirect_port }}
remote_port = {{ container.port }}
use_compression = true
""",
    )
