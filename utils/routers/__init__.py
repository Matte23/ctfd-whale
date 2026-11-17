from CTFd.utils import get_config

from .frp import FrpRouter
from .trp import TrpRouter

_routers = {
    'frp': FrpRouter,
    'trp': TrpRouter,
}


def instanciate(cls):
    return cls()


@instanciate
class Router:
    _name = ''
    _refresh = None
    _router = None

    def __getattr__(self, name: str):
        # re-create the router when its type changes or settings were saved
        # (whale:refresh gets a new token on every save), in every worker
        router_conftype = get_config("whale:router_type", "frp")
        refresh = get_config("whale:refresh")
        if Router._name != router_conftype or Router._refresh != refresh:
            Router._router = _routers[router_conftype]()
            Router._name = router_conftype
            Router._refresh = refresh
        return getattr(Router._router, name)

    @staticmethod
    def reset():
        Router._name = ''
        Router._refresh = None
        Router._router = None


__all__ = ["Router"]
