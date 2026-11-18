"""The frp router against a real frpc/frps (official images).

Skipped unless WHALE_FRPC_URL points to a running frpc admin API, e.g.:

    WHALE_FRPC_URL=http://127.0.0.1:17400 WHALE_FRPC_PASSWORD=change-me make test

with frpc and frps started from docs/frp/frpc.toml and docs/frp/frps.toml.
"""

import os

import pytest
import requests
from conftest import (
    clear_frequency_limit,
    container_url,
    create_docker_challenge,
    player,
    plugin,
    run_auto_clean,
    set_whale_config,
)
from tests.helpers import login_as_user

FRPC_URL = os.environ.get("WHALE_FRPC_URL")
USER = os.environ.get("WHALE_FRPC_USER", "admin")
PASSWORD = os.environ.get("WHALE_FRPC_PASSWORD", "change-me")

pytestmark = pytest.mark.skipif(not FRPC_URL, reason="WHALE_FRPC_URL not set")


@pytest.fixture
def real_frpc(app, monkeypatch):
    FrpRouter = plugin("utils.routers.frp").FrpRouter
    monkeypatch.setattr(FrpRouter, "_request", app.originals["frp_request"])
    set_whale_config(
        app, frp_api_url=FRPC_URL, frp_api_user=USER, frp_api_password=PASSWORD
    )
    yield
    # leave frpc clean for the next test
    for proxy in _store()["proxies"] or []:
        if proxy["name"].startswith("whale-"):
            requests.delete(
                f"{FRPC_URL}/api/store/proxies/{proxy['name']}",
                auth=(USER, PASSWORD),
                timeout=5,
            )


def _store():
    r = requests.get(f"{FRPC_URL}/api/store/proxies", auth=(USER, PASSWORD), timeout=5)
    r.raise_for_status()
    return r.json()


def _names():
    return {p["name"] for p in _store()["proxies"] or []}


def _container(app):
    WhaleContainer = plugin("models").WhaleContainer
    with app.app_context():
        return WhaleContainer.query.one_or_none()


def test_availability_and_auth(app, real_frpc):
    FrpRouter = plugin("utils.routers.frp").FrpRouter
    with app.app_context():
        assert FrpRouter().check_availability() == (True, "Available")
    set_whale_config(app, frp_api_password="wrong")
    with app.app_context():
        ok, message = FrpRouter().check_availability()
    assert not ok and "unauthorized" in message


def test_http_and_direct_proxies_lifecycle(app, real_frpc):
    http_id = create_docker_challenge(app, name="web", redirect_port=8000)
    direct_id = create_docker_challenge(
        app, name="pwn", redirect_type="direct", redirect_port=1337
    )
    with player(app, "alice") as alice:
        assert alice.post(container_url(http_id), json={}).status_code == 200
    with player(app, "bob") as bob:
        r = bob.post(container_url(direct_id), json={})
        assert r.status_code == 200, r.get_json()

    WhaleContainer = plugin("models").WhaleContainer
    with app.app_context():
        containers = {c.challenge.name: c for c in WhaleContainer.query.all()}
    proxies = {p["name"]: p for p in _store()["proxies"]}
    web = proxies[f"whale-{containers['web'].name}"]
    assert web["type"] == "http"
    assert web["http"]["subdomain"] == containers["web"].uuid
    assert web["http"]["localPort"] == 8000
    pwn = proxies[f"whale-{containers['pwn'].name}"]
    assert pwn["type"] == "tcp"
    assert pwn["tcp"]["remotePort"] == containers["pwn"].port

    clear_frequency_limit(app)
    with login_as_user(app, name="alice") as alice:
        assert alice.delete(container_url(), json={}).status_code == 200
    assert f"whale-{containers['web'].name}" not in _names()
    assert f"whale-{containers['pwn'].name}" in _names()


def test_sync_restores_a_lost_proxy_and_is_idempotent(app, real_frpc):
    challenge_id = create_docker_challenge(app)
    with player(app) as client:
        assert client.post(container_url(challenge_id), json={}).status_code == 200
    name = f"whale-{_container(app).name}"
    requests.delete(
        f"{FRPC_URL}/api/store/proxies/{name}", auth=(USER, PASSWORD), timeout=5
    ).raise_for_status()
    assert name not in _names()
    with app.app_context():
        run_auto_clean()
    assert name in _names()
    # a second sync finds everything up to date (no error, same proxy)
    before = _store()
    with app.app_context():
        run_auto_clean()
    assert _store() == before
