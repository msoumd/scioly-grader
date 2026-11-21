"""scan reading fields: page of a multi-page upload, straightened image, error text

Scan status also gains "processing" and "failed"; the column is plain text
(non-native enum, no CHECK constraint), so that needs no schema change.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("scans", schema=None) as batch_op:
        batch_op.add_column(sa.Column("page", sa.Integer(), server_default="1", nullable=False))
        batch_op.add_column(sa.Column("warped_path", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("error", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("scans", schema=None) as batch_op:
        batch_op.drop_column("error")
        batch_op.drop_column("warped_path")
        batch_op.drop_column("page")
