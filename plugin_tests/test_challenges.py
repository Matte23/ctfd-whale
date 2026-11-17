"""Docker challenges: validation when admins save them (P1-26, P1-23)."""

from conftest import create_docker_challenge, plugin, set_whale_config
from tests.helpers import login_as_user


def _post_challenge(app, **fields):
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
        **fields,
    }
    with login_as_user(app, name="admin") as admin:
        return admin.post("/api/v1/challenges", json=data)


def _challenge_count(app):
    DockerChallenges = plugin("models").DockerChallenges
    with app.app_context():
        return DockerChallenges.query.count()


def test_valid_challenge_is_created(app):
    challenge_id = create_docker_challenge(app)
    DockerChallenges = plugin("models").DockerChallenges
    with app.app_context():
        challenge = DockerChallenges.query.get(challenge_id)
        assert challenge.docker_image == "nginx:1.27"
        assert challenge.redirect_port == 80


def test_grouped_image_is_accepted(app):
    r = _post_challenge(app, docker_image='{"web": "img/web:1", "db": "mariadb:10.11"}')
    assert r.status_code == 200, r.get_json()


def _assert_rejected(response, needle):
    assert response.status_code == 500  # how CTFd reports ChallengeCreateException
    errors = response.get_json()["errors"][""]
    assert any(needle in e for e in errors), errors


def test_invalid_fields_are_rejected_and_nothing_saved(app):
    cases = {
        "docker_image": ("", "Docker image is required"),
        "memory_limit": ("0", "memory limit"),
        "cpu_limit": (0, "CPU limit"),
        "redirect_type": ("0", "redirect type"),
        "redirect_port": (70000, "Redirect port"),
        "flag_template": ("{{ unclosed", "Flag template error"),
    }
    for field, (value, needle) in cases.items():
        _assert_rejected(_post_challenge(app, **{field: value}), needle)
    assert _challenge_count(app) == 0


def test_flag_template_runs_in_the_sandbox(app):
    r = _post_challenge(app, flag_template="{{ uuid.uuid4.__globals__['os'] }}")
    _assert_rejected(r, "unsafe")


def test_privileged_rejected_with_swarm(app):
    set_whale_config(app, docker_use_swarm="true")
    _assert_rejected(_post_challenge(app, privileged=True), "Privileged")
    set_whale_config(app, docker_use_swarm="false")
    assert _post_challenge(app, privileged=True).status_code == 200


def test_update_validates_merged_values(app):
    challenge_id = create_docker_challenge(app)
    with login_as_user(app, name="admin") as admin:
        url = f"/api/v1/challenges/{challenge_id}"
        r = admin.patch(url, json={"memory_limit": "lots"})
        assert r.status_code == 500
        assert admin.patch(url, json={"memory_limit": "256m"}).status_code == 200
    DockerChallenges = plugin("models").DockerChallenges
    with app.app_context():
        assert DockerChallenges.query.get(challenge_id).memory_limit == "256m"
