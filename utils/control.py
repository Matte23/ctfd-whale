import datetime

from flask import current_app

from ..models import WhaleContainer
from .cache import try_lock
from .config import whale_config
from .db import DBContainer, db
from .docker import DockerUtils
from .exceptions import WhaleError
from .routers import get_router

# Upper bound of one removal; the lock expires after it in any case.
REMOVE_LOCK_SECONDS = 120


class ControlUtil:
    @staticmethod
    def try_add_container(user_id: int, challenge_id: int, flag_id: int):
        """Launch a container: (ok, message, HTTP status for the API)."""
        container = DBContainer.create_container_record(user_id, challenge_id, flag_id)
        # Count after inserting our own row, not before: concurrent launches
        # then all see each other, so the limit can't be exceeded (at worst
        # one is refused too early). No resources exist yet, just drop the row.
        max_count = int(whale_config("docker_max_container_count"))
        if DBContainer.get_all_alive_container_count() > max_count:
            DBContainer.remove_container_record(container)
            return False, "Max container count exceed.", 503
        try:
            started = DockerUtils.add_container(container)
        except WhaleError as e:
            current_app.logger.exception("[CTFd Whale] container creation failed")
            ControlUtil._discard_container(container)
            return False, f"Docker Creation Error: {e.message}", 500
        except Exception:
            current_app.logger.exception("[CTFd Whale] container creation failed")
            ControlUtil._discard_container(container)
            return False, "Docker Creation Error", 500
        try:
            ok, msg = get_router().register(container)
        except Exception:
            current_app.logger.exception("[CTFd Whale] router registration failed")
            ok, msg = False, "Unable to register the instance, please try again later."
        if not ok:
            # no free port, or the router is unreachable
            ControlUtil._discard_container(container)
            return False, msg, 503
        if not started:
            return (
                True,
                "Container created, it is still starting: give it a minute.",
                200,
            )
        return True, "Container created", 200

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
        # one removal per container at a time (a request and auto-clean may
        # both try); whoever comes second leaves it to the first
        lock = try_lock(f"remove-{container.id}", timeout=REMOVE_LOCK_SECONDS)
        if not lock.acquire():
            return True, "Your instance is being destroyed."
        try:
            return ControlUtil._remove_container(container)
        finally:
            lock.release()

    @staticmethod
    def _remove_container(container):
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
            current_app.logger.exception(
                "[CTFd Whale] removal of container %s failed, auto-clean retries it",
                container.id,
            )
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
        # renewing restarts the timeout from now, unless already expired
        now = datetime.datetime.utcnow()
        timeout = datetime.timedelta(seconds=int(whale_config("docker_timeout")))
        if container.start_time + timeout <= now:
            return False, "Invalid container"
        container.start_time = now
        container.renew_count += 1
        db.session.commit()
        return True, "Container Renewed"
