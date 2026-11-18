"""frp router through frpc's store API (in-memory fake frpc, see conftest)."""

from conftest import (
    clear_frequency_limit,
    container_url,
    create_docker_challenge,
    player,
    plugin,
    run_auto_clean,
)


def _container(app):
    WhaleContainer = plugin("models").WhaleContainer
    with app.app_context():
        return WhaleContainer.query.one_or_none()


def test_http_launch_creates_and_destroy_deletes_the_proxy(app, fake_frpc):
    challenge_id = create_docker_challenge(app, redirect_port=8000)
    with player(app) as client:
        assert client.post(container_url(challenge_id), json={}).status_code == 200
        container = _container(app)
        assert fake_frpc.proxies == {
            f"whale-{container.name}": {
                "name": f"whale-{container.name}",
                "type": "http",
                "http": {
                    "localIP": container.name,
                    "localPort": 8000,
                    "subdomain": container.uuid,
                    "transport": {"useCompression": True},
                },
            }
        }
        clear_frequency_limit(app)
        assert client.delete(container_url(), json={}).status_code == 200
    assert fake_frpc.proxies == {}


def test_direct_launch_uses_the_allocated_port(app, fake_frpc):
    challenge_id = create_docker_challenge(
        app, redirect_type="direct", redirect_port=1337
    )
    with player(app) as client:
        assert client.post(container_url(challenge_id), json={}).status_code == 200
    container = _container(app)
    [proxy] = fake_frpc.proxies.values()
    assert proxy["type"] == "tcp"
    assert proxy["tcp"]["remotePort"] == container.port
    assert proxy["tcp"]["localPort"] == 1337


def test_launch_while_frpc_is_down(app, fake_docker, fake_frpc):
    challenge_id = create_docker_challenge(app)
    fake_frpc.down = True
    with player(app) as client:
        r = client.post(container_url(challenge_id), json={})
        assert r.status_code == 503
    # the docker side is discarded at once; only the route removal is pending
    assert fake_docker.running == set()
    assert _container(app).is_removing
    fake_frpc.down = False
    with app.app_context():
        run_auto_clean()
    assert _container(app) is None
    assert fake_frpc.proxies == {}


def test_destroy_while_frpc_is_down_is_retried(app, fake_docker, fake_frpc):
    challenge_id = create_docker_challenge(app)
    with player(app) as client:
        assert client.post(container_url(challenge_id), json={}).status_code == 200
        fake_frpc.down = True
        clear_frequency_limit(app)
        r = client.delete(container_url(), json={})
        assert r.get_json()["message"] == "Instance is being destroyed"
    assert _container(app).is_removing
    fake_frpc.down = False
    with app.app_context():
        run_auto_clean()
    assert _container(app) is None
    assert fake_frpc.proxies == {} and fake_docker.running == set()


def test_auto_clean_reconciles_frpc(app, fake_frpc):
    challenge_id = create_docker_challenge(app)
    with player(app) as client:
        assert client.post(container_url(challenge_id), json={}).status_code == 200
    name = f"whale-{_container(app).name}"
    # frpc lost the proxy, kept a stale one, and an admin added their own
    del fake_frpc.proxies[name]
    fake_frpc.proxies["whale-gone"] = {"name": "whale-gone", "type": "tcp", "tcp": {}}
    fake_frpc.proxies["admin-ssh"] = {"name": "admin-ssh", "type": "tcp", "tcp": {}}
    with app.app_context():
        run_auto_clean()
    assert set(fake_frpc.proxies) == {name, "admin-ssh"}


def test_settings_check_reports_disabled_store(app, fake_frpc, monkeypatch):
    FrpRouter = plugin("utils.routers.frp").FrpRouter
    original = fake_frpc.request

    def no_store(method, path, **kw):
        if path.startswith(fake_frpc.STORE):
            return type(original(method, "/nope"))(404)
        return original(method, path, **kw)

    monkeypatch.setattr(fake_frpc, "request", no_store)
    with app.app_context():
        ok, message = FrpRouter().check_availability()
    assert not ok and "store is not enabled" in message
