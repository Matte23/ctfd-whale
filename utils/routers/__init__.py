from ..config import whale_config
from ..exceptions import WhaleError
from ..state import whale_state
from .frp import FrpRouter
from .trp import TrpRouter

ROUTERS = {
    'frp': FrpRouter,
    'trp': TrpRouter,
}


def get_router():
    """The router of the configured type, shared within this process.

    Routers read their settings when used, so only a change of type needs a
    new instance. Creating one has no side effects.
    """
    router_type = whale_config("router_type")
    if router_type not in ROUTERS:
        raise WhaleError(f"invalid router type: {router_type}")
    state = whale_state()
    router = state.get("router")
    if router is None or router.name != router_type:
        router = ROUTERS[router_type]()
        state["router"] = router
    return router


__all__ = ["ROUTERS", "get_router"]
