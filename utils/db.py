"""Database access for WhaleContainer rows, including port and subnet allocation."""

import datetime
import random

from CTFd.models import db
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from ..models import WhaleContainer
from .config import whale_config

# Retries when another worker takes the same port/subnet at the same time.
ALLOCATION_ATTEMPTS = 10


def _expiry_cutoff():
    """Containers started before this are expired."""
    timeout = int(whale_config("docker_timeout"))
    return datetime.datetime.utcnow() - datetime.timedelta(seconds=timeout)


def create_container(user_id: int, challenge_id: int, flag_id: int):
    container = WhaleContainer(
        user_id=user_id, challenge_id=challenge_id, flag_id=flag_id
    )
    db.session.add(container)
    db.session.commit()

    return container


def _running():
    # NULL: rows from versions before status was used
    return or_(
        WhaleContainer.status == WhaleContainer.STATUS_RUNNING,
        WhaleContainer.status.is_(None),
    )


def get_running_container(user_id: int):
    """The running container of the user (not one being removed)."""
    q = db.session.query(WhaleContainer)
    q = q.filter(WhaleContainer.user_id == user_id, _running())
    return q.first()


def has_any_container(user_id: int):
    """Whether any row of the user is left, running or being removed."""
    q = db.session.query(WhaleContainer.id)
    q = q.filter(WhaleContainer.user_id == user_id)
    return q.first() is not None


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


def get_container(container_id: int):
    return WhaleContainer.query.filter_by(id=container_id).first()


def delete_container(container: WhaleContainer):
    # delete by id, not by user: removing one record must never drop
    # another container's record and orphan its docker resources
    q = db.session.query(WhaleContainer)
    q = q.filter(WhaleContainer.id == container.id)
    q.delete()
    db.session.commit()


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


def _alive_query():
    q = db.session.query(WhaleContainer)
    return q.filter(WhaleContainer.start_time >= _expiry_cutoff())


def get_running_containers():
    """Unexpired containers that are not being removed: the routed ones."""
    return _alive_query().filter(_running()).all()


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


def count_alive_containers():
    return _alive_query().count()


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
            for (value,) in db.session.query(attribute).filter(attribute.isnot(None))
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


def allocate_port(container: WhaleContainer, candidates):
    return _allocate(container, "port", candidates)


def allocate_subnet(container: WhaleContainer, candidates):
    return _allocate(container, "subnet", candidates)
