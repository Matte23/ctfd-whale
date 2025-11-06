import random
import string
import uuid

from CTFd.models import Flags, db
from CTFd.plugins.ctfd_cheaters import report_cheater
from CTFd.plugins.flags import CTFdStaticFlag
from CTFd.utils import get_config
from CTFd.utils.user import get_current_user
from jinja2 import Template

from .models import DynamicDockerChallenge


def random_string(length: int = 16):
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


class PersonalFlag(CTFdStaticFlag):
    name: str = "personal"

    @staticmethod
    def compare(chal_key_obj, provided):
        saved = chal_key_obj.content
        data = chal_key_obj.data

        if len(saved) != len(provided):
            return False
        result = 0

        for x, y in zip(saved, provided):
            result |= ord(x) ^ ord(y)

        if result == 0:
            # If the flag is correct, we need to check if the team is the one associated with the flag
            user_id = chal_key_obj.data
            curr_user_id = get_current_user().id

            if int(user_id) == int(curr_user_id):
                return True

            # Caught a cheater!
            report_cheater(
                chal_key_obj.challenge_id, curr_user_id, user_id, chal_key_obj.id
            )

        return False

    @staticmethod
    def create_if_missing(challenge_id: int, user_id: int):
        flags = Flags.query.filter_by(id=challenge_id, data=user_id).all()

        if len(flags) == 0:
            flag_content = PersonalFlag.generate_flag(challenge_id)
            new_flag = Flags(
                challenge_id=challenge_id,
                type="personal",
                content=flag_content,
                data=user_id,
            )
            db.session.add(new_flag)
            db.session.commit()
            return new_flag.id

        return flags[0].id

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
