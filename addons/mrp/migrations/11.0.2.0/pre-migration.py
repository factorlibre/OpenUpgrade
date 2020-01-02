# Copyright 2018 Eficent <http://www.eficent.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
from openupgradelib import openupgrade

_column_renames = {
    'ir_attachment': [
        ('priority', None),
    ],
    'stock_move': [
        ('quantity_done_store', None),
    ],
}


@openupgrade.migrate(use_env=True)
def migrate(env, version):
    openupgrade.rename_columns(env.cr, _column_renames)
    openupgrade.add_fields(
        env, [
            ('done_move', 'stock.move.line', 'stock_move_line', 'boolean',
             False, 'mrp'),
            ('is_done', 'stock.move', 'stock_move', 'boolean', False,
             'mrp')
        ])
