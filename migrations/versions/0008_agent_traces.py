"""Agent traces and human review requests."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008_agent_traces"
down_revision = "0007_operations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "test_cases",
        sa.Column("allowed_tools", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
    )
    op.add_column("test_cases", sa.Column("goal", sa.Text(), nullable=True))
    op.add_column("test_cases", sa.Column("constraints", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("test_cases", sa.Column("expected_tools", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("case_results", sa.Column("trace", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_table(
        "review_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("case_result_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("case_results.id"), nullable=False),
        sa.Column("dataset_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("dataset_versions.id"), nullable=False),
        sa.Column("requested_labels", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'approved')", name="ck_review_requests_status"),
    )


def downgrade() -> None:
    op.drop_table("review_requests")
    op.drop_column("case_results", "trace")
    op.drop_column("test_cases", "expected_tools")
    op.drop_column("test_cases", "constraints")
    op.drop_column("test_cases", "goal")
    op.drop_column("test_cases", "allowed_tools")
