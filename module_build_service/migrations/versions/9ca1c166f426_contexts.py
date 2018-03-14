"""Adds the context columns

Revision ID: 9ca1c166f426
Revises: f5b1c5203cce
Create Date: 2018-01-09 16:55:43.416631

"""

# revision identifiers, used by Alembic.
revision = '9ca1c166f426'
down_revision = 'f5b1c5203cce'

from alembic import op
import sqlalchemy as sa

# Data migration imports
from module_build_service import Modulemd
import hashlib
import json
from collections import OrderedDict


modulebuild = sa.Table(
    'module_builds',
    sa.MetaData(),
    sa.Column('id', sa.Integer, primary_key=True),
    sa.Column('modulemd', sa.String()),
    sa.Column('build_context', sa.String()),
    sa.Column('runtime_context', sa.String()),
)


def upgrade():
    connection = op.get_bind()

    op.add_column('module_builds', sa.Column('build_context', sa.String()))
    op.add_column('module_builds', sa.Column('runtime_context', sa.String()))

    # Determine what the contexts should be based on the modulemd
    for build in connection.execute(modulebuild.select()):
        if not build.modulemd:
            continue
        try:
            mmd = Modulemd.Module().new_from_string(build.modulemd)
            mmd.upgrade()
        except Exception:
            # If the modulemd isn't parseable then skip this build
            continue

        mbs_xmd = mmd.get_xmd().get('mbs', {})
        contexts = {}
        for property_name in ['buildrequires', 'requires']:
            # It's possible this module build was built before MBS filled out xmd or before MBS
            # filled out the requires in xmd. We also have to use keys because GLib.Variant
            # doesn't support `in` directly.
            if property_name not in mbs_xmd.keys():
                break
            mmd_property = getattr(mmd.get_dependencies()[0], 'get_{0}'.format(property_name))()
            if set(mbs_xmd[property_name].keys()) != set(mmd_property.keys()):
                break
            mmd_formatted_property = {
                dep: info['ref'] for dep, info in mbs_xmd[property_name].items()}
            property_json = json.dumps(OrderedDict(sorted(mmd_formatted_property.items())))
            contexts[property_name] = hashlib.sha1(property_json).hexdigest()

        # Update the database now
        if len(contexts) == 2:
            connection.execute(
                modulebuild.update().where(modulebuild.c.id == build.id).values(
                    build_context=contexts['buildrequires'], runtime_context=contexts['requires']))
        elif 'buildrequires' in contexts:
            connection.execute(
                modulebuild.update().where(modulebuild.c.id == build.id).values(
                    build_context=contexts['buildrequires']))
        elif 'requires' in contexts:
            connection.execute(
                modulebuild.update().where(modulebuild.c.id == build.id).values(
                    runtime_context=contexts['requires']))


def downgrade():
    with op.batch_alter_table('module_builds') as b:
        b.drop_column('build_context')
        b.drop_column('runtime_context')
