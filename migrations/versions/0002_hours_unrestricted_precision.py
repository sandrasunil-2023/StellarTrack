"""allow precise fractional hours"""
from alembic import op
import sqlalchemy as sa

revision = "0002_hours_unrestricted_precision"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

def upgrade():
    op.alter_column("time_entries", "hours", existing_type=sa.Numeric(5, 2), type_=sa.Numeric())

def downgrade():
    op.alter_column("time_entries", "hours", existing_type=sa.Numeric(), type_=sa.Numeric(5, 2))
