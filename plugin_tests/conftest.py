"""Test harness: CTFd's own test app with ctfd-whale loaded from this repo.

CTFd is imported from CTFD_PATH (default: ../CTFd, at the version the plugin
targets). The plugin is registered as CTFd.plugins.ctfd-whale straight from
this checkout, so nothing is copied or linked into CTFd.

Docker, the router backend (frpc/trp) and the scheduler are replaced by
in-memory stand-ins: the tests cover the plugin's own logic, API and
database code. CTFd's testing config uses SQLite and the "simple" cache, so
migrations (skipped by CTFd on SQLite) and Redis locks are not exercised.
"""

import importlib.util
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
CTFD_PATH = Path(os.environ.get("CTFD_PATH", REPO.parent / "CTFd")).resolve()
PLUGIN_MODULE = "CTFd.plugins.ctfd-whale"

if not (CTFD_PATH / "CTFd" / "__init__.py").exists():
    raise RuntimeError(f"CTFd not found at {CTFD_PATH}: set CTFD_PATH")
sys.path.insert(0, str(CTFD_PATH))

import CTFd.plugins  # noqa: E402,F401  (parent package of the plugin module)
from tests.helpers import (  # noqa: E402  (CTFd's tests package)
    create_ctfd,
    destroy_ctfd,
    login_as_user,
    register_user,
    setup_ctfd,
)


def _import_plugin():
    """Import the plugin (once). Like CTFd, only inside an app context."""
    if PLUGIN_MODULE in sys.modules:
        return sys.modules[PLUGIN_MODULE]
    spec = importlib.util.spec_from_file_location(
        PLUGIN_MODULE, REPO / "__init__.py", submodule_search_locations=[str(REPO)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[PLUGIN_MODULE] = module
    spec.loader.exec_module(module)
    return module


def plugin(submodule):
    """A submodule of the plugin, e.g. plugin("utils.db")."""
    return sys.modules[f"{PLUGIN_MODULE}.{submodule}"]


class FakeScheduler:
    """Replaces APScheduler: auto-clean is run by hand in the tests."""

    jobs = {}

    def init_app(self, app):
        pass

    def start(self):
        pass

    def add_job(self, id, func, **kwargs):
        FakeScheduler.jobs[id] = func


class FakeDocker:
    """Replaces docker_utils.add_container/remove_container."""

    def __init__(self):
        self.running = set()
        self.fail_add = None
        self.fail_remove = False

    def add_container(self, container):
        if self.fail_add:
            raise plugin("utils.exceptions").WhaleError(self.fail_add)
        self.running.add(container.name)
        return True

    def remove_container(self, container):
        if self.fail_remove:
            raise RuntimeError("docker unreachable")
        self.running.discard(container.name)


@pytest.fixture
def app(monkeypatch):
    app = create_ctfd(setup=False, enable_plugins=True)
    with app.app_context():
        whale = _import_plugin()

        fake = FakeDocker()
        docker_utils = plugin("utils.docker")
        FrpRouter = plugin("utils.routers.frp").FrpRouter
        # the real code, for tests that drive it with a recording fake client
        originals = {
            "add_container": docker_utils.add_container,
            "frp_reload": FrpRouter.reload,
        }
        monkeypatch.setattr(docker_utils, "add_container", fake.add_container)
        monkeypatch.setattr(docker_utils, "remove_container", fake.remove_container)
        # load() builds a docker client once: never reach a real daemon
        monkeypatch.setattr(whale, "docker_client", lambda: None)
        monkeypatch.setattr(whale, "APScheduler", FakeScheduler)
        # the real frp router, minus the frpc HTTP calls
        monkeypatch.setattr(FrpRouter, "check_availability", lambda self: (True, "ok"))
        monkeypatch.setattr(FrpRouter, "reload", lambda self, exclude=None: None)

        whale.load(app)
    app = setup_ctfd(app)
    app.fake_docker = fake
    app.originals = originals
    yield app
    destroy_ctfd(app)


@pytest.fixture
def fake_docker(app):
    return app.fake_docker


def run_auto_clean():
    FakeScheduler.jobs["whale-auto-clean"]()


def set_whale_config(app, **values):
    from CTFd.utils import set_config

    with app.app_context():
        for key, value in values.items():
            set_config(f"whale:{key}", value)


def create_docker_challenge(app, **fields):
    """Create a docker challenge through the admin API; returns its id."""
    data = {
        "name": "web1",
        "category": "web",
        "description": "desc",
        "value": 100,
        "state": "visible",
        "type": "docker",
        "docker_image": "nginx:1.27",
        "redirect_type": "http",
        "redirect_port": 80,
        "memory_limit": "128m",
        "cpu_limit": 0.5,
        "flag_template": "",
        **fields,
    }
    with login_as_user(app, name="admin") as admin:
        r = admin.post("/api/v1/challenges", json=data)
        assert r.status_code == 200, r.get_json()
        return r.get_json()["data"]["id"]


def player(app, name="user"):
    """A logged-in client for a newly registered player."""
    register_user(app, name=name, email=f"{name}@examplectf.com")
    return login_as_user(app, name=name)


def container_url(challenge_id=None):
    url = "/api/v1/plugins/ctfd-whale/container"
    return url if challenge_id is None else f"{url}?challenge_id={challenge_id}"


def clear_frequency_limit(app):
    """Drop the per-user 60s limit between actions of the same test.

    Only the plugin's keys: CTFd keeps the sessions in the same cache.
    """
    from CTFd.cache import cache
    from CTFd.models import Users

    with app.app_context():
        for (user_id,) in Users.query.with_entities(Users.id):
            cache.delete(f"whale:frequency_limit:{user_id}")
