"""Add earned verification fields, remove billing

Revision ID: 002
Revises: 001
Create Date: 2026-02-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add earned verification fields
    op.add_column('agents', sa.Column('is_verified', sa.Boolean(), nullable=True, server_default='false'))
    op.add_column('agents', sa.Column('days_above_threshold', sa.Integer(), nullable=True, server_default='0'))
    op.add_column('agents', sa.Column('last_trust_check', sa.DateTime(), nullable=True))
    
    # Remove billing fields (may fail if already gone, that's OK)
    try:
        op.drop_column('agents', 'subscription_tier')
    except:
        pass
    try:
        op.drop_column('agents', 'stripe_customer_id')
    except:
        pass
    try:
        op.drop_column('agents', 'stripe_subscription_id')
    except:
        pass
    try:
        op.drop_column('agents', 'verified_email')
    except:
        pass


def downgrade() -> None:
    op.drop_column('agents', 'is_verified')
    op.drop_column('agents', 'days_above_threshold')
    op.drop_column('agents', 'last_trust_check')
    op.add_column('agents', sa.Column('subscription_tier', sa.String(20), nullable=True))
    op.add_column('agents', sa.Column('stripe_customer_id', sa.String(100), nullable=True))
    op.add_column('agents', sa.Column('stripe_subscription_id', sa.String(100), nullable=True))
    op.add_column('agents', sa.Column('verified_email', sa.Boolean(), nullable=True))
