import datetime
import random

from CTFd.models import db
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

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
    def _running():
        # NULL: rows from versions before status was used
        return or_(
            WhaleContainer.status == WhaleContainer.STATUS_RUNNING,
            WhaleContainer.status.is_(None),
        )

    @staticmethod
    def get_current_containers(user_id: int):
        """The running container of the user (not one being removed)."""
        q = db.session.query(WhaleContainer)
        q = q.filter(WhaleContainer.user_id == user_id, DBContainer._running())
        return q.first()

    @staticmethod
    def has_any_container(user_id: int):
        """Whether any row of the user is left, running or being removed."""
        q = db.session.query(WhaleContainer.id)
        q = q.filter(WhaleContainer.user_id == user_id)
        return q.first() is not None

    @staticmethod
    def mark_removing(container: WhaleContainer):
        """Hand the removal over to auto-clean, which retries it."""
        container_id = container.id  # read before the rollback expires it
        db.session.rollback()  # drop whatever the failed removal left pending
        q = db.session.query(WhaleContainer)
        q = q.filter(WhaleContainer.id == container_id)
        q.update(
            {WhaleContainer.status: WhaleContainer.STATUS_REMOVING},
            synchronize_session=False,
        )
        db.session.commit()

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
    def get_containers_to_clean():
        """Expired containers, and those whose removal must be retried."""
        q = db.session.query(WhaleContainer)
        q = q.filter(
            or_(
                WhaleContainer.start_time < _expiry_cutoff(),
                WhaleContainer.status == WhaleContainer.STATUS_REMOVING,
            )
        )
        return q.all()

    @staticmethod
    def _alive_query():
        q = db.session.query(WhaleContainer)
        return q.filter(WhaleContainer.start_time >= _expiry_cutoff())

    @staticmethod
    def get_all_alive_container():
        """Unexpired containers, including those being removed."""
        return DBContainer._alive_query().all()

    @staticmethod
    def get_all_running_container():
        """Unexpired containers that are not being removed: the routed ones."""
        return DBContainer._alive_query().filter(DBContainer._running()).all()

    @staticmethod
    def get_all_container():
        q = db.session.query(WhaleContainer)
        return q.all()

    @staticmethod
    def get_alive_containers_page(page: int, per_page: int):
        """One page of unexpired containers, oldest first (Flask-SQLAlchemy Pagination)."""
        q = WhaleContainer.query.filter(WhaleContainer.start_time >= _expiry_cutoff())
        # the list shows user, challenge and flag: load them with the page
        q = q.options(
            joinedload(WhaleContainer.user),
            joinedload(WhaleContainer.challenge),
            joinedload(WhaleContainer.flag),
        )
        return q.order_by(WhaleContainer.id).paginate(
            page=page, per_page=per_page, error_out=False
        )

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
