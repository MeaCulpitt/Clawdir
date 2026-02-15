"""Add ownership verification fields

Revision ID: 002
Revises: 001
Create Date: 2026-02-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add ownership verification columns
    op.add_column('agents', sa.Column('verified_ownership', sa.Boolean(), nullable=True, server_default='false'))
    op.add_column('agents', sa.Column('ownership_verified_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('agents', 'ownership_verified_at')
    op.drop_column('agents', 'verified_ownership')
