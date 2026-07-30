"""drop concept_nodes.is_satellite

The column had no producer. It was meant for concepts adjacent to but outside the
subject, created by off-subject ask-anything queries -- but that flow was
deliberately given no path to create a node at all, so the value could only ever
be false. A permanently-false boolean on the public graph schema is noise that
implies a state the app cannot reach.

Revision ID: 8f2c1a4d9b03
Revises: 405edcc14072
Create Date: 2026-07-30 00:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8f2c1a4d9b03"
down_revision: str | None = "405edcc14072"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop the column.

    Batch mode because SQLite cannot drop a column in place and rebuilds the
    table instead; on Postgres this compiles to a plain ``ALTER TABLE``.
    """
    with op.batch_alter_table("concept_nodes") as batch:
        batch.drop_column("is_satellite")


def downgrade() -> None:
    """Restore the column, defaulting to false."""
    with op.batch_alter_table("concept_nodes") as batch:
        batch.add_column(
            sa.Column("is_satellite", sa.Boolean(), nullable=False, server_default=sa.false())
        )
