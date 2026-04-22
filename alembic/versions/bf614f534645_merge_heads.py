"""merge heads

Revision ID: bf614f534645
Revises: 55b038c07479, 6bd6d4fe8096
Create Date: 2026-04-22 11:14:42.249515

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bf614f534645'
down_revision: Union[str, Sequence[str], None] = ('55b038c07479', '6bd6d4fe8096')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
