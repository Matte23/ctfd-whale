from flask import Blueprint

from CTFd.models import (
    db,
    Flags,
)
from CTFd.plugins.challenges import BaseChallenge
from CTFd.plugins.dynamic_challenges import DynamicValueChallenge
from CTFd.plugins.flags import get_flag_class
from CTFd.utils import user as current_user
from .models import WhaleContainer, DynamicDockerChallenge
from .utils.control import ControlUtil


class DynamicValueDockerChallenge(BaseChallenge):
    id = "dynamic_docker"  # Unique identifier used to register challenges
    name = "dynamic_docker"  # Name of a challenge type
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
    # Blueprint used to access the static_folder directory.
    blueprint = Blueprint(
        "ctfd-whale-challenge",
        __name__,
        template_folder="templates",
        static_folder="assets",
    )
    challenge_model = DynamicDockerChallenge

    @classmethod
    def read(cls, challenge):
        challenge = DynamicDockerChallenge.query.filter_by(id=challenge.id).first()
        data = super().read(challenge)
        data.update(
            {
                "initial": challenge.initial,
                "decay": challenge.decay,
                "minimum": challenge.minimum,
                "function": challenge.function,
                "memory_limit": challenge.memory_limit,
                "cpu_limit": challenge.cpu_limit,
                "dynamic_score": challenge.dynamic_score,
                "init": challenge.init,
                "privileged": challenge.privileged,
                "docker_image": challenge.docker_image,
                "redirect_type": challenge.redirect_type,
                "redirect_port": challenge.redirect_port,
            }
        )
        return data

    @classmethod
    def update(cls, challenge, request):
        data = request.form or request.get_json()

        for attr, value in data.items():
            # We need to set these to floats so that the next operations don't operate on strings
            if attr in ("initial", "minimum", "decay"):
                value = float(value)
            if attr == "dynamic_score":
                value = int(value)
            setattr(challenge, attr, value)

        if challenge.dynamic_score == 1:
            return DynamicValueChallenge.calculate_value(challenge)

        db.session.commit()
        return challenge

    @classmethod
    def attempt(cls, challenge, request):
        data = request.form or request.get_json()
        submission = data["submission"].strip()

        flags = Flags.query.filter_by(challenge_id=challenge.id).all()

        if len(flags) > 0:
            for flag in flags:
                if get_flag_class(flag.type).compare(flag, submission):
                    return True, "Correct"
            return False, "Incorrect"
        else:
            user_id = current_user.get_current_user().id
            q = db.session.query(WhaleContainer)
            q = q.filter(WhaleContainer.user_id == user_id)
            q = q.filter(WhaleContainer.challenge_id == challenge.id)
            records = q.all()
            if len(records) == 0:
                return False, "Please solve it during the container is running"

            container = records[0]
            if container.flag == submission:
                return True, "Correct"
            return False, "Incorrect"

    @classmethod
    def solve(cls, user, team, challenge, request):
        super().solve(user, team, challenge, request)

        if challenge.dynamic_score == 1:
            DynamicValueChallenge.calculate_value(challenge)

    @classmethod
    def delete(cls, challenge):
        for container in WhaleContainer.query.filter_by(
            challenge_id=challenge.id
        ).all():
            ControlUtil.try_remove_container(container.user_id)
        super().delete(challenge)
