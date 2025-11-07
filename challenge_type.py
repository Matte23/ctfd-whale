from CTFd.plugins.challenges import BaseChallenge
from flask import Blueprint

from .models import WhaleContainer, DockerChallenges
from .utils.control import ControlUtil


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
    def delete(cls, challenge):
        for container in WhaleContainer.query.filter_by(
            challenge_id=challenge.id
        ).all():
            ControlUtil.try_remove_container(container.user_id)
        super().delete(challenge)
