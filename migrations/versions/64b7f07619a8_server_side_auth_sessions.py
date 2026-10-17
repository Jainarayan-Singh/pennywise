"""server-side auth sessions

Revision ID: 64b7f07619a8
Revises: 5809442c0e0b
Create Date: 2026-10-10 11:01:11.863131

"""
from alembic import op
import sqlalchemy as sa


revision = '64b7f07619a8'
down_revision = '5809442c0e0b'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('auth_sessions',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_auth_sessions_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_auth_sessions'))
    )
    with op.batch_alter_table('auth_sessions', schema=None) as batch_op:
        batch_op.create_index('ix_auth_sessions_user_id', ['user_id'], unique=False)



def downgrade():
    with op.batch_alter_table('auth_sessions', schema=None) as batch_op:
        batch_op.drop_index('ix_auth_sessions_user_id')

    op.drop_table('auth_sessions')
