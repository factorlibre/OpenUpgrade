# Copyright 2020 ForgeFlow <http://www.forgeflow.com>
# Copyright 2023 Tecnativa - Pedro M. Baeza
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from openupgradelib import openupgrade


def _oow_safe_rename_xmlid(cr, old_xmlid, new_xmlid):
    """OOW-FL R106: rename de xmlid a prueba de colisión de clave única.

    `openupgrade.rename_xmlids` hace `UPDATE ir_model_data SET name=new` que
    revienta con duplicate key (module,name) cuando el xmlid NEW ya existe. En
    BLY coexisten el food viejo (_a, p.ej. account_tax_template_p_iva0_ic_a →
    plantilla "Alimentos") y el canónico v13 (_bc → "Bienes corrientes"),
    enlazado a su plantilla por el bloque R60 del pre-migration.sql del step03.
    El fix por SQL (FIX 3 / R106-SQL) no se disparaba de forma fiable dentro del
    `psql --file` de OOW (DELETE 0 pese a condiciones satisfechas); AQUÍ, en el
    cursor de Odoo durante la propia migración, la visibilidad del estado es
    correcta. Si NEW ya existe se borra el xmlid VIEJO (se conserva el canónico,
    que es el que espera account_tax_data.xml de v13); si no, rename normal.
    """
    module_old, name_old = old_xmlid.split(".", 1)
    module_new, name_new = new_xmlid.split(".", 1)
    cr.execute(
        "SELECT 1 FROM ir_model_data WHERE module=%s AND name=%s",
        (module_new, name_new),
    )
    if cr.fetchone():
        cr.execute(
            "DELETE FROM ir_model_data WHERE module=%s AND name=%s",
            (module_old, name_old),
        )
    else:
        openupgrade.rename_xmlids(cr, [(old_xmlid, new_xmlid)])


def set_account_move_number_to_invoice_number(env):
    """l10n_es_account_invoice_sequence introduced different numbering between
    invoices and account moves.

    As long as we have only account_moves in version 13 we have to choose one.
    In case that module is installed we trust the sequence of the invoice, but
    we move previously the move number to the reference for not losing it.

    It also assigns invoice sequences to the journals.
    """
    openupgrade.logged_query(
        env.cr, """
        UPDATE account_move am
        SET ref = regexp_replace(
            ref,
            CONCAT('( |^)', ai.invoice_number, '( |$)'),
            CONCAT('\1', am.name, '\2')
        )
        FROM account_invoice ai
        WHERE ai.move_id = am.id AND ai.invoice_number IS NOT NULL"""
    )
    openupgrade.logged_query(
        env.cr, """
        UPDATE account_move am SET name = ai.invoice_number
        FROM account_invoice ai
        WHERE ai.move_id = am.id AND ai.invoice_number IS NOT NULL"""
    )
    openupgrade.logged_query(
        env.cr, """
        UPDATE account_journal
        SET sequence_id = invoice_sequence_id
        WHERE invoice_sequence_id IS NOT NULL"""
    )
    openupgrade.logged_query(
        env.cr, """
        UPDATE account_journal
        SET refund_sequence_id = refund_inv_sequence_id,
            refund_sequence = True
        WHERE refund_inv_sequence_id IS NOT NULL"""
    )


def rename_food_taxes_and_fiscal_positions_xmlids(env):
    renames = [
        ("account_tax_template_p_iva0_a", "account_tax_template_p_iva0_s_bc"),
        ("account_tax_template_p_iva5_a", "account_tax_template_p_iva5_bc"),
        ("account_tax_template_p_iva0_ic_a", "account_tax_template_p_iva0_ic_bc"),
        ("account_tax_template_p_iva5_ic_a", "account_tax_template_p_iva5_ic_bc"),
        ("account_tax_template_p_iva0_ia", "account_tax_template_p_iva0_ibc"),
        ("account_tax_template_p_iva5_ia", "account_tax_template_p_iva5_ibc"),
        ("account_tax_template_p_req0625", "account_tax_template_p_req062"),
        ("account_tax_template_s_iva0_a", "account_tax_template_s_iva0b"),
        ("account_tax_template_s_iva5_a", "account_tax_template_s_iva5b"),
        ("account_tax_template_s_req0625", "account_tax_template_s_req062"),
        ("fptt_extra_0a", "fptt_extra_0b"),
        ("fptt_extra_5a", "fptt_extra_5b"),
        ("fptt_intra_0a", "fptt_intra_0b"),
        ("fptt_intra_5a", "fptt_intra_5b"),
        ("fptt_reagyp_a_0a_2", "fptt_reagyp_a_4b_4"),
        ("fptt_recargo_0a", "fptt_recargo_0b"),
        ("fptt_recargo_0a_2", "fptt_recargo_0b_2"),
        ("fptt_recargo_5a", "fptt_recargo_5b"),
        ("fptt_recargo_5a_2", "fptt_recargo_5b_2"),
        ("fptt_recargo_buy_0a", "fptt_recargo_buy_0b"),
        ("fptt_recargo_buy_0a_2", "fptt_recargo_buy_0b_2"),
        ("fptt_recargo_buy_5a", "fptt_recargo_buy_5b"),
        ("fptt_recargo_buy_5a_2", "fptt_recargo_buy_5b_2"),
    ]
    companies = env["res.company"].with_context(active_test=False).search([])
    for old, new in renames:
        # OOW-FL R106: rename a prueba de colisión (ver _oow_safe_rename_xmlid)
        _oow_safe_rename_xmlid(env.cr, "l10n_es." + old, "l10n_es." + new)
        for company in companies:
            _oow_safe_rename_xmlid(
                env.cr,
                "l10n_es.%s_" % company.id + old,
                "l10n_es.%s_" % company.id + new,
            )


@openupgrade.migrate()
def migrate(env, version):
    if openupgrade.column_exists(
            env.cr, "account_invoice", "invoice_number"):
        set_account_move_number_to_invoice_number(env)
    rename_food_taxes_and_fiscal_positions_xmlids(env)
