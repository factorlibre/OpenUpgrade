# Copyright 2021 ForgeFlow S.L.  <https://www.forgeflow.com>
# Copyright 2023 Tecnativa - Pedro M. Baeza
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).
import logging

from openupgradelib import openupgrade

_logger = logging.getLogger(__name__)


def merge_priorities(env):
    openupgrade.map_values(
        env.cr,
        openupgrade.get_legacy_name("priority"),
        "priority",
        [("1", "0"), ("2", "1"), ("3", "1")],
        table="stock_move",
    )
    openupgrade.map_values(
        env.cr,
        openupgrade.get_legacy_name("priority"),
        "priority",
        [("1", "0"), ("2", "1"), ("3", "1")],
        table="stock_picking",
    )


def recompute_stock_picking_scheduled_date(env):
    # OOW-BATCHED-STOCK-V1 (BLY 2026-06-05, propuesta_stock_recompute_batcheado
    # APROBADA): version set-based del recompute. La original iteraba
    # _compute_scheduled_date() picking a picking via ORM (~2h20 en BLY).
    # Semantica extraida de stock/models/stock_picking.py (v14):
    #   moves_dates = date de los moves del picking con state not in done/cancel
    #   move_type 'direct' -> MIN(moves_dates); resto -> MAX(moves_dates)
    #   sin moves abiertos -> conservar scheduled_date actual, o now()
    # AUTOVALIDACION: los primeros VALIDATE_N pickings van por el ORM ORIGINAL
    # (ground truth) y se comparan contra la prediccion SQL; cualquier
    # discrepancia ABORTA el camino batch y se cae al original completo.
    VALIDATE_N = 500
    env.cr.execute(
        """
        SELECT DISTINCT sp.id
        FROM stock_picking sp
        JOIN stock_move sm ON sm.picking_id = sp.id
        WHERE sp.state NOT IN ('done', 'cancel')
        ORDER BY sp.id"""
    )
    picking_ids = [pick[0] for pick in env.cr.fetchall()]
    if not picking_ids:
        return
    sample_ids = picking_ids[:VALIDATE_N]
    # prediccion SQL para TODO el conjunto (los del branch default-now se
    # marcan: su valor depende del instante y se validan por construccion)
    env.cr.execute(
        """
        CREATE TEMP TABLE oow_pred_sched AS
        SELECT sp.id,
               CASE WHEN sp.move_type = 'direct' THEN agg.min_d
                    ELSE agg.max_d END AS pred_moves,
               sp.scheduled_date AS pred_keep
        FROM stock_picking sp
        LEFT JOIN (
            SELECT sm.picking_id,
                   MIN(sm.date) FILTER (WHERE sm.state NOT IN ('done', 'cancel')) AS min_d,
                   MAX(sm.date) FILTER (WHERE sm.state NOT IN ('done', 'cancel')) AS max_d
            FROM stock_move sm
            WHERE sm.picking_id IS NOT NULL
            GROUP BY sm.picking_id
        ) agg ON agg.picking_id = sp.id
        WHERE sp.state NOT IN ('done', 'cancel')
          AND EXISTS (SELECT 1 FROM stock_move m WHERE m.picking_id = sp.id)"""
    )
    # ground truth: el ORM original sobre la muestra (queda PERSISTIDO, esos
    # pickings ya estan servidos por el camino original pase lo que pase)
    sample = env["stock.picking"].browse(sample_ids)
    sample._compute_scheduled_date()
    env["stock.picking"].flush(["scheduled_date"])
    env.cr.execute(
        """
        SELECT count(*)
        FROM oow_pred_sched p
        JOIN stock_picking sp ON sp.id = p.id
        WHERE p.id IN %s
          AND COALESCE(p.pred_moves, p.pred_keep) IS NOT NULL
          AND sp.scheduled_date IS DISTINCT FROM COALESCE(p.pred_moves, p.pred_keep)
        """,
        (tuple(sample_ids),),
    )
    mismatches = env.cr.fetchone()[0]
    if mismatches:
        _logger.error(
            "OOW-BATCHED-STOCK-V1 scheduled_date: %s discrepancias en la "
            "muestra de %s — ABORT del batch, camino ORM original completo.",
            mismatches,
            len(sample_ids),
        )
        env.cr.execute("DROP TABLE oow_pred_sched")
        pickings = env["stock.picking"].browse(picking_ids)
        pickings._compute_scheduled_date()
        return
    _logger.info(
        "OOW-BATCHED-STOCK-V1 scheduled_date: autovalidacion OK (%s/%s), "
        "aplicando UPDATE set-based al resto (%s pickings).",
        len(sample_ids),
        len(sample_ids),
        len(picking_ids) - len(sample_ids),
    )
    env.cr.execute(
        """
        UPDATE stock_picking sp
        SET scheduled_date = COALESCE(
                p.pred_moves, p.pred_keep, (now() at time zone 'UTC'))
        FROM oow_pred_sched p
        WHERE p.id = sp.id
          AND p.id NOT IN %s
          AND sp.scheduled_date IS DISTINCT FROM COALESCE(
                p.pred_moves, p.pred_keep, sp.scheduled_date)
        """,
        (tuple(sample_ids),),
    )
    _logger.info(
        "OOW-BATCHED-STOCK-V1 scheduled_date: %s filas actualizadas.",
        env.cr.rowcount,
    )
    env.cr.execute("DROP TABLE oow_pred_sched")
    # el UPDATE fue por SQL: invalidar cache ORM por si pasos posteriores leen
    env["stock.picking"].invalidate_cache(["scheduled_date"])


def save_stock_picking_date_deadline(env):
    openupgrade.logged_query(
        env.cr,
        """
        WITH picking_deadline AS (
            SELECT sp.id,
                CASE
                    WHEN sp.move_type = 'direct' THEN
                        MIN(sm.date_deadline)
                    ELSE
                        MAX(sm.date_deadline)
                END as date_deadline
            FROM stock_picking sp
                JOIN stock_move sm ON sm.picking_id = sp.id
            WHERE sm.date_deadline IS NOT NULL
            GROUP BY sp.id, sp.move_type
        )
        UPDATE stock_picking sp
        SET date_deadline = picking_deadline.date_deadline
        FROM picking_deadline
        WHERE picking_deadline.id = sp.id
        """,
    )
    openupgrade.logged_query(
        env.cr,
        """
        UPDATE stock_picking sp
        SET has_deadline_issue = TRUE
        WHERE date_deadline IS NOT NULL AND date_deadline < scheduled_date
        """,
    )


def recompute_stock_move_delay_alert_date(env):
    # OOW-BATCHED-STOCK-V1: version set-based. La original recorria via ORM
    # las cadenas move_orig_ids de cada move abierto (dominante de las ~2h20
    # del post-migration de stock en BLY: miles de micro-queries sobre
    # stock_move_move_rel). Semantica (stock/models/stock_move.py v14):
    #   prev_max = MAX(date de move_orig_ids con state not in done/cancel y date)
    #   delay_alert_date = prev_max si prev_max > move.date, si no False
    #   (los moves done/cancel no entran: la seleccion ya los excluye)
    # AUTOVALIDACION identica a scheduled_date (sin branch dependiente del
    # instante: comparacion exacta).
    VALIDATE_N = 500
    env.cr.execute(
        """
        SELECT sm.id
        FROM stock_move sm
        WHERE sm.state NOT IN ('done', 'cancel')
        ORDER BY sm.id
        """
    )
    move_ids = [move[0] for move in env.cr.fetchall()]
    if not move_ids:
        return
    sample_ids = move_ids[:VALIDATE_N]
    env.cr.execute(
        """
        CREATE TEMP TABLE oow_pred_alert AS
        SELECT dest.id,
               CASE WHEN agg.prev_max > dest.date THEN agg.prev_max END AS pred
        FROM stock_move dest
        LEFT JOIN (
            SELECT rel.move_dest_id AS dest_id, MAX(orig.date) AS prev_max
            FROM stock_move_move_rel rel
            JOIN stock_move orig ON orig.id = rel.move_orig_id
            WHERE orig.state NOT IN ('done', 'cancel')
              AND orig.date IS NOT NULL
            GROUP BY rel.move_dest_id
        ) agg ON agg.dest_id = dest.id
        WHERE dest.state NOT IN ('done', 'cancel')"""
    )
    sample = env["stock.move"].browse(sample_ids)
    sample._compute_delay_alert_date()
    env["stock.move"].flush(["delay_alert_date"])
    env.cr.execute(
        """
        SELECT count(*)
        FROM oow_pred_alert p
        JOIN stock_move sm ON sm.id = p.id
        WHERE p.id IN %s
          AND sm.delay_alert_date IS DISTINCT FROM p.pred
        """,
        (tuple(sample_ids),),
    )
    mismatches = env.cr.fetchone()[0]
    if mismatches:
        _logger.error(
            "OOW-BATCHED-STOCK-V1 delay_alert_date: %s discrepancias en la "
            "muestra de %s — ABORT del batch, camino ORM original completo.",
            mismatches,
            len(sample_ids),
        )
        env.cr.execute("DROP TABLE oow_pred_alert")
        moves = env["stock.move"].browse(move_ids)
        moves._compute_delay_alert_date()
        return
    _logger.info(
        "OOW-BATCHED-STOCK-V1 delay_alert_date: autovalidacion OK (%s/%s), "
        "aplicando UPDATE set-based al resto (%s moves).",
        len(sample_ids),
        len(sample_ids),
        len(move_ids) - len(sample_ids),
    )
    env.cr.execute(
        """
        UPDATE stock_move sm
        SET delay_alert_date = p.pred
        FROM oow_pred_alert p
        WHERE p.id = sm.id
          AND p.id NOT IN %s
          AND sm.delay_alert_date IS DISTINCT FROM p.pred
        """,
        (tuple(sample_ids),),
    )
    _logger.info(
        "OOW-BATCHED-STOCK-V1 delay_alert_date: %s filas actualizadas.",
        env.cr.rowcount,
    )
    env.cr.execute("DROP TABLE oow_pred_alert")
    env["stock.move"].invalidate_cache(["delay_alert_date"])


def delete_domain_from_view(env):
    view = env.ref("stock.report_stock_quantity_action")
    view.domain = None


@openupgrade.migrate()
def migrate(env, version):
    merge_priorities(env)
    delete_domain_from_view(env)
    openupgrade.load_data(env.cr, "stock", "14.0.1.1/noupdate_changes.xml")
    recompute_stock_picking_scheduled_date(env)
    save_stock_picking_date_deadline(env)
    recompute_stock_move_delay_alert_date(env)
    openupgrade.delete_record_translations(
        env.cr, "stock", ["mail_template_data_delivery_confirmation"]
    )
