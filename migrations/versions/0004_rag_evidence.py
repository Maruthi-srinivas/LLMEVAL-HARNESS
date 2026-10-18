"""Retrieved documents, citations, and relevant-document labels."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_rag_evidence"
down_revision = "0003_case_attempts"
branch_labels = None
depends_on = None

_JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.add_column(
        "test_cases",
        sa.Column("relevant_document_ids", _JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.add_column("test_cases", sa.Column("retrieved_context", _JSONB, nullable=True))
    op.add_column(
        "test_cases",
        sa.Column("citations", _JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.add_column("case_results", sa.Column("retrieved_documents", _JSONB, nullable=True))
    op.add_column("case_results", sa.Column("citations", _JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("case_results", "citations")
    op.drop_column("case_results", "retrieved_documents")
    op.drop_column("test_cases", "citations")
    op.drop_column("test_cases", "retrieved_context")
    op.drop_column("test_cases", "relevant_document_ids")
