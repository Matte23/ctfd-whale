"""Player endpoints: launch, info, renew, destroy, and their limits."""

import datetime
import time

from conftest import (
    clear_frequency_limit,
    container_url,
    create_docker_challenge,
    player,
    plugin,
    register_user,
    run_auto_clean,
    set_whale_config,
)
from CTFd.utils import set_config
from tests.helpers import login_as_user


def _containers(app):
    WhaleContainer = plugin("models").WhaleContainer
    with app.app_context():
        return WhaleContainer.query.all()


def test_launch_info_renew_destroy(app, fake_docker):
    challenge_id = create_docker_challenge(app)
    with player(app) as client:
        r = client.post(container_url(challenge_id), json={})
        assert r.status_code == 200, r.get_json()
        assert len(fake_docker.running) == 1

        data = client.get(container_url(challenge_id)).get_json()["data"]
        # plain text, not HTML (P1-5, P2-19)
        assert data["user_access"].startswith("http://")
        assert "<" not in data["user_access"]
        assert data["lan_domain"] in fake_docker.running
        assert 0 < data["remaining_time"] <= 3600

        clear_frequency_limit(app)
        assert client.patch(container_url(challenge_id), json={}).get_json()["success"]
        clear_frequency_limit(app)
        r = client.delete(container_url(), json={})
        assert r.get_json()["message"] == "Instance destroyed"
    assert fake_docker.running == set()
    assert _containers(app) == []


def test_start_time_is_utc(app):
    """P3-16: stored like CTFd's own timestamps (its isoformat filter adds "Z")."""
    challenge_id = create_docker_challenge(app)
    with player(app) as client:
        assert client.post(container_url(challenge_id), json={}).status_code == 200
    [container] = _containers(app)
    drift = abs(container.start_time - datetime.datetime.utcnow())
    assert drift < datetime.timedelta(seconds=60)


def test_other_challenge_shows_no_instance(app):
    first = create_docker_challenge(app, name="one")
    second = create_docker_challenge(app, name="two")
    with player(app) as client:
        assert client.post(container_url(first), json={}).status_code == 200
        assert client.get(container_url(second)).get_json()["data"] == {}
        clear_frequency_limit(app)
        # renewing from the wrong challenge is a conflict (P2-17)
        assert client.patch(container_url(second), json={}).status_code == 409


def test_challenge_id_is_required_and_checked(app):
    create_docker_challenge(app)
    with player(app) as client:
        assert client.post(container_url(), json={}).status_code == 400
        assert (
            client.post(container_url() + "?challenge_id=abc", json={}).status_code
            == 400
        )
        assert client.post(container_url(999), json={}).status_code == 403


def test_hidden_challenge_cannot_be_launched(app):
    challenge_id = create_docker_challenge(app, state="hidden")
    with player(app) as client:
        assert client.post(container_url(challenge_id), json={}).status_code == 403


def test_no_launch_before_the_ctf_starts(app):
    """P0-1: player endpoints use CTFd's CTF-time check."""
    challenge_id = create_docker_challenge(app)
    with app.app_context():
        set_config("start", int(time.time()) + 3600)
    with player(app) as client:
        assert client.post(container_url(challenge_id), json={}).status_code == 403
    assert _containers(app) == []


def test_frequency_limit(app, fake_docker):
    """P0-6: one action per minute, failures don't count, 429 when limited."""
    challenge_id = create_docker_challenge(app)
    with player(app) as client:
        fake_docker.fail_add = "No such image"
        r = client.post(container_url(challenge_id), json={})
        assert r.status_code == 500
        assert "No such image" in r.get_json()["message"]
        # the failed launch doesn't start the 60s limit
        fake_docker.fail_add = None
        assert client.post(container_url(challenge_id), json={}).status_code == 200
        assert client.delete(container_url(), json={}).status_code == 429


def test_container_limit(app):
    """P1-33: the limit counts the launch's own row; 503 when full."""
    challenge_id = create_docker_challenge(app)
    set_whale_config(app, docker_max_container_count="1")
    with player(app, "alice") as alice:
        assert alice.post(container_url(challenge_id), json={}).status_code == 200
    with player(app, "bob") as bob:
        assert bob.post(container_url(challenge_id), json={}).status_code == 503
    assert len(_containers(app)) == 1


def test_direct_ports_are_unique_and_run_out(app):
    """P0-3: ports come from the database, never twice; 503 when none left."""
    challenge_id = create_docker_challenge(
        app, redirect_type="direct", redirect_port=1337
    )
    set_whale_config(
        app, frp_direct_port_minimum="10000", frp_direct_port_maximum="10001"
    )
    for name in ("alice", "bob"):
        with player(app, name) as client:
            r = client.post(container_url(challenge_id), json={})
            assert r.status_code == 200, r.get_json()
            access = client.get(container_url(challenge_id)).get_json()["data"]
            assert access["user_access"].startswith("nc ")
    assert sorted(c.port for c in _containers(app)) == [10000, 10001]
    with player(app, "carol") as carol:
        r = carol.post(container_url(challenge_id), json={})
        assert r.status_code == 503
        assert "No available ports" in r.get_json()["message"]
    # the failed launch left nothing behind
    assert len(_containers(app)) == 2


def test_failed_removal_is_retried_by_auto_clean(app, fake_docker):
    """P2-11: a failed removal is handed to auto-clean; no new launch meanwhile."""
    challenge_id = create_docker_challenge(app)
    with player(app) as client:
        assert client.post(container_url(challenge_id), json={}).status_code == 200
        fake_docker.fail_remove = True
        clear_frequency_limit(app)
        r = client.delete(container_url(), json={})
        assert r.get_json() == {
            "success": True,
            "message": "Instance is being destroyed",
        }
        [container] = _containers(app)
        assert container.is_removing
        # no longer the player's instance, and no second one meanwhile
        assert client.get(container_url(challenge_id)).get_json()["data"] == {}
        clear_frequency_limit(app)
        assert client.post(container_url(challenge_id), json={}).status_code == 409

        fake_docker.fail_remove = False
        with app.app_context():
            run_auto_clean()
        assert _containers(app) == []
        clear_frequency_limit(app)
        assert client.post(container_url(challenge_id), json={}).status_code == 200


def test_expired_containers_are_cleaned(app, fake_docker):
    challenge_id = create_docker_challenge(app)
    with player(app) as client:
        assert client.post(container_url(challenge_id), json={}).status_code == 200
    set_whale_config(app, docker_timeout="0")
    with app.app_context():
        run_auto_clean()
    assert _containers(app) == []
    assert fake_docker.running == set()


def test_admin_is_not_rate_limited(app):
    challenge_id = create_docker_challenge(app)
    register_user(app)  # an extra user, unrelated
    with login_as_user(app, name="admin") as admin:
        assert admin.post(container_url(challenge_id), json={}).status_code == 200
        assert admin.delete(container_url(), json={}).status_code == 200
