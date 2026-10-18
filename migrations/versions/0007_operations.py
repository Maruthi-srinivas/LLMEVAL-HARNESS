"""Outbox, Kafka inbox, and workspace token budgets."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_operations"
down_revision = "0006_experiments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workspaces", sa.Column("token_budget", sa.Float(), nullable=True))
    op.create_table(
        "outbox_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("evaluation_runs.id"), nullable=False),
        sa.Column("event_name", sa.String(100), nullable=False),
        sa.Column("event_version", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "kafka_inbox",
        sa.Column("event_id", sa.String(64), primary_key=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("kafka_inbox")
    op.drop_table("outbox_events")
    op.drop_column("workspaces", "token_budget")
