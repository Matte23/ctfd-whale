"""Allocate ports and subnets in the database, under unique constraints

Ports and subnets used to come from Redis sets that were wiped and rebuilt
at runtime, which could give the same port to two containers. Now they are
stored on the container row, unique:

- port: 0 meant "no port", now NULL (unique allows many NULLs).
  Duplicated ports (left by the old bug) are cleared except on the oldest
  row: only one of those containers was reachable anyway.
- subnet: new column. Existing networks are not backfilled; allocation
  skips subnets overlapping any existing docker network instead.

Revision ID: a91c4e2f7b13
Revises: 8e5d0b6a1c27
Create Date: 2026-11-17

"""
import sqlalchemy as sa

from CTFd.plugins.migrations import get_all_tables, get_columns_for_table

revision = "a91c4e2f7b13"
down_revision = "8e5d0b6a1c27"
branch_labels = None
depends_on = None

TABLE = "whale_container"


def _has_unique(op, column):
    """Whether a unique constraint or unique index covers exactly ``column``.

    db.create_all() creates them unnamed on fresh installs, so match on the
    column, not the name. MySQL reports unique constraints as indexes.
    """
    inspector = sa.inspect(op.get_bind())
    for uc in inspector.get_unique_constraints(TABLE):
        if uc["column_names"] == [column]:
            return True
    for index in inspector.get_indexes(TABLE):
        if index.get("unique") and index["column_names"] == [column]:
            return True
    return False


def upgrade(op=None):
    if TABLE not in get_all_tables(op):
        # not created yet: db.create_all() creates it with the new schema
        return
    conn = op.get_bind()

    conn.execute(sa.text(f"UPDATE {TABLE} SET port = NULL WHERE port = 0"))
    duplicates = conn.execute(
        sa.text(
            f"SELECT port, MIN(id) FROM {TABLE} WHERE port IS NOT NULL "
            "GROUP BY port HAVING COUNT(*) > 1"
        )
    ).fetchall()
    for port, keep_id in duplicates:
        print(
            f"[CTFd Whale] port {port} was given to several containers: "
            f"keeping it on container {keep_id} only"
        )
        conn.execute(
            sa.text(f"UPDATE {TABLE} SET port = NULL WHERE port = :port AND id != :id"),
            {"port": port, "id": keep_id},
        )

    columns = get_columns_for_table(op=op, table_name=TABLE, names_only=True)
    if "subnet" not in columns:
        op.add_column(TABLE, sa.Column("subnet", sa.String(length=64), nullable=True))

    op.alter_column(
        TABLE,
        "port",
        existing_type=sa.Integer(),
        nullable=True,
        server_default=None,
    )
    if not _has_unique(op, "port"):
        op.create_unique_constraint(f"uq_{TABLE}_port", TABLE, ["port"])
    if not _has_unique(op, "subnet"):
        op.create_unique_constraint(f"uq_{TABLE}_subnet", TABLE, ["subnet"])


def downgrade(op=None):
    if TABLE not in get_all_tables(op):
        return
    inspector = sa.inspect(op.get_bind())
    names = {uc["name"] for uc in inspector.get_unique_constraints(TABLE)}
    for column in ("subnet", "port"):
        name = f"uq_{TABLE}_{column}"
        if name in names:
            op.drop_constraint(name, TABLE, type_="unique")
    columns = get_columns_for_table(op=op, table_name=TABLE, names_only=True)
    if "subnet" in columns:
        op.drop_column(TABLE, "subnet")
    conn = op.get_bind()
    conn.execute(sa.text(f"UPDATE {TABLE} SET port = 0 WHERE port IS NULL"))
