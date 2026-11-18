"""Plugin logic without HTTP: templates, validation, docker calls, frp."""

import types

import pytest
from conftest import plugin, set_whale_config
from jinja2.exceptions import SecurityError, UndefinedError

# --- templates (P0-2) ---------------------------------------------------------


def test_default_flag_template(app):
    templates = plugin("utils.templates")
    with app.app_context():
        flag = templates.render_flag('{{ "flag{"+uuid.uuid4()|string+"}" }}')
    assert flag.startswith("flag{") and len(flag) == 42


@pytest.mark.parametrize(
    "template",
    [
        "{{ uuid.uuid4.__globals__['os'] }}",
        "{{ ''.__class__.__mro__[1].__subclasses__() }}",
        "{{ uuid.os.system('id') }}",
    ],
)
def test_sandbox_blocks_escapes(app, template):
    templates = plugin("utils.templates")
    with app.app_context(), pytest.raises((SecurityError, UndefinedError)):
        templates.render_flag(template)


def test_get_config_allowlist(app):
    templates = plugin("utils.templates")
    set_whale_config(app, frp_api_password="SECRET")
    with app.app_context():
        assert templates.render('{{ get_config("whale:frp_http_port") }}') == "8080"
        secret = '{{ get_config("whale:frp_api_password", "hidden") }}'
        assert templates.render(secret) == "hidden"


# --- docker (P1-21, P1-22, P2-9, P2-10) ---------------------------------------


@pytest.mark.parametrize(
    "image,tag",
    [
        ("nginx", ""),
        ("nginx:1.27", "1.27"),
        ("reg:5000/team/img", ""),
        ("reg:5000/team/img:windows-ltsc", "windows-ltsc"),
        ("img@sha256:abc", ""),
    ],
)
def test_image_tag(app, image, tag):
    assert plugin("utils.docker")._image_tag(image) == tag


def test_choose_node(app):
    D = plugin("utils.docker")
    WhaleError = plugin("utils.exceptions").WhaleError
    assert D.choose_node("reg:5000/img", ["linux-1", "windows-1"]) == "linux-1"
    assert D.choose_node("img:windows", ["linux-1", "windows-1"]) == "windows-1"
    with pytest.raises(WhaleError):
        D.choose_node("nginx", [""])
    assert D.node_constraints("img:windows", "windows-1") == [
        "node.labels.name==windows-1",
        "node.platform.os==windows",
    ]


class RecordingClient:
    def __init__(self):
        self.calls = []
        self.services = types.SimpleNamespace(
            create=lambda **kw: self.calls.append(("service", kw)),
            list=lambda filters: [],
        )
        self.containers = types.SimpleNamespace(
            run=lambda **kw: self.calls.append(("container", kw)),
            get=lambda name: types.SimpleNamespace(
                attrs={
                    "NetworkSettings": {
                        "Networks": {"5-abc": {"IPAddress": "10.9.0.2"}}
                    }
                }
            ),
        )


class FakeNetwork:
    name = "5-abc"

    def connect(self, name):
        pass


def _container(image):
    return types.SimpleNamespace(
        name="5-abc",
        user_id=5,
        flag=types.SimpleNamespace(content="flag{x}"),
        challenge=types.SimpleNamespace(
            docker_image=image,
            memory_limit="128m",
            cpu_limit=0.5,
            init=False,
            privileged=False,
        ),
    )


@pytest.mark.parametrize("swarm", [False, True])
def test_grouped_launch(app, monkeypatch, swarm):
    docker_mod = plugin("utils.docker")
    D = docker_mod
    client = RecordingClient()
    monkeypatch.setattr(docker_mod, "docker_client", lambda: client)
    monkeypatch.setattr(D, "_create_network", lambda c, ct, **kw: FakeNetwork())
    monkeypatch.setattr(D, "_wait_for_services", lambda c, ct: True)
    set_whale_config(
        app,
        docker_use_swarm="true" if swarm else "false",
        docker_auto_connect_containers="ctfd-dns",
    )
    with app.app_context():
        assert app.originals["add_container"](_container('{"web": "a:1", "db": "b:2"}'))

    kinds = {kind for kind, _ in client.calls}
    assert kinds == {"service" if swarm else "container"}
    names = [kw["name"] for _, kw in client.calls]
    assert names[0] == "5-abc" and names[1].startswith("5-") and len(names) == 2
    for _, kw in client.calls:
        dns = kw.get("dns") or kw["dns_config"]["Nameservers"]
        assert dns == ["10.9.0.2"]  # "ctfd-dns" serves DNS by default in both modes
        assert kw["labels"] == {"ctfd-whale.id": "5-abc"}
    if swarm:
        constraints = {tuple(kw["constraints"]) for _, kw in client.calls}
        assert constraints == {("node.labels.name==linux-1", "node.platform.os==linux")}


def test_swarm_wait(app, monkeypatch):
    docker_mod = plugin("utils.docker")
    WhaleError = plugin("utils.exceptions").WhaleError
    monkeypatch.setattr(docker_mod.time, "sleep", lambda s: None)
    monkeypatch.setattr(docker_mod, "SWARM_START_TIMEOUT_SECONDS", 0.05)

    def client(*task_states, err=None):
        status = [
            {"Status": {"State": s, **({"Err": err} if err else {})}}
            for s in task_states
        ]
        service = types.SimpleNamespace(name="5-abc", tasks=lambda: status)
        return types.SimpleNamespace(
            services=types.SimpleNamespace(list=lambda filters: [service])
        )

    container = types.SimpleNamespace(name="5-abc")
    wait = docker_mod._wait_for_services
    assert wait(client("running"), container) is True
    assert wait(client("preparing"), container) is False
    with pytest.raises(WhaleError, match="No such image"):
        wait(client("rejected", err="No such image: bad:1"), container)


# --- frp store router (P3-10) --------------------------------------------------


def test_frp_definition_matches_the_store_schema(app):
    FrpRouter = plugin("utils.routers.frp").FrpRouter
    challenge = types.SimpleNamespace(redirect_type="direct", redirect_port=1337)
    container = types.SimpleNamespace(name="5-abc", port=10001, challenge=challenge)
    assert FrpRouter().definition(container) == {
        "name": "whale-5-abc",
        "type": "tcp",
        "tcp": {
            "localIP": "5-abc",
            "localPort": 1337,
            "remotePort": 10001,
            "transport": {"useCompression": True},
        },
    }


def test_frp_matches_ignores_fields_frpc_adds(app):
    FrpRouter = plugin("utils.routers.frp").FrpRouter
    wanted = {"name": "whale-x", "type": "http", "http": {"localPort": 80}}
    stored = {"name": "whale-x", "type": "http", "http": {"localPort": 80, "extra": 1}}
    assert FrpRouter._matches(stored, wanted)
    assert not FrpRouter._matches({**stored, "http": {"localPort": 81}}, wanted)
