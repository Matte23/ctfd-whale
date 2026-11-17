import abc
import typing

from ...models import WhaleContainer


class BaseRouter(abc.ABC):
    """A router exposes containers to players (frp, trp).

    Must have no side effects on creation and read its settings when used:
    instances are shared within a process (see get_router()).
    """

    name: typing.ClassVar[str]

    @abc.abstractmethod
    def access(self, container: WhaleContainer) -> str:
        """How to reach the container, as plain text (not HTML).

        A URL or a command, possibly on several lines; the frontend escapes it
        and turns URLs into links.
        """

    @abc.abstractmethod
    def register(self, container: WhaleContainer) -> tuple[bool, str]:
        """Route traffic to the container: (ok, message)."""

    @abc.abstractmethod
    def unregister(self, container: WhaleContainer) -> tuple[bool, str]:
        """Stop routing to the container: (ok, message). Must be safe to repeat."""

    def sync(self):
        """Bring the router in line with the running containers (at startup)."""
        # optional hook: nothing to do unless the router keeps its own state
        return None

    @abc.abstractmethod
    def check_availability(self) -> tuple[bool, str]:
        """Whether the router backend is reachable: (ok, message)."""
