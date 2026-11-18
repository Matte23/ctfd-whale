"""Container lifecycle: launch, remove (with background retries) and renew."""

import datetime

from CTFd.models import db
from flask import current_app

from ..models import WhaleContainer
from . import db as container_db
from . import docker as docker_utils
from .cache import try_lock
from .config import whale_config
from .exceptions import WhaleError
from .routers import get_router

# Upper bound of one removal; the lock expires after it in any case.
REMOVE_LOCK_SECONDS = 120


def launch_container(user_id: int, challenge_id: int, flag_id: int):
    """Launch a container: (ok, message, HTTP status for the API)."""
    container = container_db.create_container(user_id, challenge_id, flag_id)
    # Count after inserting our own row, not before: concurrent launches
    # then all see each other, so the limit can't be exceeded (at worst
    # one is refused too early). No resources exist yet, just drop the row.
    max_count = int(whale_config("docker_max_container_count"))
    if container_db.count_alive_containers() > max_count:
        container_db.delete_container(container)
        return False, "Max container count exceed.", 503
    try:
        started = docker_utils.add_container(container)
    except WhaleError as e:
        current_app.logger.exception("[CTFd Whale] container creation failed")
        _discard(container)
        return False, f"Docker Creation Error: {e.message}", 500
    except Exception:
        current_app.logger.exception("[CTFd Whale] container creation failed")
        _discard(container)
        return False, "Docker Creation Error", 500
    try:
        ok, msg = get_router().register(container)
    except Exception:
        current_app.logger.exception("[CTFd Whale] router registration failed")
        ok, msg = False, "Unable to register the instance, please try again later."
    if not ok:
        # no free port, or the router is unreachable
        _discard(container)
        return False, msg, 503
    if not started:
        return (
            True,
            "Container created, it is still starting: give it a minute.",
            200,
        )
    return True, "Container created", 200


def _discard(container):
    """Clean up after a failed creation.

    Docker resources (network, already-started containers) may exist even
    if creation failed partway: remove them like any other container.
    """
    remove_container(container)


def remove_user_container(user_id: int):
    container = container_db.get_running_container(user_id=user_id)
    if not container:
        return False, "No such container"
    return remove_container(container)


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
        return _remove(container)
    finally:
        lock.release()


def _remove(container):
    # Every step runs even if an earlier one failed (e.g. the router is down:
    # the docker resources still go away now). Failed steps are retried by
    # auto-clean; all of them can safely run again.
    failed = False
    try:
        ok, msg = get_router().unregister(container)
        if not ok:
            raise RuntimeError(f"router unregister failed: {msg}")
    except Exception:
        failed = True
        current_app.logger.exception(
            "[CTFd Whale] container %s: removing the route failed", container.id
        )
    try:
        docker_utils.remove_container(container)
    except Exception:
        failed = True
        current_app.logger.exception(
            "[CTFd Whale] container %s: removing docker resources failed",
            container.id,
        )
    if failed:
        current_app.logger.warning(
            "[CTFd Whale] container %s marked as removing, auto-clean retries it",
            container.id,
        )
        container_db.mark_removing(container)
        return True, "Your instance is being destroyed."
    # deleting the row frees the port and subnet: only do it once the old
    # container is really gone
    container_db.delete_container(container)
    return True, "Container destroyed"


def renew_user_container(user_id: int):
    container = container_db.get_running_container(user_id)
    if not container:
        return False, "No such container"
    return renew_container(container)


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
