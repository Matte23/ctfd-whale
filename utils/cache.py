"""Per-user locks, backed by the Redis instance CTFd already uses."""

import warnings

import redis
from flask import current_app
from redis.exceptions import LockError

from .exceptions import WhaleError, WhaleWarning
from .state import whale_state

# Above the longest container action (a Swarm launch waits up to 60s).
LOCK_TIMEOUT_SECONDS = 120
LOCK_WAIT_SECONDS = 2.0


class _NoLock:
    """Used without Redis (filesystem/simple cache): testing only."""

    def acquire(self):
        return True

    def release(self):
        pass


class _RedisLock:
    def __init__(self, lock, blocking=True):
        self._lock = lock
        self._blocking = blocking

    def acquire(self):
        if not self._blocking:
            return self._lock.acquire(blocking=False)
        return self._lock.acquire(blocking=True, blocking_timeout=LOCK_WAIT_SECONDS)

    def release(self):
        try:
            self._lock.release()
        except LockError:
            # expired meanwhile (the action took longer than the timeout)
            pass


def redis_client():
    """The plugin's Redis client, or None when CTFd runs without Redis."""
    state = whale_state()
    if "redis" not in state:
        cache_type = current_app.config["CACHE_TYPE"]
        if cache_type == "redis":
            # CACHE_REDIS_URL, not REDIS_URL: CTFd builds it from REDIS_HOST
            # and friends when REDIS_URL is not set
            state["redis"] = redis.Redis.from_url(current_app.config["CACHE_REDIS_URL"])
        elif cache_type in ("filesystem", "simple"):
            warnings.warn(
                "[CTFd Whale] CTFd runs without Redis: per-user locks are "
                "disabled. This is for TESTING purposes only, DO NOT USE on "
                "production sites.",
                WhaleWarning,
                stacklevel=2,
            )
            state["redis"] = None
        else:
            raise WhaleError(f"Unsupported CACHE_TYPE: {cache_type!r}")
    return state["redis"]


def try_lock(name, timeout):
    """Non-blocking named lock, across workers and hosts.

    Whoever gets it does the work, the others skip it: used for periodic
    jobs scheduled in every worker and for removing a container.
    """
    client = redis_client()
    if client is None:
        return _NoLock()
    return _RedisLock(
        client.lock(f"ctfd_whale_job-{name}", timeout=timeout), blocking=False
    )


def user_lock(user_id):
    """Lock serializing the container actions of one user."""
    client = redis_client()
    if client is None:
        return _NoLock()
    return _RedisLock(
        client.lock(f"ctfd_whale_lock-{user_id}", timeout=LOCK_TIMEOUT_SECONDS)
    )
