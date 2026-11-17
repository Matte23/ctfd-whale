from conftest import plugin
from tests.helpers import login_as_user


def test_load_fills_default_settings(app):
    config = plugin("utils.config")
    with app.app_context():
        for key, default in config.DEFAULTS.items():
            assert config.whale_config(key) == default, key


def test_admin_settings_page(app):
    with login_as_user(app, name="admin") as admin:
        r = admin.get("/plugins/ctfd-whale/admin/settings")
        assert r.status_code == 200
        assert b"Swarm" in r.data


def test_admin_containers_page_view_modes(app):
    with login_as_user(app, name="admin") as admin:
        assert admin.get("/plugins/ctfd-whale/admin/containers").status_code == 200
        r = admin.get("/plugins/ctfd-whale/admin/containers?mode=card")
        assert r.status_code == 200
        # an unknown mode falls back to "list" instead of breaking the page
        r = admin.get("/plugins/ctfd-whale/admin/containers?mode=../../admin/base")
        assert r.status_code == 200
        assert admin.get("/plugins/ctfd-whale/admin/containers").status_code == 200
