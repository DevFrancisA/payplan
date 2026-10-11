"""Initial schema: plans, installments, payments, idempotency keys.

Revision ID: 0001
Revises:
Create Date: 2026-09-01
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("principal", sa.Numeric(12, 2), nullable=False),
        sa.Column("apr", sa.Numeric(6, 3), nullable=False),
        sa.Column("frequency", sa.String(16), nullable=False),
        sa.Column("installment_count", sa.Integer, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("total_interest", sa.Numeric(12, 2), nullable=False),
        sa.Column("total_cost", sa.Numeric(12, 2), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("principal > 0", name="ck_plans_principal_positive"),
        sa.CheckConstraint("installment_count BETWEEN 1 AND 60", name="ck_plans_installment_count"),
        sa.CheckConstraint("apr >= 0", name="ck_plans_apr_non_negative"),
    )

    op.create_table(
        "installments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "plan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("number", sa.Integer, nullable=False),
        sa.Column("due_date", sa.Date, nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("principal", sa.Numeric(12, 2), nullable=False),
        sa.Column("interest", sa.Numeric(12, 2), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("plan_id", "number", name="uq_installments_plan_number"),
        sa.CheckConstraint("amount > 0", name="ck_installments_amount_positive"),
    )

    op.create_table(
        "payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "installment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("installments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(255), nullable=False, unique=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("payment_method", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("gateway_attempts", sa.Integer, nullable=False),
        sa.Column("gateway_reference", sa.String(64), unique=True),
        sa.Column("failure_code", sa.String(64)),
        sa.Column("failure_message", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_payments_installment_id", "payments", ["installment_id"])
    op.create_index(
        "uq_payments_one_active_per_installment",
        "payments",
        ["installment_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'succeeded')"),
    )

    op.create_table(
        "idempotency_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("scope", sa.String(64), nullable=False),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True)),
        sa.Column("response_status", sa.Integer),
        sa.Column("response_body", postgresql.JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("scope", "key", name="uq_idempotency_scope_key"),
    )


def downgrade() -> None:
    op.drop_table("idempotency_keys")
    op.drop_index("uq_payments_one_active_per_installment", table_name="payments")
    op.drop_index("ix_payments_installment_id", table_name="payments")
    op.drop_table("payments")
    op.drop_table("installments")
    op.drop_table("plans")
