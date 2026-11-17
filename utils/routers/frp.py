from CTFd.utils import set_config
from requests import RequestException, session

from ...models import WhaleContainer
from ..config import whale_config
from ..db import DBContainer
from ..exceptions import WhaleError
from .base import BaseRouter

REQUEST_TIMEOUT_SECONDS = 5


class FrpRouter(BaseRouter):
    name = "frp"
    types = {
        "direct": "tcp",
        "http": "http",
    }

    class FrpRule:
        def __init__(self, name, config):
            self.name = name
            self.config = config

        def __str__(self) -> str:
            return f"[{self.name}]\n" + "\n".join(
                f"{k} = {v}" for k, v in self.config.items()
            )

    def __init__(self):
        super().__init__()
        self.ses = session()

    @property
    def url(self):
        return whale_config("frp_api_url").rstrip("/")

    def _common_section(self):
        common = whale_config("frp_config_template")
        if "[common]" in common:
            return common
        remote = self.ses.get(f"{self.url}/api/config", timeout=REQUEST_TIMEOUT_SECONDS)
        remote.raise_for_status()
        set_config("whale:frp_config_template", remote.text)
        return remote.text

    def reload(self, exclude=None):
        rules = []
        for container in DBContainer.get_all_alive_container():
            # no challenge: it was deleted, the container is waiting for cleanup
            if container.uuid == exclude or container.challenge is None:
                continue
            name = f"{container.challenge.redirect_type}_{container.user_id}_{container.uuid}"
            config = {
                "type": self.types[container.challenge.redirect_type],
                "local_ip": container.name,
                "local_port": container.challenge.redirect_port,
                "use_compression": "true",
            }
            if config["type"] == "http":
                config["subdomain"] = container.http_subdomain
            elif config["type"] == "tcp":
                config["remote_port"] = container.port
            rules.append(self.FrpRule(name, config))

        try:
            config = self._common_section() + "\n" + "\n".join(str(r) for r in rules)
            self.ses.put(
                f"{self.url}/api/config", config, timeout=REQUEST_TIMEOUT_SECONDS
            ).raise_for_status()
            self.ses.get(
                f"{self.url}/api/reload", timeout=REQUEST_TIMEOUT_SECONDS
            ).raise_for_status()
        except RequestException as e:
            raise WhaleError(
                "\nfrpc request failed\n"
                + (f"{e}\n" if str(e) else "")
                + "please check the frp related configs"
            ) from None

    def access(self, container: WhaleContainer):
        if container.challenge.redirect_type == "direct":
            return f'nc {whale_config("frp_direct_ip_address")} {container.port}'
        elif container.challenge.redirect_type == "http":
            host = whale_config("frp_http_domain_suffix")
            port = whale_config("frp_http_port")
            host += f":{port}" if port != 80 else ""
            return f'<a target="_blank" href="http://{container.http_subdomain}.{host}/">Link to the Challenge</a>'
        return ""

    def register(self, container: WhaleContainer):
        if container.challenge.redirect_type == "direct" and not container.port:
            port = DBContainer.allocate_port(
                container,
                range(
                    int(whale_config("frp_direct_port_minimum")),
                    int(whale_config("frp_direct_port_maximum")) + 1,
                ),
            )
            if port is None:
                return False, "No available ports. Please wait for a few minutes."
        try:
            self.reload()
        except WhaleError as e:
            print(e.message)
            return False, "Unable to register the instance, please try again later."
        return True, "success"

    def unregister(self, container: WhaleContainer):
        self.reload(exclude=container.uuid)
        return True, "success"

    def check_availability(self):
        try:
            resp = self.ses.get(f"{self.url}/api/status", timeout=2.0)
        except RequestException:
            return False, "Unable to access frpc admin api"
        if resp.status_code == 401:
            return False, "frpc admin api unauthorized"
        return True, "Available"
