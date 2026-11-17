import datetime
import random

from CTFd.models import db
from sqlalchemy.exc import IntegrityError

from ..models import WhaleContainer, WhaleRedirectTemplate
from .config import whale_config

# Retries when another worker takes the same port/subnet at the same time.
ALLOCATION_ATTEMPTS = 10


def _expiry_cutoff():
    """Containers started before this are expired."""
    timeout = int(whale_config("docker_timeout"))
    return datetime.datetime.now() - datetime.timedelta(seconds=timeout)


class DBContainer:
    @staticmethod
    def create_container_record(user_id: int, challenge_id: int, flag_id: int):
        container = WhaleContainer(
            user_id=user_id, challenge_id=challenge_id, flag_id=flag_id
        )
        db.session.add(container)
        db.session.commit()

        return container

    @staticmethod
    def get_current_containers(user_id: int):
        q = db.session.query(WhaleContainer)
        q = q.filter(WhaleContainer.user_id == user_id)
        return q.first()

    @staticmethod
    def get_container_by_id(container_id: int):
        return WhaleContainer.query.filter_by(id=container_id).first()

    @staticmethod
    def get_container_by_port(port: int):
        q = db.session.query(WhaleContainer)
        q = q.filter(WhaleContainer.port == port)
        return q.first()

    @staticmethod
    def remove_container_record(container: WhaleContainer):
        # delete by id, not by user: removing one record must never drop
        # another container's record and orphan its docker resources
        q = db.session.query(WhaleContainer)
        q = q.filter(WhaleContainer.id == container.id)
        q.delete()
        db.session.commit()

    @staticmethod
    def get_all_expired_container():
        q = db.session.query(WhaleContainer)
        q = q.filter(WhaleContainer.start_time < _expiry_cutoff())
        return q.all()

    @staticmethod
    def _alive_query():
        q = db.session.query(WhaleContainer)
        return q.filter(WhaleContainer.start_time >= _expiry_cutoff())

    @staticmethod
    def get_all_alive_container():
        return DBContainer._alive_query().all()

    @staticmethod
    def get_all_container():
        q = db.session.query(WhaleContainer)
        return q.all()

    @staticmethod
    def get_all_alive_container_page(page_start: int, page_end: int):
        q = DBContainer._alive_query().slice(page_start, page_end)
        return q.all()

    @staticmethod
    def get_all_alive_container_count():
        return DBContainer._alive_query().count()

    @staticmethod
    def _allocate(container: WhaleContainer, column: str, candidates):
        """Store a free value of ``column`` (port/subnet) on the container.

        Picks at random among the candidates no row holds yet. The unique
        constraint on the column catches another worker taking the same
        value meanwhile: then roll back and try again.
        Returns the value, or None when nothing is free.
        """
        candidates = list(candidates)
        for _ in range(ALLOCATION_ATTEMPTS):
            attribute = getattr(WhaleContainer, column)
            taken = {
                value
                for (value,) in db.session.query(attribute).filter(
                    attribute.isnot(None)
                )
            }
            free = [c for c in candidates if c not in taken]
            if not free:
                return None
            value = random.choice(free)
            setattr(container, column, value)
            try:
                db.session.commit()
                return value
            except IntegrityError:
                db.session.rollback()
        return None

    @staticmethod
    def allocate_port(container: WhaleContainer, candidates):
        return DBContainer._allocate(container, "port", candidates)

    @staticmethod
    def allocate_subnet(container: WhaleContainer, candidates):
        return DBContainer._allocate(container, "subnet", candidates)


class DBRedirectTemplate:
    @staticmethod
    def get_all_templates():
        return WhaleRedirectTemplate.query.all()

    @staticmethod
    def create_template(name, access_template, frp_template):
        if WhaleRedirectTemplate.query.filter_by(key=name).first():
            return  # already existed
        db.session.add(WhaleRedirectTemplate(name, access_template, frp_template))
        db.session.commit()

    @staticmethod
    def delete_template(name):
        WhaleRedirectTemplate.query.filter_by(key=name).delete()
        db.session.commit()
