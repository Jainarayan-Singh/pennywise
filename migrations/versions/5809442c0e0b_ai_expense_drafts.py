"""ai expense drafts

Revision ID: 5809442c0e0b
Revises: ef5715979ea7
Create Date: 2026-10-08 10:57:15.640406

"""
from alembic import op
import sqlalchemy as sa


revision = '5809442c0e0b'
down_revision = 'ef5715979ea7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('expense_drafts',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('input_source', sa.String(length=8), nullable=False),
    sa.Column('fields', sa.JSON(), nullable=False),
    sa.Column('pending_field', sa.String(length=24), nullable=True),
    sa.Column('question', sa.String(length=300), nullable=True),
    sa.Column('turn_count', sa.Integer(), nullable=False),
    sa.Column('saved_transaction_id', sa.Uuid(), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("input_source IN ('text', 'voice')", name=op.f('ck_expense_drafts_input_source_valid')),
    sa.CheckConstraint("status IN ('needs_clarification', 'ready_for_review', 'saved', 'cancelled', 'expired')", name=op.f('ck_expense_drafts_status_valid')),
    sa.ForeignKeyConstraint(['saved_transaction_id'], ['transactions.id'], name=op.f('fk_expense_drafts_saved_transaction_id_transactions'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_expense_drafts_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_expense_drafts'))
    )
    with op.batch_alter_table('expense_drafts', schema=None) as batch_op:
        batch_op.create_index('ix_expense_drafts_expires_at', ['expires_at'], unique=False)
        batch_op.create_index('ix_expense_drafts_user_id_status', ['user_id', 'status'], unique=False)



def downgrade():
    with op.batch_alter_table('expense_drafts', schema=None) as batch_op:
        batch_op.drop_index('ix_expense_drafts_user_id_status')
        batch_op.drop_index('ix_expense_drafts_expires_at')

    op.drop_table('expense_drafts')
