from flask import current_app
from requests import HTTPError, RequestException, session

from ...models import WhaleContainer
from .. import db as container_db
from ..config import whale_config
from .base import BaseRouter

REQUEST_TIMEOUT_SECONDS = 5


class TrpRouter(BaseRouter):
    name = "trp"

    def __init__(self):
        super().__init__()
        self.ses = session()

    @property
    def url(self):
        return whale_config("trp_api_url").rstrip("/")

    @staticmethod
    def get_domain(container: WhaleContainer):
        domain = whale_config("trp_domain_suffix").lstrip(".")
        domain = f"{container.uuid}.{domain}"
        return domain

    def access(self, container: WhaleContainer):
        ch_type = container.challenge.redirect_type
        domain = self.get_domain(container)
        port = whale_config("trp_listening_port")
        if ch_type == "direct":
            return (
                f'from pwn import *\nremote("{domain}", {port}, ssl=True).interactive()'
            )
        elif ch_type == "http":
            return f"https://{domain}" + (f":{port}" if port != 443 else "")
        else:
            return f"[ssl] {domain} {port}"

    def register(self, container: WhaleContainer):
        try:
            resp = self.ses.post(
                f"{self.url}/rule/{self.get_domain(container)}",
                json={
                    "target": f"{container.name}:{container.challenge.redirect_port}",
                    "source": None,
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            return True, "success"
        except HTTPError as e:
            return False, e.response.text
        except RequestException:
            current_app.logger.exception("[CTFd Whale] trp request failed")
            return False, "unable to access trp Api"

    def unregister(self, container: WhaleContainer):
        try:
            resp = self.ses.delete(
                f"{self.url}/rule/{self.get_domain(container)}",
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            # already gone: fine, removals may be retried
            if resp.status_code == 404:
                return True, "success"
            resp.raise_for_status()
            return True, "success"
        except HTTPError as e:
            return False, e.response.text
        except RequestException:
            current_app.logger.exception("[CTFd Whale] trp request failed")
            return False, "unable to access trp Api"

    def sync(self):
        # trp may have restarted and lost its rules: register them again
        for container in container_db.get_running_containers():
            if container.challenge is not None:
                self.register(container)

    def check_availability(self):
        try:
            self.ses.get(f"{self.url}/rules", timeout=REQUEST_TIMEOUT_SECONDS).json()
        except RequestException:
            return False, "Unable to access trp admin api"
        except Exception:
            return False, "Unknown trp error"
        return True, "Available"
