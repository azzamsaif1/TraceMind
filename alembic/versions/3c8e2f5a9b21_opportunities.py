"""verified opportunities

Revision ID: 3c8e2f5a9b21
Revises: 2b7c9d1e4f10
Create Date: 2026-07-31 09:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '3c8e2f5a9b21'
down_revision: str | Sequence[str] | None = '2b7c9d1e4f10'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'opportunities',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('workspace_id', sa.String(length=36), nullable=False),
        sa.Column('recall_event_id', sa.String(length=36), nullable=False),
        sa.Column('kind', sa.String(length=60), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('rationale', sa.Text(), nullable=False),
        sa.Column('evidence', sa.JSON(), nullable=False),
        sa.Column('operations', sa.JSON(), nullable=False),
        sa.Column('native_operations', sa.Integer(), nullable=False),
        sa.Column('generative_operations', sa.Integer(), nullable=False),
        sa.Column('blocked_operations', sa.Integer(), nullable=False),
        sa.Column('feasibility_state', sa.String(length=20), nullable=False),
        sa.Column('executed_operations', sa.Integer(), nullable=False),
        sa.Column('result', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['recall_event_id'], ['recall_events.id'], ),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_opportunities_workspace_id'),
        'opportunities', ['workspace_id'], unique=False,
    )
    op.create_index(
        op.f('ix_opportunities_recall_event_id'),
        'opportunities', ['recall_event_id'], unique=False,
    )
    op.create_index(
        op.f('ix_opportunities_status'),
        'opportunities', ['status'], unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_opportunities_status'), table_name='opportunities')
    op.drop_index(op.f('ix_opportunities_recall_event_id'), table_name='opportunities')
    op.drop_index(op.f('ix_opportunities_workspace_id'), table_name='opportunities')
    op.drop_table('opportunities')
