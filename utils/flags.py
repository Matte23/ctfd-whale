import secrets
import string
import uuid

from CTFd.utils import get_config
from jinja2 import Template

from ..models import DockerChallenges


# Flags must not be predictable: use the OS CSPRNG. SystemRandom has the same
# API as the random module, so existing templates using random.* keep working.
_random = secrets.SystemRandom()


def random_string(length: int = 16):
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_flag(challenge_id: int):
    challenge = DockerChallenges.query.filter_by(id=challenge_id).first()
    flag_template = ""

    if challenge.flag_template != "":
        flag_template = challenge.flag_template
    else:
        flag_template = get_config(
            "whale:template_chall_flag", '{{ "flag{"+uuid.uuid4()|string+"}" }}'
        )

    return Template(flag_template).render(
        uuid=uuid, random=_random, get_config=get_config, random_string=random_string
    )
