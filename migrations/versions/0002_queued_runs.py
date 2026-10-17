"""Allow queued evaluation runs created by the API."""

from alembic import op

revision = "0002_queued_runs"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

_QUEUED = "status IN ('pending', 'queued', 'running', 'completed', 'partial')"
_PREVIOUS = "status IN ('pending', 'running', 'completed', 'partial')"


def upgrade() -> None:
    op.drop_constraint("ck_evaluation_runs_status", "evaluation_runs", type_="check")
    op.create_check_constraint("ck_evaluation_runs_status", "evaluation_runs", _QUEUED)


def downgrade() -> None:
    op.drop_constraint("ck_evaluation_runs_status", "evaluation_runs", type_="check")
    op.create_check_constraint("ck_evaluation_runs_status", "evaluation_runs", _PREVIOUS)
