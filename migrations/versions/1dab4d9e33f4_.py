"""empty message

Revision ID: 1dab4d9e33f4
Revises: None
Create Date: 2013-11-26 23:11:28.923375

"""

# revision identifiers, used by Alembic.
revision = '1dab4d9e33f4'
down_revision = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

def upgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.create_table('user',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('gh_id', sa.Integer(), nullable=False),
    sa.Column('gh_login', sa.String(length=200), nullable=False),
    sa.Column('gh_name', sa.String(length=200), nullable=False),
    sa.Column('gh_access_token', sa.String(length=100), nullable=False),
    sa.Column('gh_avatar_url', sa.String(length=500), nullable=False),
    sa.Column('repos_last_synchronized_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('gh_id'),
    sa.UniqueConstraint('gh_login')
    )
    op.create_table('project',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=False),
    sa.Column('gh_id', sa.Integer(), nullable=False),
    sa.Column('gh_name', sa.String(length=200), nullable=False),
    sa.Column('gh_full_name', sa.String(length=200), nullable=False),
    sa.Column('gh_login', sa.String(length=200), nullable=False),
    sa.Column('gh_clone_url', sa.String(length=200), nullable=False),
    sa.Column('gh_key_id', sa.Integer(), nullable=False),
    sa.Column('rsa_private_key', sa.Text(), nullable=False),
    sa.Column('rsa_public_key', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('gh_id')
    )
    op.create_table('organization',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('gh_id', sa.Integer(), nullable=False),
    sa.Column('gh_login', sa.String(length=200), nullable=False),
    sa.Column('gh_name', sa.String(length=200), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('user_repository',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('gh_id', sa.Integer(), nullable=False),
    sa.Column('gh_name', sa.String(length=200), nullable=False),
    sa.Column('gh_full_name', sa.String(length=200), nullable=False),
    sa.Column('gh_clone_url', sa.String(length=200), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('build',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('number', sa.Integer(), nullable=False),
    sa.Column('gh_commit_sha', sa.String(length=40), nullable=False),
    sa.Column('gh_commit_author', sa.String(length=200), nullable=False),
    sa.Column('gh_commit_message', sa.String(length=2000), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['project.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('gh_commit_sha')
    )
    op.create_table('project_members',
    sa.Column('project_id', sa.Integer(), nullable=True),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['project.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
    sa.PrimaryKeyConstraint()
    )
    op.create_table('hook',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('gh_id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('build_script', sa.Text(), nullable=False),
    sa.Column('docker_image', sa.String(length=200), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['project.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('organization_repository',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('gh_id', sa.Integer(), nullable=False),
    sa.Column('gh_name', sa.String(length=200), nullable=False),
    sa.Column('gh_full_name', sa.String(length=200), nullable=False),
    sa.Column('gh_clone_url', sa.String(length=200), nullable=False),
    sa.Column('organization_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organization.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('hook_call',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('hook_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('gh_payload', sa.PickleType(), nullable=False),
    sa.ForeignKeyConstraint(['hook_id'], ['hook.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('build_step',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('build_id', sa.Integer(), nullable=False),
    sa.Column('hook_call_id', sa.Integer(), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('finished_at', sa.DateTime(), nullable=True),
    sa.Column('return_code', sa.Integer(), nullable=True),
    sa.Column('stdout', mysql.MEDIUMBLOB(), nullable=True),
    sa.Column('task_uuid', sa.String(length=36), nullable=True),
    sa.ForeignKeyConstraint(['build_id'], ['build.id'], ),
    sa.ForeignKeyConstraint(['hook_call_id'], ['hook_call.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    ### end Alembic commands ###


def downgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('build_step')
    op.drop_table('hook_call')
    op.drop_table('organization_repository')
    op.drop_table('hook')
    op.drop_table('project_members')
    op.drop_table('build')
    op.drop_table('user_repository')
    op.drop_table('organization')
    op.drop_table('project')
    op.drop_table('user')
    ### end Alembic commands ###
