"""W2 ask: blocked answers are incidents the desk can see.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_KINDS = (
    "'er', 'safety_unchecked', 'low_confidence', 'advice_request', "
    "'no_availability', 'model_failure', 'ai_booking', 'late_block', 'doc_held', 'doc_quarantine'"
)
NEW_KINDS = OLD_KINDS + ", 'answer_blocked'"


def upgrade() -> None:
    op.drop_constraint("desk_ticket_kind_valid", "desk_ticket", type_="check")
    op.create_check_constraint("desk_ticket_kind_valid", "desk_ticket", f"kind IN ({NEW_KINDS})")


def downgrade() -> None:
    op.drop_constraint("desk_ticket_kind_valid", "desk_ticket", type_="check")
    op.create_check_constraint("desk_ticket_kind_valid", "desk_ticket", f"kind IN ({OLD_KINDS})")
