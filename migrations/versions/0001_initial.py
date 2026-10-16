"""initial schema"""
from alembic import op
import sqlalchemy as sa
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None
def upgrade():
    op.create_table("users",sa.Column("id",sa.Integer,primary_key=True),sa.Column("full_name",sa.String(160),nullable=False),sa.Column("username",sa.String(80),nullable=False,unique=True),sa.Column("password_hash",sa.String(255),nullable=False),sa.Column("role",sa.Enum("ADMIN","EMPLOYEE",name="role"),nullable=False),sa.Column("is_active",sa.Boolean,nullable=False),sa.Column("must_change_password",sa.Boolean,nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False))
    op.create_table("companies",sa.Column("id",sa.Integer,primary_key=True),sa.Column("name",sa.String(160),nullable=False,unique=True),sa.Column("code",sa.String(40),unique=True),sa.Column("is_active",sa.Boolean,nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False))
    op.create_table("time_entries",sa.Column("id",sa.Integer,primary_key=True),sa.Column("employee_id",sa.Integer,sa.ForeignKey("users.id"),nullable=False),sa.Column("company_id",sa.Integer,sa.ForeignKey("companies.id"),nullable=False),sa.Column("work_date",sa.Date,nullable=False),sa.Column("hours",sa.Numeric,nullable=False),sa.Column("description",sa.Text,nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("updated_at",sa.DateTime(timezone=True),nullable=False))
    op.create_table("audit_logs",sa.Column("id",sa.Integer,primary_key=True),sa.Column("actor_id",sa.Integer,sa.ForeignKey("users.id")),sa.Column("action",sa.String(60),nullable=False),sa.Column("entity_type",sa.String(60),nullable=False),sa.Column("entity_id",sa.Integer,nullable=False),sa.Column("timestamp",sa.DateTime(timezone=True),nullable=False),sa.Column("before_data",sa.Text),sa.Column("after_data",sa.Text))
    op.create_index("ix_time_entries_employee_date","time_entries",["employee_id","work_date"]);op.create_index("ix_audit_logs_timestamp","audit_logs",["timestamp"])
def downgrade():
    op.drop_table("audit_logs");op.drop_table("time_entries");op.drop_table("companies");op.drop_table("users")
