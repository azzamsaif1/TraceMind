"""durable repair dispatch queue (separate worker)

Revision ID: 2b7c9d1e4f10
Revises: 15fabd319801
Create Date: 2026-07-30 09:40:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '2b7c9d1e4f10'
down_revision: str | Sequence[str] | None = '15fabd319801'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'repair_queue_items',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('workspace_id', sa.String(length=36), nullable=False),
        sa.Column('recall_event_id', sa.String(length=36), nullable=False),
        sa.Column('asset_ids', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('claimed_by', sa.String(length=120), nullable=True),
        sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('max_attempts', sa.Integer(), nullable=False),
        sa.Column('last_error', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['recall_event_id'], ['recall_events.id'], ),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_repair_queue_items_workspace_id'),
        'repair_queue_items', ['workspace_id'], unique=False,
    )
    op.create_index(
        op.f('ix_repair_queue_items_recall_event_id'),
        'repair_queue_items', ['recall_event_id'], unique=False,
    )
    op.create_index(
        op.f('ix_repair_queue_items_status'),
        'repair_queue_items', ['status'], unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_repair_queue_items_status'), table_name='repair_queue_items')
    op.drop_index(op.f('ix_repair_queue_items_recall_event_id'), table_name='repair_queue_items')
    op.drop_index(op.f('ix_repair_queue_items_workspace_id'), table_name='repair_queue_items')
    op.drop_table('repair_queue_items')
