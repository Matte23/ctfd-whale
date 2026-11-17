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
        page = r.get_data(as_text=True)
    # fields come from the macros in templates/config/macros.html
    assert 'name="whale:docker_api_url"' in page
    assert 'value="unix:///var/run/docker.sock"' in page
    assert 'id="docker-use-swarm" name="whale:docker_use_swarm"' in page
    assert 'id="docker-use-ssl"' in page and 'id="docker-ssl-config"' in page
    assert 'id="router-type"' in page
    assert 'name="whale:frp_direct_port_maximum"' in page  # frp router fields
    assert 'name="whale:docker_dns_containers"' in page
    assert "/admin/plugins/ctfd-whale" not in page and "onchange" not in page


def test_admin_containers_page_view_modes(app):
    with login_as_user(app, name="admin") as admin:
        assert admin.get("/plugins/ctfd-whale/admin/containers").status_code == 200
        r = admin.get("/plugins/ctfd-whale/admin/containers?mode=card")
        assert r.status_code == 200
        # an unknown mode falls back to "list" instead of breaking the page
        r = admin.get("/plugins/ctfd-whale/admin/containers?mode=../../admin/base")
        assert r.status_code == 200
        assert admin.get("/plugins/ctfd-whale/admin/containers").status_code == 200
