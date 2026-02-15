"""Initial schema

Revision ID: 001
Revises: 
Create Date: 2026-02-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create agents table
    op.create_table('agents',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('endpoint', sa.String(length=500), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('owner_email', sa.String(length=255), nullable=False),
        sa.Column('api_key_hash', sa.String(length=128), nullable=False),
        sa.Column('trust_score', sa.Float(), nullable=True),
        sa.Column('ratings_received', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('last_seen', sa.DateTime(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('verified_email', sa.Boolean(), nullable=True),
        sa.Column('verified_endpoint', sa.Boolean(), nullable=True),
        sa.Column('last_verification', sa.DateTime(), nullable=True),
        sa.Column('last_latency_ms', sa.Integer(), nullable=True),
        sa.Column('subscription_tier', sa.String(length=20), nullable=True),
        sa.Column('stripe_customer_id', sa.String(length=100), nullable=True),
        sa.Column('stripe_subscription_id', sa.String(length=100), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    op.create_index(op.f('ix_agents_id'), 'agents', ['id'], unique=False)
    op.create_index(op.f('ix_agents_name'), 'agents', ['name'], unique=True)

    # Create capabilities table
    op.create_table('capabilities',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('agent_id', sa.UUID(), nullable=True),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('capability_type', sa.String(length=100), nullable=False),
        sa.Column('actions', sa.JSON(), nullable=True),
        sa.Column('input_schema', sa.JSON(), nullable=True),
        sa.Column('output_schema', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_capabilities_id'), 'capabilities', ['id'], unique=False)

    # Create ratings table
    op.create_table('ratings',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('rater_id', sa.UUID(), nullable=True),
        sa.Column('rated_id', sa.UUID(), nullable=True),
        sa.Column('score', sa.Integer(), nullable=False),
        sa.Column('success', sa.Boolean(), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['rated_id'], ['agents.id'], ),
        sa.ForeignKeyConstraint(['rater_id'], ['agents.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ratings_id'), 'ratings', ['id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_ratings_id'), table_name='ratings')
    op.drop_table('ratings')
    op.drop_index(op.f('ix_capabilities_id'), table_name='capabilities')
    op.drop_table('capabilities')
    op.drop_index(op.f('ix_agents_name'), table_name='agents')
    op.drop_index(op.f('ix_agents_id'), table_name='agents')
    op.drop_table('agents')
