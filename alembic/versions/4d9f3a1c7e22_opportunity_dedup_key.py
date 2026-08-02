"""opportunity deterministic identity (dedup_key)

Revision ID: 4d9f3a1c7e22
Revises: 3c8e2f5a9b21
Create Date: 2026-08-02 09:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '4d9f3a1c7e22'
down_revision: str | Sequence[str] | None = '3c8e2f5a9b21'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'opportunities',
        sa.Column('dedup_key', sa.String(length=64), nullable=False, server_default=''),
    )
    op.create_index(
        op.f('ix_opportunities_dedup_key'),
        'opportunities', ['dedup_key'], unique=False,
    )
    op.create_unique_constraint(
        'uq_opportunity_dedup', 'opportunities', ['recall_event_id', 'dedup_key'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('uq_opportunity_dedup', 'opportunities', type_='unique')
    op.drop_index(op.f('ix_opportunities_dedup_key'), table_name='opportunities')
    op.drop_column('opportunities', 'dedup_key')
