# -*- coding: utf-8 -*-
# Copyright 2018 Tecnativa - Pedro M. Baeza
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from openupgradelib import openupgrade, openupgrade_merge_records

QUANT_MERGE_OPS = {
    # The rest of the values are good with default merge operation
    'in_date': 'min',
    'removal_date': 'max',
}


def merge_quants(env):
    group_list = [
        'product_id', 'package_id', 'lot_id', 'location_id', 'owner_id',
    ]
    StockQuant = env['stock.quant']
    customer_loc_id = env.ref('stock.stock_location_customers').id
    groups = StockQuant.read_group([
        ('location_id', '!=', customer_loc_id)
    ], group_list, group_list, lazy=False)
    for group in groups:
        quants = StockQuant.search(group['__domain'])
        if len(quants) == 1:
            continue
        openupgrade_merge_records.merge_records(
            env, 'stock.quant', quants[1:].ids, quants[0].id, QUANT_MERGE_OPS,
        )
    # Merge customer location quants
    groups = StockQuant.read_group([
        ('location_id', '!=', customer_loc_id)
    ], group_list, group_list, lazy=False)
    for group in groups:
        quants = StockQuant.search(group['__domain'], limit=500)
        while quants and len(quants) > 1:
            openupgrade_merge_records.merge_records(
                env, 'stock.quant', quants[1:].ids, quants[0].id,
                QUANT_MERGE_OPS,
            )
            quants = StockQuant.search(group['__domain'], limit=500)


@openupgrade.migrate(use_env=True)
def migrate(env, version):
    merge_quants(env)
