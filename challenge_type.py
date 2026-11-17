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


class DockerChallenge(BaseChallenge):
    id = "docker"  # Unique identifier used to register challenges
    name = "docker"  # Name of a challenge type
    templates = {
        "create": "/plugins/ctfd-whale/assets/create.html",
        "update": "/plugins/ctfd-whale/assets/update.html",
        "view": "/plugins/ctfd-whale/assets/view.html",
    }
    scripts = {
        "create": "/plugins/ctfd-whale/assets/create.js",
        "update": "/plugins/ctfd-whale/assets/update.js",
        "view": "/plugins/ctfd-whale/assets/view.js",
    }
    route = "/plugins/ctfd-whale/assets/"
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
