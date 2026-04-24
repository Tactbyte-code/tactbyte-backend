# alembic/versions/41c7349dd39f_add_packages_table.py
"""add packages table

Revision ID: 41c7349dd39f
Revises: 4d884c0f4d4d
Create Date: 2026-04-23 17:42:19.789259
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '41c7349dd39f'
down_revision: Union[str, Sequence[str], None] = '4d884c0f4d4d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table('packages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=False),
        sa.Column('features', sa.JSON(), nullable=False),
        sa.Column('monthly_price_id', sa.Integer(), nullable=True),
        sa.Column('annual_price_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['monthly_price_id'], ['prices.id']),
        sa.ForeignKeyConstraint(['annual_price_id'], ['prices.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_packages_id'), 'packages', ['id'], unique=False)

def downgrade() -> None:
    op.drop_index(op.f('ix_packages_id'), table_name='packages')
    op.drop_table('packages')