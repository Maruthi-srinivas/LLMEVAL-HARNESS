"""Safety policy labels and human calibration labels."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_safety_labels"
down_revision = "0004_rag_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("test_cases", sa.Column("expected_policy", sa.String(16), nullable=True))
    op.add_column(
        "test_cases",
        sa.Column("human_labels", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_check_constraint(
        "ck_test_cases_expected_policy",
        "test_cases",
        "expected_policy IS NULL OR expected_policy IN ('refuse', 'answer')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_test_cases_expected_policy", "test_cases", type_="check")
    op.drop_column("test_cases", "human_labels")
    op.drop_column("test_cases", "expected_policy")
