"""update package table

Revision ID: 6739449c6047
Revises: e029f625004e
Create Date: 2026-04-25 13:42:14.596325

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '6739449c6047'
down_revision: Union[str, Sequence[str], None] = 'e029f625004e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_index(op.f('ix_contact_id'), table_name='contact')
    op.drop_table('contact')

    # Add as nullable first so existing rows don't violate the constraint
    op.add_column('packages', sa.Column('package_type', sa.String(), nullable=True))
    op.add_column('packages', sa.Column('is_free', sa.Boolean(), nullable=True))

    # Backfill existing rows with sensible defaults
    op.execute("UPDATE packages SET package_type = 'general' WHERE package_type IS NULL")
    op.execute("UPDATE packages SET is_free = false WHERE is_free IS NULL")

    # Now enforce NOT NULL
    op.alter_column('packages', 'package_type', nullable=False)
    op.alter_column('packages', 'is_free', nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('packages', 'is_free')
    op.drop_column('packages', 'package_type')
    op.create_table('contact',
    sa.Column('id', sa.INTEGER(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.INTEGER(), autoincrement=False, nullable=False),
    sa.Column('full_name', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('email', sa.VARCHAR(), autoincrement=False, nullable=False),
    sa.Column('phone', sa.VARCHAR(), autoincrement=False, nullable=True),
    sa.Column('message', sa.TEXT(), autoincrement=False, nullable=False),
    sa.Column('created_at', postgresql.TIMESTAMP(), autoincrement=False, nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('contact_user_id_fkey')),
    sa.PrimaryKeyConstraint('id', name=op.f('contact_pkey'))
    )
    op.create_index(op.f('ix_contact_id'), 'contact', ['id'], unique=False)