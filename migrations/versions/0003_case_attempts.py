"""Case claims, run heartbeats, and cancelled runs."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_case_attempts"
down_revision = "0002_queued_runs"
branch_labels = None
depends_on = None

_WITH_CANCELLED = (
    "status IN ('pending', 'queued', 'running', 'completed', 'partial', 'cancelled')"
)
_WITHOUT_CANCELLED = "status IN ('pending', 'queued', 'running', 'completed', 'partial')"


def upgrade() -> None:
    op.drop_constraint("ck_evaluation_runs_status", "evaluation_runs", type_="check")
    op.create_check_constraint("ck_evaluation_runs_status", "evaluation_runs", _WITH_CANCELLED)
    op.add_column("evaluation_runs", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("evaluation_runs", sa.Column("progress", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_table(
        "case_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("evaluation_runs.id"), nullable=False),
        sa.Column("test_case_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("test_cases.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error_category", sa.String(64), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('claimed', 'succeeded', 'execution_error')",
            name="ck_case_attempts_status",
        ),
        sa.UniqueConstraint("run_id", "test_case_id", name="uq_case_attempts_run_case"),
    )


def downgrade() -> None:
    op.drop_table("case_attempts")
    op.drop_column("evaluation_runs", "progress")
    op.drop_column("evaluation_runs", "heartbeat_at")
    op.drop_constraint("ck_evaluation_runs_status", "evaluation_runs", type_="check")
    op.create_check_constraint("ck_evaluation_runs_status", "evaluation_runs", _WITHOUT_CANCELLED)
