"""Release policies and stored experiment comparisons."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_experiments"
down_revision = "0005_safety_labels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "release_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("metric_minimums", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("max_error_rate", sa.Float(), nullable=False),
        sa.Column("latency_budget_ms", sa.Float(), nullable=False),
        sa.Column("safety_required", sa.Boolean(), nullable=False),
        sa.Column("price_per_1k_tokens", sa.Float(), nullable=False),
        sa.Column("max_cost_increase", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("project_id", "name", name="uq_release_policies_project_name"),
    )
    op.create_table(
        "experiments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("baseline_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("evaluation_runs.id"), nullable=False),
        sa.Column("candidate_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("evaluation_runs.id"), nullable=False),
        sa.Column("policy_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("release_policies.id"), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("comparison", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("decision IN ('pass', 'fail', 'review')", name="ck_experiments_decision"),
        sa.UniqueConstraint("project_id", "name", name="uq_experiments_project_name"),
    )


def downgrade() -> None:
    op.drop_table("experiments")
    op.drop_table("release_policies")
