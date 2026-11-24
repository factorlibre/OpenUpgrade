# Copyright 2021 ForgeFlow S.L.  <https://www.forgeflow.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
import logging

from openupgradelib import openupgrade

from odoo.tools.translate import _

_logger = logging.getLogger(__name__)


def _create_hooks(env):
    def _check_fiscalyear_lock_date(self):
        return True

    def _check_tax_lock_date(self):
        return True

    def _check_reconciliation(self):
        return True

    # create hooks
    _check_fiscalyear_lock_date._original_method = type(
        env["account.move"]
    )._check_fiscalyear_lock_date
    type(env["account.move"])._check_fiscalyear_lock_date = _check_fiscalyear_lock_date
    _check_tax_lock_date._original_method = type(
        env["account.move.line"]
    )._check_tax_lock_date
    type(env["account.move.line"])._check_tax_lock_date = _check_tax_lock_date
    _check_reconciliation._original_method = type(
        env["account.move.line"]
    )._check_reconciliation
    type(env["account.move.line"])._check_reconciliation = _check_reconciliation


def _delete_hooks(env):
    # delete hooks
    type(env["account.move"])._check_fiscalyear_lock_date = type(
        env["account.move"]
    )._check_fiscalyear_lock_date._original_method
    type(env["account.move.line"])._check_tax_lock_date = type(
        env["account.move.line"]
    )._check_tax_lock_date._original_method
    type(env["account.move.line"])._check_reconciliation = type(
        env["account.move.line"]
    )._check_reconciliation._original_method


def fill_account_journal_posted_before(env):
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE account_move
        SET posted_before = TRUE
        WHERE state = 'posted'""",
    )


def fill_code_prefix_end_field(env):
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE account_group
        SET code_prefix_end = code_prefix_start
        """,
    )


def fill_default_account_id_field(env):
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE account_journal
        SET default_account_id = {0}
        WHERE {0} = {1} OR ({0} IS NOT NULL AND {1} IS NULL);
        UPDATE account_journal
        SET default_account_id = {1}
        WHERE {0} IS NULL AND {1} IS NOT NULL
        """.format(
            openupgrade.get_legacy_name("default_credit_account_id"),
            openupgrade.get_legacy_name("default_debit_account_id"),
        ),
    )


def fill_payment_id_and_statement_line_id_fields(env):
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE account_move_line aml
        SET payment_id = am.payment_id
        FROM account_move am
        WHERE am.id = aml.move_id AND am.payment_id IS NOT NULL
            AND aml.payment_id IS NULL
        """,
    )
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE account_move_line aml
        SET statement_line_id = am.statement_line_id
        FROM account_move am
        WHERE am.id = aml.move_id AND am.statement_line_id IS NOT NULL
            AND aml.statement_line_id IS NULL
        """,
    )


def fill_partial_reconcile_debit_and_credit_amounts(env):
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE account_partial_reconcile
        SET debit_amount_currency = COALESCE(NULLIF(amount_currency, 0.0), amount),
            debit_currency_id = COALESCE(currency_id, debit_currency_id)
        WHERE debit_amount_currency IS NULL
       """,
    )
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE account_partial_reconcile
        SET credit_amount_currency = COALESCE(NULLIF(amount_currency, 0.0), amount),
            credit_currency_id = COALESCE(currency_id, credit_currency_id)
        WHERE credit_amount_currency IS NULL
       """,
    )


def create_account_reconcile_model_lines(env):
    openupgrade.logged_query(
        env.cr,
        """
        INSERT INTO account_reconcile_model_line (model_id, company_id,
            sequence, account_id, journal_id, label, amount_type,
            force_tax_included, amount, amount_string, analytic_account_id,
            create_uid, create_date, write_uid, write_date)
        SELECT id, company_id, 10, account_id, journal_id, label,
            amount_type, force_tax_included,
            CASE WHEN amount_type = 'regex' THEN 0 ELSE amount END as amount,
            CASE WHEN amount_type = 'regex' THEN amount_from_label_regex
                ELSE amount || '' END as amount_string,
            analytic_account_id, create_uid, create_date, write_uid, write_date
        FROM (
            SELECT arm.* FROM account_reconcile_model arm
            LEFT JOIN ir_model_data imd ON (
                imd.model = 'account.reconcile.model' AND imd.res_id = arm.id)
            WHERE imd.id IS NULL) arm1
        WHERE rule_type != 'invoice_matching' OR (rule_type = 'invoice_matching'
            AND match_total_amount AND match_total_amount_param < 100.0)
        UNION ALL
        SELECT id, company_id, 20, second_account_id, second_journal_id,
            second_label, second_amount_type, force_second_tax_included,
            CASE WHEN second_amount_type = 'regex' THEN 0
                ELSE second_amount END as amount,
            CASE WHEN second_amount_type = 'regex' THEN second_amount_from_label_regex
                ELSE second_amount || '' END as amount_string,
            second_analytic_account_id, create_uid, create_date, write_uid, write_date
        FROM (
            SELECT arm.* FROM account_reconcile_model arm
            LEFT JOIN ir_model_data imd ON (
                imd.model = 'account.reconcile.model' AND imd.res_id = arm.id)
            WHERE imd.id IS NULL) arm2
        WHERE has_second_line AND (rule_type != 'invoice_matching' OR (
            rule_type = 'invoice_matching' AND match_total_amount
            AND match_total_amount_param < 100.0))
        ORDER BY id""",
    )
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE account_reconcile_model_analytic_tag_rel rel
        SET account_reconcile_model_line_id = arml.id
        FROM account_reconcile_model_line arml
        WHERE arml.model_id = rel.account_reconcile_model_id""",
    )
    openupgrade.logged_query(
        env.cr,
        """
        DELETE FROM account_reconcile_model_analytic_tag_rel
        WHERE account_reconcile_model_line_id IS NULL""",
    )
    openupgrade.logged_query(
        env.cr,
        """
        INSERT INTO account_reconcile_model_analytic_tag_rel (
            account_reconcile_model_line_id, account_analytic_tag_id)
        SELECT arml.id, rel.account_analytic_tag_id
        FROM account_reconcile_model_second_analytic_tag_rel rel
        JOIN account_reconcile_model_line arml
            ON rel.account_reconcile_model_id = arml.model_id""",
    )
    openupgrade.logged_query(
        env.cr,
        """
        INSERT INTO account_reconcile_model_line_account_tax_rel (
            account_reconcile_model_line_id, account_tax_id)
        SELECT arml.id, rel.account_tax_id
        FROM account_reconcile_model_account_tax_rel rel
        JOIN account_reconcile_model_line arml
            ON rel.account_reconcile_model_id = arml.model_id""",
    )
    openupgrade.logged_query(
        env.cr,
        """
        INSERT INTO account_reconcile_model_line_account_tax_rel (
            account_reconcile_model_line_id, account_tax_id)
        SELECT arml.id, rel.account_tax_id
        FROM account_reconcile_model_account_tax_bis_rel rel
        JOIN account_reconcile_model_line arml
            ON rel.account_reconcile_model_id = arml.model_id""",
    )


def create_account_reconcile_model_template_lines(env):
    openupgrade.logged_query(
        env.cr,
        """
        INSERT INTO account_reconcile_model_line_template (model_id,
            sequence, account_id, label, amount_type,
            force_tax_included, amount_string,
            create_uid, create_date, write_uid, write_date)
        SELECT id, 10, account_id, label,
            amount_type, force_tax_included,
            CASE WHEN amount_type = 'regex' THEN amount_from_label_regex
                ELSE amount::varchar END as amount_string,
            create_uid, create_date, write_uid, write_date
        FROM (
            SELECT armt.* FROM account_reconcile_model_template armt
            LEFT JOIN ir_model_data imd ON (
                imd.model = 'account.reconcile.model.template'
                    AND imd.res_id = armt.id)
            WHERE imd.id IS NULL) armt1
        WHERE rule_type != 'invoice_matching' OR (rule_type = 'invoice_matching'
            AND match_total_amount AND match_total_amount_param < 100.0)
        UNION ALL
        SELECT id, 20, second_account_id,
            second_label, second_amount_type, force_second_tax_included,
            CASE WHEN second_amount_type = 'regex' THEN second_amount_from_label_regex
                ELSE second_amount::varchar END as amount_string,
            create_uid, create_date, write_uid, write_date
        FROM (
            SELECT armt.* FROM account_reconcile_model_template armt
            LEFT JOIN ir_model_data imd ON (
                imd.model = 'account.reconcile.model.template'
                    AND imd.res_id = armt.id)
            WHERE imd.id IS NULL) armt2
        WHERE has_second_line AND (rule_type != 'invoice_matching' OR (
            rule_type = 'invoice_matching' AND match_total_amount
            AND match_total_amount_param < 100.0))
        ORDER BY id""",
    )
    openupgrade.logged_query(
        env.cr,
        """
        INSERT INTO account_reconcile_model_line_template_account_tax_template_rel (
            account_reconcile_model_line_template_id, account_tax_template_id)
        SELECT armlt.id, rel.account_tax_template_id
        FROM account_reconcile_model_template_account_tax_template_rel rel
        JOIN account_reconcile_model_line_template armlt
            ON rel.account_reconcile_model_template_id = armlt.model_id""",
    )
    openupgrade.logged_query(
        env.cr,
        """
        INSERT INTO account_reconcile_model_line_template_account_tax_template_rel (
            account_reconcile_model_line_template_id, account_tax_template_id)
        SELECT armlt.id, rel.account_tax_template_id
        FROM account_reconcile_model_tmpl_account_tax_bis_rel rel
        JOIN account_reconcile_model_line_template armlt
            ON rel.account_reconcile_model_template_id = armlt.model_id""",
    )


def create_account_tax_report_lines(env):
    openupgrade.logged_query(
        env.cr,
        """
        ALTER TABLE account_tax_report
        ADD COLUMN root_line_id integer""",
    )
    openupgrade.logged_query(
        env.cr,
        """
        INSERT INTO account_tax_report (name, country_id, root_line_id,
            create_uid, create_date, write_uid, write_date)
        SELECT name, country_id, id, create_uid, create_date, write_uid, write_date
        FROM account_tax_report_line
        WHERE parent_id IS NULL
        """,
    )
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE account_tax_report_line atrl
        SET report_id = atr.id
        FROM account_tax_report atr
        WHERE atr.root_line_id = atrl.id
        """,
    )
    while True:
        openupgrade.logged_query(
            env.cr,
            """
            UPDATE account_tax_report_line atrl
            SET report_id = atrl2.report_id
            FROM account_tax_report_line atrl2
            WHERE atrl.parent_id = atrl2.id AND atrl.report_id IS NULL
            RETURNING atrl.id""",
        )
        if not env.cr.fetchone():
            break


def post_statements(env):
    """These 2 inconsistent use cases require to put the statement as posted."""
    # Confirmed statements that have unreconciled items
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE account_bank_statement bst
        SET state = 'posted'
        FROM account_bank_statement_line bstl
        WHERE bst.state = 'confirm' AND bstl.statement_id = bst.id
            AND bstl.is_reconciled IS DISTINCT FROM TRUE
        """,
    )
    # New statements with reconciled items
    openupgrade.logged_query(
        env.cr,
        """SELECT bst.id FROM account_bank_statement bst
        JOIN account_bank_statement_line bstl ON bstl.statement_id = bst.id
        WHERE bst.state = 'open' AND bstl.is_reconciled IS TRUE
        """,
    )
    stmt_ids = list({x[0] for x in env.cr.fetchall()})
    # calling .button_post() on all statements together fails with:
    # File "/odoo_env/src/odoo/addons/account/models/account_move.py", line 1842, in _check_unique_sequence_number  # noqa: B950
    #     raise ValidationError(_('Posted journal entry must have an unique sequence number per company.\n'  # noqa: B950
    # odoo.exceptions.ValidationError: Posted journal entry must have an unique sequence number per company.  # noqa: B950
    # Problematic numbers: 198/100, 198/100, 198/104, 198/104, 198/101, 198/101, 198/102, 198/103, 198/103, 198/102  # noqa: B950
    # instead, call it one by one.
    stmts = env["account.bank.statement"].browse(stmt_ids)
    for stmt in stmts:
        stmt.button_post()


def pass_bank_statement_line_note_to_journal_entry_narration(env):
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE account_move am
        SET narration = CASE
            WHEN char_length(COALESCE(am.narration, '')) = 0 THEN absl.note
            ELSE am.narration || ' ' || absl.note END
        FROM account_bank_statement_line absl
        WHERE absl.move_id = am.id AND char_length(COALESCE(absl.note, '')) > 0
        """,
    )


def pass_payment_to_journal_entry_narration(env):
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE account_move am
        SET narration = CASE
            WHEN char_length(COALESCE(am.narration, '')) = 0 THEN ap.communication
            ELSE am.narration || ' ' || ap.communication END
        FROM account_payment ap
        WHERE ap.move_id = am.id AND char_length(COALESCE(ap.communication, '')) > 0
        """,
    )


def fill_company_account_cash_basis_base_account_id(env):
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE account_chart_template chart
        SET property_cash_basis_base_account_id = att.cash_basis_base_account_id
        FROM account_tax_template att
        WHERE att.chart_template_id = chart.id
            AND att.cash_basis_base_account_id IS NOT NULL
        """,
    )
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE res_company rc
        SET account_cash_basis_base_account_id = at.cash_basis_base_account_id
        FROM account_tax at
        WHERE at.company_id = rc.id
            AND at.cash_basis_base_account_id IS NOT NULL
        """,
    )


def fill_company_account_journal_suspense_account_id(env):
    companies = env["res.company"].search([("chart_template_id", "!=", False)])
    for company in companies:
        chart = company.chart_template_id
        account = chart._create_liquidity_journal_suspense_account(
            company, chart.code_digits
        )
        company.account_journal_suspense_account_id = account
    journals = (
        env["account.journal"]
        .with_context(active_test=False)
        .search([("type", "in", ("bank", "cash")), ("company_id", "in", companies.ids)])
    )
    journals._compute_suspense_account_id()


def fill_statement_lines_with_no_move(env):
    # OOW-BATCHED-STL-V2 (BLY 2026-06-03, R24): version por LOTES.
    # La original creaba el move de cada linea via ORM uno a uno (create +
    # _synchronize_to_moves + write) a ~1/seg. Esta version produce el MISMO
    # resultado (move 'entry' + 2 apuntes con los MISMOS
    # _prepare_move_line_default_vals()) en 3 fases batcheadas:
    #   A) crear los moves VACIOS en lotes,
    #   B) enlazar move_id en las lineas (UPDATE masivo) -> los related
    #      journal_id/date de la linea ya resuelven (dependen de move_id;
    #      por eso NO se pueden calcular los vals antes de crear el move),
    #   C) calcular vals con _prepare_move_line_default_vals() y crear los
    #      apuntes con account.move.line.create() en lotes.
    # AUTOVALIDACION: las primeras VALIDATE_N lineas van por el camino
    # original (ground truth) y se comparan campo a campo contra los vals
    # del batch; cualquier discrepancia ABORTA (rollback limpio del modulo).
    VALIDATE_N = 200
    BATCH = 500

    legacy_date = openupgrade.get_legacy_name("date")

    def _fetch_pending():
        env.cr.execute(
            """
            SELECT id, %s, company_id
            FROM account_bank_statement_line
            WHERE move_id IS NULL
            ORDER BY id"""
            % legacy_date
        )
        return env.cr.fetchall()

    rows = _fetch_pending()
    stl_dates = {r[0]: r[1] for r in rows}
    companies = {r[2] for r in rows}
    total = len(rows)
    _logger.info("OOW-BATCHED-STL-V2: %s statement lines sin move", total)
    if not total:
        return

    # fail-fast: diarios con lineas pendientes y SIN cuenta por defecto ->
    # el apunte de liquidez saldria con account_id NULL (constraint
    # account_move_line_check_accountable_required_fields). Mejor abortar ya
    # con la lista clara que reventar en el lote N (vease FIX3 del
    # pre-migration.sql del step 04 para el data-fix de BLY).
    env.cr.execute(
        """
        SELECT DISTINCT aj.id, aj.name
        FROM account_bank_statement_line absl
        JOIN account_bank_statement abs ON abs.id = absl.statement_id
        JOIN account_journal aj ON aj.id = abs.journal_id
        WHERE absl.move_id IS NULL AND aj.default_account_id IS NULL"""
    )
    bad_journals = env.cr.fetchall()
    if bad_journals:
        raise Exception(
            "OOW-BATCHED-STL-V2: diarios sin default_account_id con lineas"
            " pendientes (configurar antes de migrar): %s" % bad_journals
        )

    deprecated = env["account.account"].search(
        [("deprecated", "=", True), ("company_id", "in", list(companies))]
    )
    deprecated.deprecated = False

    def _move_header_vals(st_line):
        journal = st_line.statement_id.journal_id
        company_currency = journal.company_id.currency_id
        journal_currency = (
            journal.currency_id
            if journal.currency_id and journal.currency_id != company_currency
            else False
        )
        return {
            "name": "/",
            "date": stl_dates[st_line.id],
            "statement_line_id": st_line.id,
            "move_type": "entry",
            "journal_id": journal.id,
            "company_id": journal.company_id.id,
            "currency_id": (
                st_line.foreign_currency_id or journal_currency or company_currency
            ).id,
            "partner_id": st_line.partner_id.id,
        }

    def _normalize_vals(vals_list):
        res = []
        for lv in vals_list:
            res.append((
                lv.get("account_id"),
                round(lv.get("debit") or 0.0, 6),
                round(lv.get("credit") or 0.0, 6),
                round(lv.get("amount_currency") or 0.0, 6),
                lv.get("currency_id") or False,
                lv.get("partner_id") or False,
            ))
        return sorted(res)

    def _normalize_move(move):
        res = []
        for line in move.line_ids:
            res.append((
                line.account_id.id,
                round(line.debit or 0.0, 6),
                round(line.credit or 0.0, 6),
                round(line.amount_currency or 0.0, 6),
                line.currency_id.id or False,
                line.partner_id.id or False,
            ))
        return sorted(res)

    try:
        # ---- fase 1: camino ORIGINAL en las primeras VALIDATE_N (ground truth)
        validate_ids = [r[0] for r in rows[:VALIDATE_N]]
        st_lines = env["account.bank.statement.line"].browse(validate_ids)
        for st_line in st_lines.with_context(
            check_move_validity=False, tracking_disable=True
        ):
            move = env["account.move"].create(
                {
                    "name": "/",
                    "date": stl_dates[st_line.id],
                    "statement_line_id": st_line.id,
                    "move_type": "entry",
                    "journal_id": st_line.statement_id.journal_id.id,
                    "company_id": st_line.statement_id.company_id.id,
                    "currency_id": st_line.statement_id.journal_id.currency_id.id
                    or st_line.statement_id.company_id.currency_id.id,
                }
            )
            st_line.move_id = move
            try:
                st_line._synchronize_to_moves(
                    [
                        "payment_ref",
                        "amount",
                        "amount_currency",
                        "foreign_currency_id",
                        "currency_id",
                        "partner_id",
                    ]
                )
            except Exception as e:
                _logger.error("Failed for statement line with id %s: %s", st_line.id, e)
                raise
            to_write = {
                "line_ids": [
                    (
                        0,
                        0,
                        st_line._prepare_move_line_default_vals(
                            counterpart_account_id=False
                        )[0],
                    )
                ]
            }
            st_line.move_id.with_context(
                skip_account_move_synchronization=True
            ).write(to_write)

        # ---- comparar: lo que produjo el original vs lo que produciria el
        # batch (los mismos _prepare_* sobre lineas que YA tienen move).
        mismatches = 0
        for st_line in env["account.bank.statement.line"].browse(validate_ids):
            move = st_line.move_id
            header = _move_header_vals(st_line)
            batch_vals = st_line._prepare_move_line_default_vals()
            header_ok = (
                move.journal_id.id == header["journal_id"]
                and (move.partner_id.id or False) == (header["partner_id"] or False)
                and move.currency_id.id == header["currency_id"]
                and str(move.date) == str(header["date"])
            )
            exp_lines = _normalize_vals(batch_vals)
            got_lines = _normalize_move(move)
            if not header_ok or exp_lines != got_lines:
                mismatches += 1
                _logger.error(
                    "OOW-BATCHED-STL-V2 MISMATCH stl=%s header_ok=%s exp=%s got=%s",
                    st_line.id, header_ok, exp_lines, got_lines,
                )
        if mismatches:
            raise Exception(
                "OOW-BATCHED-STL-V2: validacion fallida (%s/%s) -> abort"
                % (mismatches, len(validate_ids))
            )
        _logger.info(
            "OOW-BATCHED-STL-V2: validacion OK en %s lineas", len(validate_ids)
        )
        env["base"].flush()

        # ---- fase 2A: crear moves VACIOS en lotes para el resto
        pending = [r[0] for r in _fetch_pending()]
        _logger.info("OOW-BATCHED-STL-V2: creando %s moves vacios", len(pending))
        Move = env["account.move"].with_context(
            check_move_validity=False,
            tracking_disable=True,
            skip_account_move_synchronization=True,
        )
        for start in range(0, len(pending), BATCH):
            chunk_ids = pending[start:start + BATCH]
            chunk = env["account.bank.statement.line"].browse(chunk_ids)
            Move.create([_move_header_vals(sl) for sl in chunk])
            env["base"].flush()
            env.cache.invalidate()

        # ---- fase 2B: enlazar move_id en bloque
        env.cr.execute(
            """
            UPDATE account_bank_statement_line absl
            SET move_id = am.id
            FROM account_move am
            WHERE am.statement_line_id = absl.id AND absl.move_id IS NULL"""
        )
        _logger.info("OOW-BATCHED-STL-V2: move_id enlazado en %s lineas", env.cr.rowcount)
        env.cache.invalidate()

        # ---- fase 2C: crear los apuntes en lotes con los vals canonicos
        AML = env["account.move.line"].with_context(
            check_move_validity=False,
            tracking_disable=True,
            skip_account_move_synchronization=True,
        )
        done = 0
        for start in range(0, len(pending), BATCH):
            chunk_ids = pending[start:start + BATCH]
            chunk = env["account.bank.statement.line"].browse(chunk_ids).with_context(
                check_move_validity=False, tracking_disable=True
            )
            vals_list = []
            for sl in chunk:
                vals_list.extend(sl._prepare_move_line_default_vals())
            AML.create(vals_list)
            done += len(chunk_ids)
            if done % 5000 < BATCH or done == len(pending):
                _logger.info("OOW-BATCHED-STL-V2: apuntes %s/%s lineas", done, len(pending))
            env["base"].flush()
            env.cache.invalidate()
    finally:
        deprecated.deprecated = True

    openupgrade.logged_query(
        env.cr,
        """
        UPDATE account_move am
        SET partner_bank_id = absl.bank_account_id
        FROM account_bank_statement_line absl
        WHERE am.statement_line_id = absl.id AND am.partner_bank_id IS NULL
            AND absl.bank_account_id IS NOT NULL""",
    )


def fill_account_journal_payment_credit_debit_account_id(env):
    journals = (
        env["account.journal"]
        .with_context(active_test=False)
        .search([("type", "in", ("bank", "cash"))])
    )
    current_assets_type = env.ref("account.data_account_type_current_assets")
    for journal in journals:
        random_account = env["account.account"].search(
            [("company_id", "=", journal.company_id.id)], limit=1
        )
        digits = len(random_account.code) if random_account else 6
        if journal.type == "bank":
            liquidity_account_prefix = journal.company_id.bank_account_code_prefix or ""
        else:
            liquidity_account_prefix = (
                journal.company_id.cash_account_code_prefix
                or journal.company_id.bank_account_code_prefix
                or ""
            )
        journal.payment_debit_account_id = env["account.account"].create(
            {
                "name": _("Outstanding Receipts"),
                "code": env["account.account"]._search_new_account_code(
                    journal.company_id, digits, liquidity_account_prefix
                ),
                "reconcile": True,
                "user_type_id": current_assets_type.id,
                "company_id": journal.company_id.id,
            }
        )
        journal.payment_credit_account_id = (
            env["account.account"]
            .create(
                {
                    "name": _("Outstanding Payments"),
                    "code": env["account.account"]._search_new_account_code(
                        journal.company_id, digits, liquidity_account_prefix
                    ),
                    "reconcile": True,
                    "user_type_id": current_assets_type.id,
                    "company_id": journal.company_id.id,
                }
            )
            .id
        )


def create_new_counterpart_account_payment_transfer(env):
    # Create new counterpart payment with account payment transfer
    openupgrade.logged_query(
        env.cr,
        """
        INSERT INTO account_payment (move_id, is_internal_transfer, partner_type,
            payment_type,
            amount, currency_id,
            destination_account_id, partner_id,
            create_uid, create_date, write_uid, write_date)
        SELECT move.id, true, ap.partner_type,
            CASE
            WHEN journal.id = ap.destination_journal_id THEN 'inbound' ELSE 'outbound'
            END,
            ap.amount, ap.currency_id,
            ap.destination_account_id, ap.partner_id,
            ap.create_uid, ap.create_date, ap.write_uid, ap.write_date
        FROM account_payment ap
        JOIN account_move move
            ON (move.payment_id = ap.id AND move.id != ap.move_id)
        JOIN account_journal journal ON journal.id = move.journal_id
        WHERE ap.payment_type = 'transfer'
        """,
    )


def map_account_payment_transfer(env):
    # map payment_type from transfer to 'inbound'/'outbound'
    # and set is_internal_transfer as true on account payment transfer
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE account_payment ap
        SET is_internal_transfer = true, payment_type = 'outbound'
        WHERE ap.payment_type = 'transfer'
        """,
    )


def fill_account_payment_reconciliation(env):
    openupgrade.logged_query(
        env.cr,
        """
            UPDATE account_payment ap
            SET is_reconciled = True,
                is_matched = True
            FROM res_currency rcur
            WHERE rcur.id = ap.currency_id
                AND ROUND(ap.amount, rcur.decimal_places) = 0
        """,
    )
    openupgrade.logged_query(
        env.cr,
        """
            WITH matched_payments as (
                SELECT ap.id,
                    CASE WHEN aj.default_account_id IS NOT NULL
                            AND bool_or(aj.default_account_id = aml.account_id)
                        THEN TRUE
                    ELSE
                        ROUND(SUM(CASE
                            WHEN aml.account_id in (
                                aj.default_account_id,
                                aj.payment_debit_account_id,
                                aj.payment_credit_account_id
                            ) THEN CASE
                                WHEN rc.currency_id = rcur.id THEN aml.amount_residual
                                ELSE aml.amount_residual_currency END
                            ELSE 0 END
                        ), rcur.decimal_places) = 0
                    END as is_matched,
                    ROUND(
                        SUM(CASE
                            WHEN NOT aa.reconcile THEN 0
                            WHEN aml.account_id not in (
                                aj.default_account_id,
                                aj.payment_debit_account_id,
                                aj.payment_credit_account_id
                            ) THEN CASE
                                WHEN rc.currency_id = rcur.id THEN aml.amount_residual
                                ELSE aml.amount_residual_currency END
                            ELSE 0 END
                        ),
                        rcur.decimal_places
                    ) = 0 as is_reconciled
                FROM account_payment ap
                JOIN account_move am ON am.id = ap.move_id
                JOIN account_move_line aml ON aml.move_id = am.id
                JOIN account_account aa ON aa.id = aml.account_id
                JOIN res_company rc ON rc.id = am.company_id
                JOIN account_journal aj ON aj.id = am.journal_id
                JOIN res_currency rcur ON rcur.id = ap.currency_id
                GROUP BY ap.id, rcur.decimal_places, aj.default_account_id
            )
            UPDATE account_payment ap
            SET is_matched = matched_payments.is_matched,
                is_reconciled = matched_payments.is_reconciled
            FROM matched_payments
            where ap.id = matched_payments.id
        """,
    )


def fill_account_payment_with_no_move(env):
    p_data = {}
    p_dates_by_company = {}
    env.cr.execute(
        """
        SELECT ap.id, ap.%s, ap.%s, ap.%s, ap.state, aj.company_id
        FROM account_payment ap
        JOIN account_journal aj ON ap.%s = aj.id
        WHERE ap.move_id IS NULL
        """
        % (
            openupgrade.get_legacy_name("journal_id"),
            openupgrade.get_legacy_name("name"),
            openupgrade.get_legacy_name("payment_date"),
            openupgrade.get_legacy_name("journal_id"),
        )
    )
    for (
        p_id,
        p_journal_id,
        p_name,
        p_payment_date,
        p_state,
        p_company,
    ) in env.cr.fetchall():
        p_data[p_id] = {
            "journal_id": p_journal_id,
            "name": p_name,
            # Switch to cancel when no linked move, but the payment was validated
            "state": "cancelled" if p_state not in {"draft", "cancelled"} else p_state,
            "payment_date": p_payment_date,
        }
        if p_company in p_dates_by_company:
            p_dates_by_company[p_company] = min(
                p_payment_date, p_dates_by_company[p_company]
            )
        else:
            p_dates_by_company[p_company] = p_payment_date
    payments = env["account.payment"].browse(list(p_data.keys()))
    for payment in payments.with_context(
        check_move_validity=False, tracking_disable=True
    ):
        journal = env["account.journal"].browse(p_data[payment.id]["journal_id"])
        move = env["account.move"].create(
            {
                "name": "/",
                # map old payment's state to move's state:
                # draft -> draft, cancelled -> cancel
                "state": "cancel"
                if p_data[payment.id]["state"] == "cancelled"
                else "draft",
                "date": p_data[payment.id]["payment_date"],
                "payment_id": payment.id,
                "move_type": "entry",
                "journal_id": journal.id,
                "company_id": journal.company_id.id,
                "currency_id": journal.currency_id.id
                or journal.company_id.currency_id.id,
            }
        )
        payment.move_id = move
        deprecated_accounts = env["account.account"].search(
            [("deprecated", "=", True), ("company_id", "=", payment.company_id.id)]
        )
        deprecated_accounts.deprecated = False
        try:
            payment._synchronize_to_moves(
                [
                    "date",
                    "amount",
                    "payment_type",
                    "partner_type",
                    "payment_reference",
                    "is_internal_transfer",
                    "currency_id",
                    "partner_id",
                    "destination_account_id",
                    "partner_bank_id",
                    "journal_id",
                ]
            )
        except Exception as e:
            _logger.error("Failed for payment with id %s: %s", payment.id, e)
            raise
        deprecated_accounts.deprecated = True


def try_delete_noupdate_records(env):
    openupgrade.delete_records_safely_by_xml_id(
        env,
        [
            "account.sequence_payment_customer_invoice",
            "account.sequence_payment_customer_refund",
            "account.sequence_payment_supplier_invoice",
            "account.sequence_payment_supplier_refund",
            "account.sequence_payment_transfer",
        ],
    )


def fill_account_move_line_amounts(env):
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE account_move_line aml
        SET amount_currency = aml.debit-aml.credit
        FROM account_move am
        JOIN res_company rc ON am.company_id = rc.id
        WHERE aml.currency_id = rc.currency_id AND
            aml.move_id = am.id AND
            aml.debit + aml.credit > 0 AND (
                aml.amount_currency = 0 OR aml.amount_currency IS NULL)""",
    )


def fill_account_move_line_date(env):
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE account_move_line aml
        SET date = COALESCE(am.date, aml.create_date::date)
        FROM account_move am
        WHERE aml.move_id = am.id AND aml.date IS NULL""",
    )


def fill_account_bank_statement_line_reconciliation(env):
    openupgrade.logged_query(
        env.cr,
        """
        WITH absl_residual AS (
            SELECT absl.id,
                CASE
                    WHEN am.to_check
                        AND absl.foreign_currency_id IS NOT NULL
                        THEN -absl.amount_currency
                    WHEN am.to_check THEN -absl.amount
                    ELSE SUM(
                        CASE
                            WHEN aa.reconcile AND aa.id != aj.default_account_id
                                AND aa.id = aj.suspense_account_id
                                THEN aml.amount_residual_currency
                            WHEN aa.id != aj.default_account_id
                                AND aa.id = aj.suspense_account_id
                                THEN aml.amount_currency
                            ELSE 0.
                        END
                    )
                END as amount_residual,
                MIN(CASE
                    WHEN aa.id != aj.default_account_id
                        AND aa.id = aj.suspense_account_id
                        THEN aml.currency_id
                    ELSE NULL END) as suspense_currency_id
            FROM account_bank_statement_line absl
                JOIN account_move am ON am.id = absl.move_id
                JOIN account_move_line aml ON aml.move_id = am.id
                JOIN account_journal aj ON aj.id = am.journal_id
                JOIN account_account aa ON aa.id = aml.account_id
                JOIN res_company rc ON rc.id = aj.company_id
            GROUP BY
                absl.id,
                am.to_check,
                absl.foreign_currency_id,
                absl.amount_currency,
                absl.amount
        )
        UPDATE account_bank_statement_line absl
        SET amount_residual = absl_residual.amount_residual,
            is_reconciled = CASE
                WHEN suspense_currency_id IS NULL THEN TRUE
                ELSE ROUND(absl_residual.amount_residual, rcur.decimal_places) = 0
            END
        FROM absl_residual
            LEFT JOIN res_currency rcur ON rcur.id = absl_residual.suspense_currency_id
        WHERE absl_residual.id = absl.id
        """,
    )


def update_payment_state_partial(env):
    """As the 'Partially paid' didn't exist before, invoices with this condition are
    still marked as 'Not paid', so we should update them as if they were partially paid
    in this new version.
    """
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE account_move
        SET payment_state='partial'
        WHERE move_type IN ('out_invoice', 'out_refund', 'in_invoice', 'in_refund')
            AND amount_residual > 0
            AND amount_residual < amount_total
            AND payment_state != 'partial'
        """,
    )


def cash_rounding_fields_to_company_dependent(env):
    """Usually for such cases, openupgrade.convert_to_company_dependent() should
    normally be used, but that function does not seem to support converting
    a field to company-dependent without changing its name at the same time.
    moreover, it stores boolean values even when they are false (what odoo
    does not), and it creates values for all companies, which does not make
    sense when a record is linked to a particular company only.
    """
    field_names = ["profit_account_id"]
    if openupgrade.column_exists(env.cr, "account_cash_rounding", "loss_account_id"):
        # loss_account_id comes from pos_cash_rounding
        field_names += ["loss_account_id"]
    for field_name in field_names:
        field_id = (env.ref(f"account.field_account_cash_rounding__{field_name}").id,)
        # this many2one property stores its value in the value_reference column
        openupgrade.logged_query(
            env.cr,
            f"""
            insert into ir_property (
                company_id, fields_id, value_reference, name, res_id, type
            )
            select
                aa.company_id,
                %(field_id)s,
                'account.account,' || acr.{field_name},
                '{field_name}',
                'account.cash.rounding,' || acr.id,
                'many2one'
            from account_cash_rounding acr
            join account_account aa ON acr.profit_account_id = aa.id
            where
                acr.{field_name} is not null
            order by acr.id
            """,
            {"field_id": field_id},
        )
        if field_name == "loss_account_id":
            # for account.cash.rounding records that are not linked to
            # a company (i.e, to a profit_account_id), create an
            # ir.property record for each company.
            openupgrade.logged_query(
                env.cr,
                """
                insert into ir_property (
                    company_id,
                    fields_id,
                    value_reference,
                    name,
                    res_id,
                    type
                )
                select
                    rc.id,
                    %(field_id)s,
                    'account.account,' || acr.loss_account_id,
                    'loss_account_id',
                    'account.cash.rounding,' || acr.id,
                    'many2one'
                from account_cash_rounding acr
                inner join res_company as rc on
                    acr.profit_account_id is null
                    and acr.loss_account_id is not null
                order by acr.id, rc.id
                """,
                {"field_id": field_id},
            )


@openupgrade.migrate()
def migrate(env, version):
    # OOW-PREMIG-SAFETY (BLY 2026-06-03): red de seguridad de R21/R22. En un run
    # el pre-migration.sql de oow se aplico de forma incompleta (psql sin
    # ON_ERROR_STOP y salida swallowed por exec_run -> un fallo en una sentencia
    # es invisible). Re-aplicamos aqui las correcciones criticas de forma
    # idempotente justo antes de que account las necesite. logged_query deja
    # los conteos visibles en el log.
    openupgrade.logged_query(env.cr, """
        UPDATE ir_model_data d SET res_id = sub.pid FROM (
            SELECT p.id AS pid FROM ir_property p
            JOIN ir_model_fields f ON f.id = p.fields_id
            WHERE f.model='res.partner' AND f.name='trust'
              AND p.company_id IS NULL AND p.res_id IS NULL
            ORDER BY p.id LIMIT 1) sub
        WHERE d.module='account' AND d.name='default_followup_trust'
          AND d.res_id IS DISTINCT FROM sub.pid""")
    openupgrade.logged_query(env.cr, """
        UPDATE ir_model_data d SET res_id = sub.pid FROM (
            SELECT p.id AS pid FROM ir_property p
            JOIN ir_model_fields f ON f.id = p.fields_id
            WHERE f.model='res.partner' AND f.name='property_stock_customer'
              AND p.company_id IS NULL AND p.res_id IS NULL
            ORDER BY p.id LIMIT 1) sub
        WHERE d.module='stock' AND d.name='property_stock_customer'
          AND d.res_id IS DISTINCT FROM sub.pid""")
    openupgrade.logged_query(env.cr, """
        UPDATE account_reconcile_model
        SET rule_type = 'invoice_matching'
        WHERE rule_type IN ('writeoff_button', 'writeoff_suggestion')
          AND account_id IS NULL""")
    # OOW perf-fix (BLY 2026-06-02): indexar los FK usados como reverse-o2m
    # (move.payment_ids / move.statement_line_ids) en los bucles/recompute por-move.
    # Sin estos indices cada acceso es un seq-scan de account_payment / 
    # account_bank_statement_line -> el post-migration tardaba dias. Idempotente.
    if openupgrade.column_exists(env.cr, "account_payment", "move_id"):
        env.cr.execute("CREATE INDEX IF NOT EXISTS account_payment_move_id_idx ON account_payment (move_id)")
    if openupgrade.column_exists(env.cr, "account_bank_statement_line", "move_id"):
        env.cr.execute("CREATE INDEX IF NOT EXISTS account_bank_statement_line_move_id_idx ON account_bank_statement_line (move_id)")
    cash_rounding_fields_to_company_dependent(env)
    fill_account_journal_posted_before(env)
    fill_code_prefix_end_field(env)
    fill_default_account_id_field(env)
    fill_payment_id_and_statement_line_id_fields(env)
    fill_partial_reconcile_debit_and_credit_amounts(env)
    create_account_reconcile_model_lines(env)
    create_account_reconcile_model_template_lines(env)
    create_account_tax_report_lines(env)
    pass_bank_statement_line_note_to_journal_entry_narration(env)
    pass_payment_to_journal_entry_narration(env)
    fill_company_account_cash_basis_base_account_id(env)
    fill_account_move_line_amounts(env)
    fill_account_move_line_date(env)
    openupgrade.load_data(env.cr, "account", "14.0.1.1/noupdate_changes.xml")
    try_delete_noupdate_records(env)
    _create_hooks(env)
    fill_company_account_journal_suspense_account_id(env)
    fill_statement_lines_with_no_move(env)
    fill_account_journal_payment_credit_debit_account_id(env)
    create_new_counterpart_account_payment_transfer(env)
    map_account_payment_transfer(env)
    fill_account_payment_reconciliation(env)
    fill_account_payment_with_no_move(env)
    fill_account_bank_statement_line_reconciliation(env)
    post_statements(env)
    _delete_hooks(env)
    update_payment_state_partial(env)
    openupgrade.delete_record_translations(
        env.cr,
        "account",
        ["email_template_edi_invoice", "mail_template_data_payment_receipt"],
    )
