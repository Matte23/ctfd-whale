import functools
import time
from flask import request, current_app, session
from flask_restx import abort
from sqlalchemy.sql import and_

from CTFd.models import Challenges, Solves
from CTFd.utils.user import is_admin, get_current_user
from .utils.cache import CacheProvider


def challenge_visible(func):
    @functools.wraps(func)
    def _challenge_visible(*args, **kwargs):
        challenge_id = request.args.get('challenge_id')
        if is_admin():
            challenge = Challenges.query.filter(
                Challenges.id == challenge_id,
                Challenges.type == "docker",
            ).first()
            if not challenge:
                abort(404, 'no such challenge', success=False)
        else:
            challenge = Challenges.query.filter(
                Challenges.id == challenge_id,
                Challenges.type == "docker",
                and_(Challenges.state != "hidden", Challenges.state != "locked"),
            ).first()
            if not challenge:
                abort(403, 'challenge not visible', success=False)
            if not _prerequisites_met(challenge):
                abort(403, 'challenge not unlocked', success=False)
        return func(*args, **kwargs)

    return _challenge_visible


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


def frequency_limited(func):
    @functools.wraps(func)
    def _frequency_limited(*args, **kwargs):
        if is_admin():
            return func(*args, **kwargs)
        redis_util = CacheProvider(app=current_app, user_id=get_current_user().id)
        if not redis_util.acquire_lock():
            abort(403, 'Request Too Fast!', success=False)
            # last request was unsuccessful. this is for protection.

        if "limit" not in session:
            session["limit"] = int(time.time())
        else:
            if int(time.time()) - session["limit"] < 60:
                abort(403, 'Frequency limit, You should wait at least 1 min.', success=False)
        session["limit"] = int(time.time())

        result = func(*args, **kwargs)
        redis_util.release_lock()  # if any exception is raised, lock will not be released
        return result

    return _frequency_limited
