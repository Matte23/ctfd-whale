import random
import uuid
import string

from ..models import DynamicDockerChallenge

from jinja2 import Template
from CTFd.utils import get_config


def random_string(length: int = 16):
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


class TemplateFlagUtils:
    @staticmethod
    def generate_flag(challenge_id: int):
        challenge = DynamicDockerChallenge.query.filter_by(id=challenge_id).first()
        flag_template = ""

        if challenge.flag_template != "":
            flag_template = challenge.flag_template
        else:
            flag_template = get_config(
                "whale:template_chall_flag", '{{ "flag{"+uuid.uuid4()|string+"}" }}'
            )

        return Template(flag_template).render(
            uuid=uuid, random=random, get_config=get_config, random_string=random_string
        )
