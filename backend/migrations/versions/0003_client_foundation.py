"""Add durable clients and associate analyses.

Revision ID: 0003_client_foundation
Revises: 0002_analysis_review_fields
Create Date: 2026-08-21
"""

from collections.abc import Sequence
from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa


revision: str = "0003_client_foundation"
down_revision: str | Sequence[str] | None = "0002_analysis_review_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FK_NAME = "fk_analyses_client_id_clients"


def upgrade() -> None:
    op.create_table(
        "clients",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("external_reference", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "external_reference", name="uq_clients_external_reference"
        ),
    )
    op.create_index("ix_clients_status", "clients", ["status"], unique=False)

    with op.batch_alter_table("analyses") as batch_op:
        batch_op.add_column(sa.Column("client_id", sa.String(36), nullable=True))
        batch_op.create_foreign_key(
            FK_NAME,
            "clients",
            ["client_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index("ix_analyses_client_id", "analyses", ["client_id"], unique=False)

    connection = op.get_bind()
    historical = connection.execute(
        sa.text(
            """
            SELECT client_reference, MIN(created_at) AS first_created_at
            FROM analyses
            WHERE client_reference IS NOT NULL
              AND TRIM(client_reference) <> ''
            GROUP BY client_reference
            """
        )
    ).mappings()
    for row in historical:
        reference = row["client_reference"]
        client_id = str(uuid5(NAMESPACE_URL, f"client-reference:{reference}"))
        timestamp = row["first_created_at"]
        connection.execute(
            sa.text(
                """
                INSERT INTO clients (
                    id, display_name, external_reference, status,
                    created_at, updated_at
                ) VALUES (
                    :id, :reference, :reference, 'active', :created_at, :created_at
                )
                """
            ),
            {"id": client_id, "reference": reference, "created_at": timestamp},
        )
        connection.execute(
            sa.text(
                """
                UPDATE analyses SET client_id = :client_id
                WHERE client_reference = :reference
                """
            ),
            {"client_id": client_id, "reference": reference},
        )


def downgrade() -> None:
    op.drop_index("ix_analyses_client_id", table_name="analyses")
    with op.batch_alter_table("analyses") as batch_op:
        batch_op.drop_constraint(FK_NAME, type_="foreignkey")
        batch_op.drop_column("client_id")
    op.drop_index("ix_clients_status", table_name="clients")
    op.drop_table("clients")
