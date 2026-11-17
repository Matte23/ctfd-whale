import datetime
import traceback

from ..models import WhaleContainer
from .config import whale_config
from .db import DBContainer, db
from .docker import DockerUtils
from .routers import get_router


class ControlUtil:
    @staticmethod
    def try_add_container(user_id: int, challenge_id: int, flag_id: int):
        container = DBContainer.create_container_record(user_id, challenge_id, flag_id)
        try:
            DockerUtils.add_container(container)
        except Exception:
            print(traceback.format_exc())
            ControlUtil._discard_container(container)
            return False, "Docker Creation Error"
        try:
            ok, msg = get_router().register(container)
        except Exception:
            print(traceback.format_exc())
            ok, msg = False, "Unable to register the instance, please try again later."
        if not ok:
            ControlUtil._discard_container(container)
            return False, msg
        return True, "Container created"

    @staticmethod
    def _discard_container(container):
        """Clean up after a failed creation.

        Docker resources (network, already-started containers) may exist even
        if creation failed partway: remove them like any other container.
        """
        ControlUtil.remove_container(container)

    @staticmethod
    def try_remove_container(user_id: int):
        container = DBContainer.get_current_containers(user_id=user_id)
        if not container:
            return False, "No such container"
        return ControlUtil.remove_container(container)

    @staticmethod
    def remove_container(container):
        """Remove the container now, or hand it over to auto-clean.

        Every step can safely run again. If one fails, the row is marked as
        removing and auto-clean retries on its next run, instead of the
        request retrying or waiting (e.g. for Swarm to free a network).
        """
        try:
            ok, msg = get_router().unregister(container)
            if not ok:
                raise RuntimeError(f"router unregister failed: {msg}")
            DockerUtils.remove_container(container)
            # deleting the row frees the port and subnet: only do it once
            # the old container is really gone
            DBContainer.remove_container_record(container)
            return True, "Container destroyed"
        except Exception:
            print(traceback.format_exc())
            DBContainer.mark_removing(container)
            return True, "Your instance is being destroyed."

    @staticmethod
    def try_renew_container(user_id: int):
        container = DBContainer.get_current_containers(user_id)
        if not container:
            return False, "No such container"
        return ControlUtil.renew_container(container)

    @staticmethod
    def renew_container(container: WhaleContainer):
        if container.is_removing:
            return False, "This instance is being destroyed"
        timeout = int(whale_config("docker_timeout"))
        container.start_time = container.start_time + datetime.timedelta(
            seconds=timeout
        )
        if container.start_time > datetime.datetime.now():
            container.start_time = datetime.datetime.now()
            # race condition? useless maybe?
            # useful when docker_timeout < poll timeout (10 seconds)
            # doesn't make any sense
        else:
            return False, "Invalid container"
        container.renew_count += 1
        db.session.commit()
        return True, "Container Renewed"
