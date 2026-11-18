import functools

from CTFd.cache import cache
from CTFd.models import Challenges, Solves
from CTFd.utils.config import is_teams_mode
from CTFd.utils.user import get_current_team, get_current_user, is_admin
from flask import g, request
from flask_restx import abort
from sqlalchemy.sql import and_

from .utils.cache import user_lock
from .utils.config import whale_config


def challenge_visible(func):
    @functools.wraps(func)
    def _challenge_visible(*args, **kwargs):
        challenge_id = request.args.get("challenge_id", type=int)
        if challenge_id is None:
            abort(400, "Missing or invalid challenge_id", success=False)
        # parsed once here for the endpoint (see current_challenge_id)
        g.whale_challenge_id = challenge_id
        if is_admin():
            challenge = Challenges.query.filter(
                Challenges.id == challenge_id,
                Challenges.type == "docker",
            ).first()
            if not challenge:
                # returned, not raised: flask-restx would append its
                # "did you mean" help to a raised 404
                return {"success": False, "message": "no such challenge"}, 404
        else:
            challenge = Challenges.query.filter(
                Challenges.id == challenge_id,
                Challenges.type == "docker",
                and_(Challenges.state != "hidden", Challenges.state != "locked"),
            ).first()
            if not challenge:
                abort(403, "challenge not visible", success=False)
            if not _prerequisites_met(challenge):
                abort(403, "challenge not unlocked", success=False)
        return func(*args, **kwargs)

    return _challenge_visible


def current_challenge_id():
    """The challenge_id of the request, validated by @challenge_visible."""
    return g.whale_challenge_id


def _prerequisites_met(challenge):
    # mirrors the prerequisite check in CTFd/api/v1/challenges.py
    if not challenge.requirements:
        return True
    requirements = challenge.requirements.get("prerequisites", [])
    if not requirements:
        return True
    all_challenge_ids = {
        c.id for c in Challenges.query.with_entities(Challenges.id).all()
    }
    prereqs = set(requirements).intersection(all_challenge_ids)
    solve_ids = {
        value
        for value, in Solves.query.with_entities(Solves.challenge_id)
        .filter_by(account_id=get_current_user().account_id)
        .all()
    }
    return solve_ids >= prereqs


def require_team_if_teams_mode(func):
    """In teams mode, require the user to be in a team.

    CTFd's own ``require_team`` aborts with 404 outside teams mode, so it
    can't be used on endpoints that must work in both modes.
    """

    @functools.wraps(func)
    def _require_team_if_teams_mode(*args, **kwargs):
        if is_teams_mode() and not is_admin() and get_current_team() is None:
            abort(403, "You must join a team first.", success=False)
        return func(*args, **kwargs)

    return _require_team_if_teams_mode


def _user_action(func, limited):
    """Serialize the container actions of a user; optionally rate limit them.

    With ``limited``, a successful action starts a cooldown of
    ``docker_frequency_limit`` seconds (0: none) during which the user's
    limited actions get a 429.
    """

    @functools.wraps(func)
    def _action(*args, **kwargs):
        if is_admin():
            return func(*args, **kwargs)

        user_id = get_current_user().id
        # kept in the shared cache, not in the session: a second login
        # must not reset the limit
        limit_key = f"whale:frequency_limit:{user_id}"
        seconds = int(whale_config("docker_frequency_limit")) if limited else 0

        lock = user_lock(user_id)
        if not lock.acquire():
            abort(429, "Request Too Fast!", success=False)
        # check and record the limit while holding the lock, so two
        # concurrent requests of the same user can't both get through
        try:
            if seconds > 0 and cache.get(limit_key):
                abort(
                    429,
                    f"Frequency limit, you should wait at least {seconds} seconds.",
                    success=False,
                )
            result = func(*args, **kwargs)
            # only successful actions count: a failed launch must not lock
            # the user out. Never with 0: the cache keeps it forever
            if seconds > 0 and isinstance(result, dict) and result.get("success"):
                cache.set(limit_key, True, timeout=seconds)
        finally:
            lock.release()
        return result

    return _action


def frequency_limited(func):
    """Launch and renew: serialized and rate limited."""
    return _user_action(func, limited=True)


def user_serialized(func):
    """Destroy: serialized with the user's other actions, never limited."""
    return _user_action(func, limited=False)
