"""Rendering of admin-written templates (flags, subdomains, redirects).

They run in Jinja's sandbox and only get plain data and a few safe helpers:
never ORM objects, modules or CTFd's get_config. The sandbox blocks private
attributes (``__class__``, ``__globals__``...), but public methods stay
callable, so e.g. a model's ``query.delete()`` or ``uuid.os.system`` would
still be reachable if those objects were passed in.
"""

import secrets
import string
import uuid
from types import SimpleNamespace

from jinja2.sandbox import ImmutableSandboxedEnvironment

from .config import PREFIX, whale_config

_env = ImmutableSandboxedEnvironment()

# Settings templates may read through get_config(): nothing secret.
PUBLIC_SETTINGS = (
    "frp_http_domain_suffix",
    "frp_http_port",
    "frp_direct_ip_address",
    "trp_domain_suffix",
    "trp_listening_port",
)

_csprng = secrets.SystemRandom()

# Same names as before ("uuid.uuid4()", "random.randint(...)"), so existing
# templates keep working; flags must not be predictable, hence the CSPRNG.
_uuid = SimpleNamespace(uuid4=uuid.uuid4)
_random = SimpleNamespace(
    random=_csprng.random,
    randint=_csprng.randint,
    randrange=_csprng.randrange,
    choice=_csprng.choice,
    choices=_csprng.choices,
    sample=_csprng.sample,
    shuffle=_csprng.shuffle,
    uniform=_csprng.uniform,
    getrandbits=_csprng.getrandbits,
)


def random_string(length: int = 16):
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _get_config(key, default=None):
    """get_config() for templates: only PUBLIC_SETTINGS, else ``default``."""
    if isinstance(key, str) and key.startswith(PREFIX):
        name = key[len(PREFIX) :]
        if name in PUBLIC_SETTINGS:
            return whale_config(name)
    return default


def render(template: str, **context) -> str:
    """Render an admin-written template in the sandbox.

    Raises jinja2.exceptions.SecurityError (or another TemplateError) when the
    template tries something it may not do.
    """
    return _env.from_string(template).render(get_config=_get_config, **context)


def container_context(container, with_subdomain=True):
    """Plain, read-only data about a WhaleContainer for templates.

    No user object: user names are chosen by players and could inject into
    subdomains or the frp config. ``with_subdomain`` is False while rendering
    the subdomain itself.
    """
    challenge = container.challenge
    data = {
        "id": container.id,
        "uuid": container.uuid,
        "name": container.name,
        "user_id": container.user_id,
        "challenge_id": container.challenge_id,
        "port": container.port,
        "subnet": container.subnet,
        "challenge": (
            {
                "id": challenge.id,
                "name": challenge.name,
                "redirect_type": challenge.redirect_type,
                "redirect_port": challenge.redirect_port,
            }
            if challenge is not None
            else None
        ),
    }
    if with_subdomain:
        data["http_subdomain"] = render_http_subdomain(container)
    return data


def render_http_subdomain(container) -> str:
    return render(
        whale_config("template_http_subdomain"),
        container=container_context(container, with_subdomain=False),
    )


def render_flag(flag_template: str) -> str:
    return render(
        flag_template, uuid=_uuid, random=_random, random_string=random_string
    )
