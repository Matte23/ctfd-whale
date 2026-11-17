import typing

from ...models import WhaleContainer


class BaseRouter:
    name = None

    def __init__(self):
        pass

    def access(self, container: WhaleContainer) -> str:
        """How to reach the container, as plain text (not HTML).

        A URL or a command, possibly on several lines; the frontend escapes it
        and turns URLs into links.
        """
        pass

    def register(self, container: WhaleContainer):
        pass

    def unregister(self, container: WhaleContainer):
        pass

    def sync(self):
        """Bring the router in line with the running containers (at startup)."""
        pass

    def check_availability(self) -> typing.Tuple[bool, str]:
        pass
