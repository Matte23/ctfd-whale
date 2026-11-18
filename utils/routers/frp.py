"""frp router: one frpc proxy per container, managed through frpc's store API.

Needs the official frp, v0.72.0 or later, with the store enabled in
frpc.toml ([store] path = ...) and the admin API (webServer.*) reachable
with user and password. Each proxy is created, updated and deleted on its
own (POST/PUT/DELETE /api/store/proxies); frpc applies the change right
away and keeps the store on disk across restarts.

Only proxies named PROXY_PREFIX + <container name> are managed: any other
store proxy an admin adds is left alone.
"""

from flask import current_app
from requests import RequestException, session

from ...models import WhaleContainer
from .. import db as container_db
from ..config import whale_config
from .base import BaseRouter

REQUEST_TIMEOUT_SECONDS = 5
PROXY_PREFIX = "whale-"
STORE_PATH = "/api/store/proxies"


class FrpRouter(BaseRouter):
    name = "frp"
    # cheap reconcile (one GET when nothing changed): run on every auto-clean
    periodic_sync = True
    # redirect type of the challenge -> frp proxy type
    types = {
        "direct": "tcp",
        "http": "http",
    }

    def __init__(self):
        super().__init__()
        self.ses = session()

    @property
    def url(self):
        return whale_config("frp_api_url").rstrip("/")

    def _request(self, method, path, **kwargs):
        password = whale_config("frp_api_password")
        auth = (str(whale_config("frp_api_user")), str(password)) if password else None
        return self.ses.request(
            method,
            self.url + path,
            auth=auth,
            timeout=REQUEST_TIMEOUT_SECONDS,
            **kwargs,
        )

    @staticmethod
    def proxy_name(container: WhaleContainer) -> str:
        return PROXY_PREFIX + container.name

    def _routable(self, container: WhaleContainer) -> bool:
        challenge = container.challenge
        if challenge is None:
            # deleted: the container is waiting for cleanup
            return False
        if challenge.redirect_type not in self.types:
            # rejected when saving challenges; may still exist from before
            current_app.logger.warning(
                "[CTFd Whale] container %s: unknown redirect type %r, not routed",
                container.id,
                challenge.redirect_type,
            )
            return False
        # direct containers need their port (allocated in register)
        return challenge.redirect_type != "direct" or bool(container.port)

    def definition(self, container: WhaleContainer) -> dict:
        """The store's JSON body for the container's proxy."""
        proxy_type = self.types[container.challenge.redirect_type]
        block = {
            "localIP": container.name,
            "localPort": int(container.challenge.redirect_port),
            "transport": {"useCompression": True},
        }
        if proxy_type == "http":
            block["subdomain"] = container.http_subdomain
        else:
            block["remotePort"] = int(container.port)
        return {
            "name": self.proxy_name(container),
            "type": proxy_type,
            proxy_type: block,
        }

    @staticmethod
    def _matches(current: dict, wanted: dict) -> bool:
        """Whether the stored proxy has every value we set (frpc may add others)."""

        def contains(have, want):
            if isinstance(want, dict):
                return isinstance(have, dict) and all(
                    contains(have.get(k), v) for k, v in want.items()
                )
            return have == want

        return contains(current, wanted)

    def _put(self, definition: dict):
        """Create the proxy, or update it when it already exists."""
        resp = self._request("POST", STORE_PATH, json=definition)
        if resp.status_code == 409:
            resp = self._request(
                "PUT", f"{STORE_PATH}/{definition['name']}", json=definition
            )
        resp.raise_for_status()

    def _delete(self, name: str):
        resp = self._request("DELETE", f"{STORE_PATH}/{name}")
        # already gone: fine, removals may be retried
        if resp.status_code != 404:
            resp.raise_for_status()

    def access(self, container: WhaleContainer):
        if container.challenge.redirect_type == "direct":
            return f'nc {whale_config("frp_direct_ip_address")} {container.port}'
        elif container.challenge.redirect_type == "http":
            host = whale_config("frp_http_domain_suffix")
            port = whale_config("frp_http_port")
            host += f":{port}" if port != 80 else ""
            return f"http://{container.http_subdomain}.{host}/"
        return ""

    def register(self, container: WhaleContainer):
        if container.challenge.redirect_type == "direct" and not container.port:
            port = container_db.allocate_port(
                container,
                range(
                    int(whale_config("frp_direct_port_minimum")),
                    int(whale_config("frp_direct_port_maximum")) + 1,
                ),
            )
            if port is None:
                return False, "No available ports. Please wait for a few minutes."
        if not self._routable(container):
            return False, "Unable to register the instance, please try again later."
        try:
            self._put(self.definition(container))
        except RequestException:
            current_app.logger.exception("[CTFd Whale] frpc: registering failed")
            return False, "Unable to register the instance, please try again later."
        return True, "success"

    def unregister(self, container: WhaleContainer):
        try:
            self._delete(self.proxy_name(container))
        except RequestException as e:
            return False, f"frpc request failed: {e}"
        return True, "success"

    def sync(self):
        """Make frpc's whale-* proxies match the running containers.

        Creates missing or outdated proxies and deletes those of containers
        that are gone, e.g. after frpc lost its store or a removal failed.
        """
        resp = self._request("GET", STORE_PATH)
        resp.raise_for_status()
        current = {
            proxy["name"]: proxy
            for proxy in resp.json().get("proxies") or []
            if str(proxy.get("name", "")).startswith(PROXY_PREFIX)
        }
        wanted = {
            self.proxy_name(c): self.definition(c)
            for c in container_db.get_running_containers()
            if self._routable(c)
        }
        for name in current.keys() - wanted.keys():
            self._delete(name)
        for name, definition in wanted.items():
            if name not in current or not self._matches(current[name], definition):
                self._put(definition)

    def check_availability(self):
        try:
            resp = self._request("GET", "/api/status")
            if resp.status_code == 401:
                return (
                    False,
                    "frpc admin api unauthorized: check the frp API user and password",
                )
            store = self._request("GET", STORE_PATH)
        except RequestException:
            return False, "Unable to access frpc admin api"
        if store.status_code == 404:
            return False, (
                "frpc store is not enabled: set [store] path in frpc.toml "
                "(needs the official frp, v0.72.0 or later)"
            )
        if not store.ok:
            return False, f"frpc store api error: HTTP {store.status_code}"
        return True, "Available"
