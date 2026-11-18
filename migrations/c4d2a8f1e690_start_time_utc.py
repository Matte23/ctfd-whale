"""Store whale_container.start_time in UTC

start_time used to be written in the server's local time while CTFd (and
its "isoformat" template filter) treats stored times as UTC. Shift existing
rows by the server's UTC offset at the time the migration runs. Rows only
live for docker_timeout, so a daylight-saving change since a row was
written doesn't matter in practice.

Revision ID: c4d2a8f1e690
Revises: a91c4e2f7b13
Create Date: 2026-11-18

"""

import datetime

import sqlalchemy as sa
from CTFd.plugins.migrations import get_all_tables

revision = "c4d2a8f1e690"
down_revision = "a91c4e2f7b13"
branch_labels = None
depends_on = None

TABLE = "whale_container"


def _utc_offset():
    """Local time minus UTC, rounded to the minute."""
    offset = datetime.datetime.now() - datetime.datetime.utcnow()
    return datetime.timedelta(minutes=round(offset.total_seconds() / 60))


def _shift(op, delta):
    if TABLE not in get_all_tables(op) or not delta:
        return
    conn = op.get_bind()
    rows = conn.execute(sa.text(f"SELECT id, start_time FROM {TABLE}")).fetchall()
    for row_id, start_time in rows:
        if start_time is None:
            continue
        if isinstance(start_time, str):  # SQLite returns text
            start_time = datetime.datetime.fromisoformat(start_time)
        conn.execute(
            sa.text(f"UPDATE {TABLE} SET start_time = :t WHERE id = :id"),
            {"t": start_time + delta, "id": row_id},
        )


def upgrade(op=None):
    _shift(op, -_utc_offset())


def downgrade(op=None):
    _shift(op, _utc_offset())
