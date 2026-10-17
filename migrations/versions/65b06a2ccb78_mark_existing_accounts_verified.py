"""mark existing accounts verified

Sign-up now creates a pending account that can only sign in after the emailed link is used. Accounts that
already exist were created (and could sign in) before that rule, so they are marked as verified on the day
they were created. Data only: no table or column changes, and no rows are removed.

Revision ID: 65b06a2ccb78
Revises: 64b7f07619a8
Create Date: 2026-10-10 12:33:38.859686

"""
from alembic import op

revision = '65b06a2ccb78'
down_revision = '64b7f07619a8'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE users SET email_verified_at = created_at WHERE email_verified_at IS NULL")


def downgrade():
    # Which accounts were verified before this revision is not recorded, so nothing is reverted.
    pass
