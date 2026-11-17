"""Admin container API (P1-1, P1-2, P1-3, P2-7)."""

from conftest import container_url, create_docker_challenge, player, plugin
from tests.helpers import login_as_user

ADMIN_URL = "/api/v1/plugins/ctfd-whale/admin/container"


def _launch(app, names):
    challenge_id = create_docker_challenge(app)
    for name in names:
        with player(app, name) as client:
            assert client.post(container_url(challenge_id), json={}).status_code == 200


def test_list_is_plain_json_and_paginated(app):
    _launch(app, ["alice", "bob", "carol"])
    with login_as_user(app, name="admin") as admin:
        data = admin.get(ADMIN_URL + "?per_page=2").get_json()["data"]
        assert data["total"] == 3 and data["pages"] == 2
        assert [c["user_name"] for c in data["containers"]] == ["alice", "bob"]
        first = data["containers"][0]
        assert first["challenge_name"] == "web1"
        assert first["access"].startswith("http://")
        assert first["removing"] is False
        # out-of-range values are clamped instead of crashing
        for query in ("?page=0", "?per_page=0", "?page=-3&per_page=-1", "?page=99"):
            assert admin.get(ADMIN_URL + query).status_code == 200


def test_renew_and_delete_by_container_id(app, fake_docker):
    _launch(app, ["alice"])
    WhaleContainer = plugin("models").WhaleContainer
    with app.app_context():
        container_id = WhaleContainer.query.one().id
    with login_as_user(app, name="admin") as admin:
        assert (
            admin.patch(f"{ADMIN_URL}?container_id={container_id}", json={}).status_code
            == 200
        )
        r = admin.delete(f"{ADMIN_URL}?container_id={container_id}", json={})
        assert r.get_json()["success"]
    assert fake_docker.running == set()


def test_unknown_or_missing_container_id(app):
    with login_as_user(app, name="admin") as admin:
        r = admin.delete(f"{ADMIN_URL}?container_id=12345", json={})
        assert r.status_code == 404
        # no flask-restx "did you mean" help appended (P2-7)
        assert r.get_json()["message"] == "No such container"
        assert admin.delete(ADMIN_URL, json={}).status_code == 400
        assert admin.delete(f"{ADMIN_URL}?container_id=x", json={}).status_code == 400


def test_players_cannot_use_the_admin_api(app):
    with player(app) as client:
        assert client.get(ADMIN_URL).status_code in (302, 403)
