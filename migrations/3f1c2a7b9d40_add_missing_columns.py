"""Add columns missing on installs created by older versions

Tables used to be created only with db.create_all(), which never adds
columns to an existing table. Add every column the current models expect,
skipping the ones that already exist, so this is safe on any install.

Revision ID: 3f1c2a7b9d40
Revises:
Create Date: 2026-11-17

"""
import sqlalchemy as sa

from CTFd.plugins.migrations import get_all_tables, get_columns_for_table

revision = "3f1c2a7b9d40"
down_revision = None
branch_labels = None
depends_on = None

# Defined here instead of imported from models.py: a migration must keep
# describing the schema of its own revision even when the models change.
COLUMNS = {
    "docker_challenges": [
        sa.Column("flag_template", sa.Text(), nullable=True, server_default=""),
        sa.Column("memory_limit", sa.Text(), nullable=True, server_default="128m"),
        sa.Column("cpu_limit", sa.Float(), nullable=True, server_default="0.5"),
        sa.Column("init", sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column(
            "privileged", sa.Boolean(), nullable=True, server_default=sa.false()
        ),
        sa.Column("docker_image", sa.Text(), nullable=True),
        sa.Column("redirect_type", sa.Text(), nullable=True),
        sa.Column("redirect_port", sa.Integer(), nullable=True),
    ],
    "whale_container": [
        sa.Column("renew_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.Integer(), nullable=True, server_default="1"),
        sa.Column("uuid", sa.String(length=256), nullable=True),
        sa.Column("port", sa.Integer(), nullable=True, server_default="0"),
        # the foreign key is added by the next revision
        sa.Column("flag_id", sa.Integer(), nullable=True),
    ],
}


def upgrade(op=None):
    tables = get_all_tables(op)
    for table, columns in COLUMNS.items():
        if table not in tables:
            # not created yet: db.create_all() creates it with every column
            continue
        existing = get_columns_for_table(op=op, table_name=table, names_only=True)
        for column in columns:
            if column.name not in existing:
                op.add_column(table, column)


def downgrade(op=None):
    # These columns are part of the baseline schema: nothing to undo.
    pass
