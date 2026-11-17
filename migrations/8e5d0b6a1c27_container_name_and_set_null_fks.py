"""Store the container docker name and use ON DELETE SET NULL

- whale_container.name keeps the docker name / whale_id label
  ("<user_id>-<uuid>"), so the docker resources can still be found and
  removed after the user is deleted. Backfilled for existing rows.
- The user_id, challenge_id and flag_id foreign keys become
  ON DELETE SET NULL: deleting a user, challenge or flag keeps the row,
  and auto-clean still removes the container.

Revision ID: 8e5d0b6a1c27
Revises: 3f1c2a7b9d40
Create Date: 2026-11-17

"""
import sqlalchemy as sa

from CTFd.plugins.migrations import get_all_tables, get_columns_for_table

revision = "8e5d0b6a1c27"
down_revision = "3f1c2a7b9d40"
branch_labels = None
depends_on = None

TABLE = "whale_container"
FOREIGN_KEYS = {
    "user_id": "users",
    "challenge_id": "challenges",
    "flag_id": "flags",
}


def _foreign_keys_by_column(op):
    """Map column name -> reflected foreign keys on that column.

    Constraint names differ per database (e.g. MySQL's whale_container_ibfk_N),
    so they are looked up instead of guessed.
    """
    result = {}
    for fk in sa.inspect(op.get_bind()).get_foreign_keys(TABLE):
        if len(fk["constrained_columns"]) == 1:
            result.setdefault(fk["constrained_columns"][0], []).append(fk)
    return result


def _set_ondelete(op, ondelete):
    fks = _foreign_keys_by_column(op)
    for column, referred_table in FOREIGN_KEYS.items():
        existing = fks.get(column, [])
        wanted = (ondelete or "").upper()
        if any(
            (fk.get("options", {}).get("ondelete") or "").upper() == wanted
            for fk in existing
        ):
            continue
        for fk in existing:
            op.drop_constraint(fk["name"], TABLE, type_="foreignkey")
        op.create_foreign_key(
            f"{TABLE}_{column}_fkey",
            TABLE,
            referred_table,
            [column],
            ["id"],
            ondelete=ondelete,
        )


def upgrade(op=None):
    if TABLE not in get_all_tables(op):
        # not created yet: db.create_all() creates it with the new schema
        return

    columns = get_columns_for_table(op=op, table_name=TABLE, names_only=True)
    if "name" not in columns:
        op.add_column(TABLE, sa.Column("name", sa.String(length=256), nullable=True))

    conn = op.get_bind()
    rows = conn.execute(
        sa.text(f"SELECT id, user_id, uuid FROM {TABLE} WHERE name IS NULL")
    ).fetchall()
    for row_id, user_id, row_uuid in rows:
        conn.execute(
            sa.text(f"UPDATE {TABLE} SET name = :name WHERE id = :id"),
            {"name": f"{user_id}-{row_uuid}", "id": row_id},
        )

    # the columns must accept NULL for ON DELETE SET NULL
    for column in FOREIGN_KEYS:
        op.alter_column(TABLE, column, existing_type=sa.Integer(), nullable=True)

    _set_ondelete(op, "SET NULL")


def downgrade(op=None):
    if TABLE not in get_all_tables(op):
        return
    _set_ondelete(op, None)
    columns = get_columns_for_table(op=op, table_name=TABLE, names_only=True)
    if "name" in columns:
        op.drop_column(TABLE, "name")
