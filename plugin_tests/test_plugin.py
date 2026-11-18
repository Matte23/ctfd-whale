import json
from collections import namedtuple

from conftest import REPO, plugin
from tests.helpers import login_as_user


def test_load_fills_default_settings(app):
    config = plugin("utils.config")
    with app.app_context():
        for key, default in config.DEFAULTS.items():
            assert config.whale_config(key) == default, key


def _config_page(app, monkeypatch):
    """CTFd's Config page, with this plugin's config.json tabs.

    CTFd finds config.json by scanning CTFd/plugins; in the tests the plugin is
    loaded from this checkout instead, so point the lookup at its file.
    """
    plugin_type = namedtuple("Plugin", ["name", "route", "config"])
    entries = json.loads((REPO / "config.json").read_text())
    tabs = [plugin_type(e["name"], e.get("route"), e.get("config")) for e in entries]
    monkeypatch.setitem(app.jinja_env.globals, "get_configurable_plugins", lambda: tabs)
    with login_as_user(app, name="admin") as admin:
        r = admin.get("/admin/config")
        assert r.status_code == 200
        return r.get_data(as_text=True)


def test_settings_are_tabs_in_ctfds_config_page(app, monkeypatch):
    page = _config_page(app, monkeypatch)
    for name in (
        "Whale: Docker",
        "Whale: Router",
        "Whale: Limits",
        "Whale: Challenges",
    ):
        assert name in page
    # one form per tab, saved by CTFd's own config page script
    assert page.count('<form class="whale-settings"') == 4
    assert 'name="whale:docker_api_url"' in page
    assert 'value="unix:///var/run/docker.sock"' in page
    assert 'id="docker-use-swarm" name="whale:docker_use_swarm"' in page
    assert 'id="docker-use-ssl"' in page and 'id="docker-ssl-config"' in page
    # the router type is a field of its tab; both routers' fields are there
    assert 'id="router-type" name="whale:router_type"' in page
    assert 'name="whale:frp_api_password"' in page
    assert 'name="whale:trp_api_url"' in page
    assert 'name="whale:docker_dns_containers"' in page
    # the tabs' script is registered for admin pages
    assert "/assets/config.js" in page


def test_old_settings_url_redirects_to_config(app):
    with login_as_user(app, name="admin") as admin:
        r = admin.get("/plugins/ctfd-whale/admin/settings")
        assert r.status_code == 302
        assert r.headers["Location"].endswith("/admin/config")


def test_checks_endpoint(app, monkeypatch):
    checks = plugin("utils.checks")
    monkeypatch.setattr(checks, "check_docker_api", lambda: "Docker API url incorrect")
    monkeypatch.setattr(checks, "check_router_connection", lambda: None)
    with login_as_user(app, name="admin") as admin:
        r = admin.get("/api/v1/plugins/ctfd-whale/admin/checks")
        assert r.get_json() == {
            "success": True,
            "data": {"docker": "Docker API url incorrect", "router": None},
        }


def test_admin_containers_page_view_modes(app):
    with login_as_user(app, name="admin") as admin:
        assert admin.get("/plugins/ctfd-whale/admin/containers").status_code == 200
        r = admin.get("/plugins/ctfd-whale/admin/containers?mode=card")
        assert r.status_code == 200
        # an unknown mode falls back to "list" instead of breaking the page
        r = admin.get("/plugins/ctfd-whale/admin/containers?mode=../../admin/base")
        assert r.status_code == 200
        assert admin.get("/plugins/ctfd-whale/admin/containers").status_code == 200
