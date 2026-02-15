"""Initial schema

Revision ID: 001
Revises: 
Create Date: 2026-02-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Agents table
    op.create_table(
        'agents',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('endpoint', sa.String(500), nullable=False),
        sa.Column('description', sa.Text),
        sa.Column('owner_email', sa.String(255)),
        sa.Column('api_key_hash', sa.String(128), nullable=False),
        sa.Column('trust_score', sa.Float, default=10.0),
        sa.Column('ratings_received', sa.Integer, default=0),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('last_seen', sa.DateTime(timezone=True)),
        sa.Column('is_active', sa.Boolean, default=True),
        sa.Column('verified_email', sa.Boolean, default=False),
        sa.Column('verified_endpoint', sa.Boolean, default=False),
    )
    
    # Capabilities table
    op.create_table(
        'capabilities',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('agent_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('agents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('category', sa.String(50), nullable=False),
        sa.Column('capability_type', sa.String(50), nullable=False),
        sa.Column('actions', postgresql.JSONB),
        sa.Column('input_schema', postgresql.JSONB),
        sa.Column('output_schema', postgresql.JSONB),
        sa.Column('pricing', postgresql.JSONB),
        sa.Column('sla', postgresql.JSONB),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('idx_capabilities_type', 'capabilities', ['category', 'capability_type'])
    op.create_index('idx_capabilities_agent', 'capabilities', ['agent_id'])
    
    # Ratings table
    op.create_table(
        'ratings',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('rater_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('agents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('rated_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('agents.id', ondelete='CASCADE'), nullable=False),
        sa.Column('score', sa.Integer, nullable=False),
        sa.Column('success', sa.Boolean),
        sa.Column('latency_ms', sa.Integer),
        sa.Column('comment', sa.Text),
        sa.Column('capability_used', sa.String(50)),
        sa.Column('transaction_id', sa.String(100)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('idx_ratings_rated', 'ratings', ['rated_id'])
    op.create_index('idx_ratings_rater', 'ratings', ['rater_id'])


def downgrade() -> None:
    op.drop_table('ratings')
    op.drop_table('capabilities')
    op.drop_table('agents')
