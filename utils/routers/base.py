import typing

from ...models import WhaleContainer


class BaseRouter:
    name = None

    def __init__(self):
        pass

    def access(self, container: WhaleContainer):
        pass

    def register(self, container: WhaleContainer):
        pass

    def unregister(self, container: WhaleContainer):
        pass

    def release(self, container: WhaleContainer):
        """Give back resources (e.g. ports) held for the container.

        Called only once the container is gone from docker, so they can't be
        handed to someone else while the old container still uses them.
        """
        pass

    def reload(self):
        pass

    def check_availability(self) -> typing.Tuple[bool, str]:
        pass
