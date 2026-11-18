from ..models import DockerChallenges
from .config import whale_config
from .exceptions import WhaleError
from .templates import random_string, render_flag

__all__ = ["generate_flag", "random_string"]


def generate_flag(challenge_id: int):
    challenge = DockerChallenges.query.filter_by(id=challenge_id).first()
    if challenge is None:
        raise WhaleError(f"No docker challenge with id {challenge_id}")
    # empty or NULL per-challenge template: use the global one
    flag_template = challenge.flag_template or whale_config("template_chall_flag")
    return render_flag(flag_template)
