"""Drop the unused whale_config and whale_redirect_template tables

- whale_config: the plugin stores its settings in CTFd's config table.
- whale_redirect_template: access info comes from the router (frp/trp),
  for admins and players alike.

Revision ID: d71e3b9a0c52
Revises: c4d2a8f1e690
Create Date: 2026-11-18

"""

import sqlalchemy as sa
from CTFd.plugins.migrations import get_all_tables

revision = "d71e3b9a0c52"
down_revision = "c4d2a8f1e690"
branch_labels = None
depends_on = None


def upgrade(op=None):
    tables = get_all_tables(op)
    for table in ("whale_config", "whale_redirect_template"):
        if table in tables:
            op.drop_table(table)


def downgrade(op=None):
    # Recreated empty: their old contents are not restored.
    tables = get_all_tables(op)
    if "whale_config" not in tables:
        op.create_table(
            "whale_config",
            sa.Column("key", sa.String(length=128), primary_key=True),
            sa.Column("value", sa.Text(), nullable=True),
        )
    if "whale_redirect_template" not in tables:
        op.create_table(
            "whale_redirect_template",
            sa.Column("key", sa.String(length=20), primary_key=True),
            sa.Column("frp_template", sa.Text(), nullable=True),
            sa.Column("access_template", sa.Text(), nullable=True),
        )
