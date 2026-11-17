from CTFd.exceptions.challenges import (
    ChallengeCreateException,
    ChallengeUpdateException,
)
from CTFd.plugins.challenges import BaseChallenge
from flask import Blueprint

from .models import DockerChallenges, WhaleContainer
from .utils.control import ControlUtil
from .utils.validation import CHALLENGE_FIELDS, validate_challenge


def _submitted(request):
    data = request.form or request.get_json() or {}
    return {key: data[key] for key in data}


# CTFd serves plugin assets from the plugin's directory: their URL must use
# its real name ("CTFd.plugins.<dir>.challenge_type"). Page and API URLs
# stay fixed under /plugins/ctfd-whale.
_ASSETS = f"/plugins/{__name__.split('.')[-2]}/assets/"


class DockerChallenge(BaseChallenge):
    id = "docker"  # Unique identifier used to register challenges
    name = "docker"  # Name of a challenge type
    templates = {
        "create": _ASSETS + "create.html",
        "update": _ASSETS + "update.html",
        "view": _ASSETS + "view.html",
    }
    scripts = {
        "create": _ASSETS + "create.js",
        "update": _ASSETS + "update.js",
        "view": _ASSETS + "view.js",
    }
    route = _ASSETS
    # Blueprint used to access the static_folder directory.
    blueprint = Blueprint(
        "ctfd-whale-challenge",
        __name__,
        template_folder="templates",
        static_folder="assets",
    )
    challenge_model = DockerChallenges

    @classmethod
    def create(cls, request):
        # validate before anything is saved; CTFd shows the message to the admin
        values = {**CHALLENGE_FIELDS, **_submitted(request)}
        try:
            validate_challenge(values)
        except ValueError as e:
            raise ChallengeCreateException(str(e))
        return super().create(request)

    @classmethod
    def update(cls, challenge, request):
        # only the submitted fields change: check them merged with the stored ones
        values = {field: getattr(challenge, field) for field in CHALLENGE_FIELDS}
        values.update(_submitted(request))
        try:
            validate_challenge(values)
        except ValueError as e:
            raise ChallengeUpdateException(str(e))
        return super().update(challenge, request)

    @classmethod
    def delete(cls, challenge):
        for container in WhaleContainer.query.filter_by(
            challenge_id=challenge.id
        ).all():
            # if this fails, the row is marked as removing and survives the
            # deletion (SET NULL): auto-clean retries the removal
            ControlUtil.remove_container(container)
        super().delete(challenge)
