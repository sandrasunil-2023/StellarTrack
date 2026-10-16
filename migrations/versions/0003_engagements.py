"""add engagements to time entries

Revision ID: 0003_engagements
Revises: 0002_hours_unrestricted_precision
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_engagements"
down_revision = "0002_hours_unrestricted_precision"
branch_labels = None
depends_on = None

def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "engagements" not in inspector.get_table_names():
        op.create_table(
            "engagements",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("company_id", sa.Integer, sa.ForeignKey("companies.id"), nullable=False),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column("code", sa.String(40), nullable=False, unique=True),
            sa.Column("is_active", sa.Boolean, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    if "engagement_id" not in {column["name"] for column in inspector.get_columns("time_entries")}:
        # SQLite cannot add a foreign-key constraint with ALTER TABLE.  The ORM
        # relationship still enforces the valid-company/engagement pairing.
        op.add_column("time_entries", sa.Column("engagement_id", sa.Integer, nullable=True))
    inspector = sa.inspect(op.get_bind())
    engagement_indexes = {index["name"] for index in inspector.get_indexes("engagements")}
    entry_indexes = {index["name"] for index in inspector.get_indexes("time_entries")}
    if "ix_engagements_company_id" not in engagement_indexes:
        op.create_index("ix_engagements_company_id", "engagements", ["company_id"])
    if "ix_time_entries_engagement_id" not in entry_indexes:
        op.create_index("ix_time_entries_engagement_id", "time_entries", ["engagement_id"])

def downgrade():
    op.drop_index("ix_time_entries_engagement_id", table_name="time_entries")
    op.drop_column("time_entries", "engagement_id")
    op.drop_index("ix_engagements_company_id", table_name="engagements")
    op.drop_table("engagements")
