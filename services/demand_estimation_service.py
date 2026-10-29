"""
FestivePulse — Transparent, Non-AI Festival Demand Estimation Service
Implements auditable operations research methods comparing daily sales across
comparable periods and previous festival occurrences, accounting for period durations.
Zero machine learning, zero external APIs, zero fabricated historical data.
Keeps forecasts strictly separated from actual sales ledgers.
"""

import math
from datetime import date, datetime
from typing import Dict, Any, List, Optional, Tuple
import pandas as pd
from database.connection import get_db_connection


STANDARD_UNCERTAINTY_LIMITATIONS = [
    "Estimates are derived strictly from historical transactional run-rates and do not guarantee future sales.",
    "Does not account for external macroeconomic shifts, unseasonable weather events, or hyper-local competitor discounting.",
    "Assumes stable product availability and supplier lead times during the target festival window.",
    "Not a financial guarantee or binding commitment. Use as an operational planning baseline."
]


def parse_date_str(val: Any) -> Optional[date]:
    """Safely converts string/date to datetime.date."""
    if not val:
        return None
    if isinstance(val, date):
        return val
    if isinstance(val, datetime):
        return val.date()
    try:
        return datetime.strptime(str(val).strip(), "%Y-%m-%d").date()
    except Exception:
        return None


def get_festival_occurrence_details(occurrence_id: int) -> Optional[Dict[str, Any]]:
    """Fetches metadata and duration for a festival occurrence."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT o.occurrence_id, o.festival_id, o.year, o.campaign_start_date, o.campaign_end_date,
                   o.peak_start_date, o.festival_date, o.notes,
                   f.festival_name, f.festival_code, f.typical_surge_multiplier
            FROM festival_occurrences o
            JOIN festivals f ON o.festival_id = f.festival_id
            WHERE o.occurrence_id = ?
        """, (occurrence_id,))
        row = cursor.fetchone()
        if not row:
            return None
        res = dict(row)
        s_dt = parse_date_str(res["campaign_start_date"])
        e_dt = parse_date_str(res["campaign_end_date"])
        res["duration_days"] = max(1, (e_dt - s_dt).days + 1) if s_dt and e_dt else 10
        return res
    finally:
        conn.close()


def detect_sales_spike(daily_sales: List[Dict[str, Any]], total_units: int) -> Tuple[bool, Optional[str], int]:
    """
    Detects if an unusual one-off sales spike occurred (e.g. a single invoice or day
    accounting for >= 50% of the entire period's volume).
    Returns (has_spike, spike_explanation, normalized_units_estimate).
    """
    if not daily_sales or total_units <= 0:
        return False, None, total_units

    # Find maximum single-day units
    max_day = max(daily_sales, key=lambda d: d["units"])
    max_units = max_day["units"]
    pct_of_total = (max_units / total_units) * 100.0

    # If single day >= 50% of total and >= 10 units, flag as unusual spike
    if pct_of_total >= 50.0 and len(daily_sales) > 1 and max_units >= 10:
        # Calculate median of remaining days
        other_units = [d["units"] for d in daily_sales if d["date"] != max_day["date"]]
        median_other = sorted(other_units)[len(other_units) // 2] if other_units else 0
        normalized_units = (total_units - max_units) + median_other

        desc = (
            f"Unusual bulk spike detected on {max_day['date']} ({max_units} units in a single day, "
            f"representing {pct_of_total:.1f}% of entire period sales). "
            f"This often indicates an institutional/corporate gift booking rather than walk-in retail footfall."
        )
        return True, desc, max(1, normalized_units)

    return False, None, total_units


def estimate_product_demand(
    product_id: int,
    target_occurrence_id: int,
    growth_multiplier: float = 1.0,
    manual_daily_estimate: Optional[float] = None,
    trim_spikes: bool = False
) -> Dict[str, Any]:
    """
    Computes transparent, non-AI festival demand estimation for a single product.
    
    Documented Method:
    1. Checks for prior completed sales for this product during previous occurrences of the SAME festival.
       Computes historical daily sales = (historical units / historical days).
       Estimates target units = Ceil(historical daily sales * target days * growth_multiplier).
    2. If no same-festival sales exist, checks for recent non-festival baseline sales (past 60 days).
       Computes baseline daily sales = (baseline units / baseline days).
       Estimates target units = Ceil(baseline daily sales * festival surge multiplier * target days * growth_multiplier).
    3. If neither exists (zero sales history):
       Returns status = 'INSUFFICIENT_HISTORICAL_DATA' and provides a clearly labelled Manual Planning Estimate.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # 1. Product Master Data
        cursor.execute("""
            SELECT p.product_id, p.sku, p.product_name, p.category_id, p.cost_price, p.selling_price,
                   p.min_safety_stock, p.reorder_quantity, c.category_name, c.default_gst_rate
            FROM products p
            JOIN product_categories c ON p.category_id = c.category_id
            WHERE p.product_id = ?
        """, (product_id,))
        p_row = cursor.fetchone()
        if not p_row:
            raise ValueError(f"Product ID {product_id} not found in database.")

        cost_price = float(p_row["cost_price"])
        selling_price = float(p_row["selling_price"])

        # 2. Target Festival Occurrence Data
        target_fest = get_festival_occurrence_details(target_occurrence_id)
        if not target_fest:
            raise ValueError(f"Festival occurrence ID {target_occurrence_id} not found.")

        fest_id = target_fest["festival_id"]
        fest_name = target_fest["festival_name"]
        target_year = target_fest["year"]
        target_days = target_fest["duration_days"]
        cat_surge = float(target_fest["typical_surge_multiplier"])
        target_period_str = f"{target_fest['campaign_start_date']} to {target_fest['campaign_end_date']} ({target_days} days)"

        # -----------------------------------------------------------------
        # STEP 1: HISTORICAL OCCURRENCE OF SAME FESTIVAL
        # -----------------------------------------------------------------
        cursor.execute("""
            SELECT prev_occ.occurrence_id, prev_occ.year, prev_occ.campaign_start_date, prev_occ.campaign_end_date,
                   COALESCE(SUM(si.quantity), 0) AS total_units,
                   COUNT(DISTINCT inv.invoice_id) AS transaction_count,
                   COUNT(DISTINCT inv.invoice_date) AS active_sales_days
            FROM sales_items si
            JOIN sales_invoices inv ON si.invoice_id = inv.invoice_id
            JOIN festival_occurrences prev_occ ON inv.occurrence_id = prev_occ.occurrence_id
            WHERE si.product_id = ?
              AND prev_occ.festival_id = ?
              AND prev_occ.year < ?
              AND inv.status = 'COMPLETED'
            GROUP BY prev_occ.occurrence_id
            ORDER BY prev_occ.year DESC
            LIMIT 1
        """, (product_id, fest_id, target_year))
        hist_row = cursor.fetchone()

        hist_units = int(hist_row["total_units"]) if hist_row else 0
        hist_tx_count = int(hist_row["transaction_count"]) if hist_row else 0
        hist_active_days = int(hist_row["active_sales_days"]) if hist_row else 0

        # CASE A: PREVIOUS FESTIVAL OCCURRENCE HAS ACTUAL SALES
        if hist_units > 0 and hist_row:
            h_start = parse_date_str(hist_row["campaign_start_date"])
            h_end = parse_date_str(hist_row["campaign_end_date"])
            hist_duration_days = max(1, (h_end - h_start).days + 1) if h_start and h_end else target_days
            baseline_name = f"{fest_name} {hist_row['year']} (Previous Occurrence)"
            baseline_period_str = f"{hist_row['campaign_start_date']} to {hist_row['campaign_end_date']} ({hist_duration_days} days)"

            # Daily sales distribution for spike detection
            cursor.execute("""
                SELECT inv.invoice_date AS date, SUM(si.quantity) AS units
                FROM sales_items si
                JOIN sales_invoices inv ON si.invoice_id = inv.invoice_id
                WHERE si.product_id = ?
                  AND inv.occurrence_id = ?
                  AND inv.status = 'COMPLETED'
                GROUP BY inv.invoice_date
                ORDER BY inv.invoice_date ASC
            """, (product_id, hist_row["occurrence_id"]))
            daily_breakdown = [dict(r) for r in cursor.fetchall()]

            has_spike, spike_text, normalized_units = detect_sales_spike(daily_breakdown, hist_units)

            units_to_use = normalized_units if (trim_spikes and has_spike) else hist_units
            hist_daily_rate = units_to_use / float(hist_duration_days)

            # Calculation
            raw_estimated = hist_daily_rate * target_days * growth_multiplier
            estimated_units = max(0, math.ceil(raw_estimated))

            partial_note = None
            if hist_duration_days != target_days:
                partial_note = (
                    f"Period Duration Normalization: Previous festival period was {hist_duration_days} days, "
                    f"while target festival period is {target_days} days. Daily rate of {hist_daily_rate:.2f} units/day "
                    f"is scaled by target duration."
                )

            arithmetic = (
                f"⌈({units_to_use} units ÷ {hist_duration_days} historical days) × {target_days} target days × {growth_multiplier:.2f} growth⌉ "
                f"= ⌈{hist_daily_rate:.2f} units/day × {target_days} days × {growth_multiplier:.2f}⌉ "
                f"= ⌈{raw_estimated:.2f}⌉ = {estimated_units} units"
            )

            formula_name = "Duration-Normalized Previous Festival Run-Rate (YoY)"
            formula_latex = "Estimated Units = ⌈(Historical Festival Units / Historical Duration Days) × Target Duration Days × Growth Multiplier⌉"
            status = "EMPIRICAL_FESTIVAL_YOY"
            method_desc = (
                f"Prior festival occurrence model: Derived from {hist_units} units sold across {hist_tx_count} transactions "
                f"during {fest_name} {hist_row['year']}."
            )

            return {
                "product_id": product_id,
                "product_name": p_row["product_name"],
                "sku": p_row["sku"],
                "category_name": p_row["category_name"],
                "festival_name": fest_name,
                "status": status,
                "status_label": f"✅ Empirical ({fest_name} {hist_row['year']} History)",
                "method": "HISTORICAL_YOY",
                "method_description": method_desc,
                "multiplier": growth_multiplier,
                "estimated_demand_units": estimated_units,
                "daily_festival_demand": round(estimated_units / float(target_days), 2),
                "festival_window_days": target_days,
                "baseline_units": hist_units,
                "estimated_units": estimated_units,
                "estimated_units_raw": round(raw_estimated, 2),
                "daily_run_rate": round(estimated_units / float(target_days), 2),
                "estimated_revenue": round(estimated_units * selling_price, 2),
                "estimated_cost": round(estimated_units * cost_price, 2),
                "estimated_profit": round(estimated_units * (selling_price - cost_price), 2),
                "selling_price": selling_price,
                "cost_price": cost_price,
                "historical_sample_size": {
                    "total_units_sold": hist_units,
                    "transaction_count": hist_tx_count,
                    "active_sales_days": hist_active_days,
                    "period_duration_days": hist_duration_days,
                    "daily_sales_rate": round(hist_daily_rate, 2)
                },
                "baseline_period": {
                    "type": "PREVIOUS_FESTIVAL_OCCURRENCE",
                    "name": baseline_name,
                    "period_str": baseline_period_str,
                    "duration_days": hist_duration_days,
                    "start_date": str(hist_row["campaign_start_date"]),
                    "end_date": str(hist_row["campaign_end_date"])
                },
                "target_period": {
                    "name": f"{fest_name} {target_year}",
                    "duration_days": target_days,
                    "period_str": target_period_str
                },
                "calculation_details": {
                    "formula_name": formula_name,
                    "formula_latex": formula_latex,
                    "arithmetic_breakdown": arithmetic,
                    "applied_growth_rate": growth_multiplier,
                    "applied_surge_multiplier": 1.0,
                    "partial_period_note": partial_note,
                    "spike_analysis": {
                        "has_spike": has_spike,
                        "description": spike_text,
                        "trimmed": trim_spikes and has_spike,
                        "untrimmed_units": hist_units,
                        "normalized_units": normalized_units
                    }
                },
                "uncertainty_limitations": STANDARD_UNCERTAINTY_LIMITATIONS,
                "is_manual": False,
                "is_guaranteed": False
            }

        # -----------------------------------------------------------------
        # STEP 2: RECENT NON-FESTIVAL BASELINE SALES
        # -----------------------------------------------------------------
        baseline_lookback_days = 60
        cursor.execute("""
            SELECT COALESCE(SUM(si.quantity), 0) AS total_units,
                   COUNT(DISTINCT inv.invoice_id) AS transaction_count,
                   COUNT(DISTINCT inv.invoice_date) AS active_sales_days,
                   MIN(inv.invoice_date) AS earliest_sale,
                   MAX(inv.invoice_date) AS latest_sale
            FROM sales_items si
            JOIN sales_invoices inv ON si.invoice_id = inv.invoice_id
            WHERE si.product_id = ?
              AND inv.status = 'COMPLETED'
              AND inv.invoice_date >= DATE('now', '-' || ? || ' days')
        """, (product_id, baseline_lookback_days))
        reg_row = cursor.fetchone()
        reg_units = int(reg_row["total_units"]) if reg_row else 0
        reg_tx = int(reg_row["transaction_count"]) if reg_row else 0
        reg_active_days = int(reg_row["active_sales_days"]) if reg_row else 0

        # If recent non-festival sales exist:
        if reg_units > 0:
            reg_daily_rate = reg_units / float(baseline_lookback_days)
            raw_estimated = reg_daily_rate * cat_surge * target_days * growth_multiplier
            estimated_units = max(0, math.ceil(raw_estimated))

            baseline_period_str = f"Past {baseline_lookback_days} Days (Earliest: {reg_row['earliest_sale']}, Latest: {reg_row['latest_sale']})"

            arithmetic = (
                f"⌈({reg_units} units ÷ {baseline_lookback_days} days) × {cat_surge:.2f} surge × {target_days} target days × {growth_multiplier:.2f} growth⌉ "
                f"= ⌈{reg_daily_rate:.2f} units/day × {cat_surge:.2f} × {target_days} days × {growth_multiplier:.2f}⌉ "
                f"= ⌈{raw_estimated:.2f}⌉ = {estimated_units} units"
            )

            formula_name = "Off-Season Baseline Run-Rate with Category Surge Multiplier"
            formula_latex = "Estimated Units = ⌈(Baseline Units / Baseline Days) × Category Surge Multiplier × Target Duration Days × Growth Multiplier⌉"
            status = "EMPIRICAL_RECENT_BASELINE"

            return {
                "product_id": product_id,
                "product_name": p_row["product_name"],
                "sku": p_row["sku"],
                "category_name": p_row["category_name"],
                "festival_name": fest_name,
                "status": status,
                "status_label": "📊 Empirical (Recent Off-Season Baseline + Category Surge)",
                "method": "CATEGORY_SURGE_BASELINE",
                "method_description": "Category Surge baseline model based on recent 60-day store run rate.",
                "multiplier": growth_multiplier,
                "estimated_demand_units": estimated_units,
                "daily_festival_demand": round(estimated_units / float(target_days), 2),
                "festival_window_days": target_days,
                "baseline_units": reg_units,
                "estimated_units": estimated_units,
                "estimated_units_raw": round(raw_estimated, 2),
                "daily_run_rate": round(estimated_units / float(target_days), 2),
                "estimated_revenue": round(estimated_units * selling_price, 2),
                "estimated_cost": round(estimated_units * cost_price, 2),
                "estimated_profit": round(estimated_units * (selling_price - cost_price), 2),
                "selling_price": selling_price,
                "cost_price": cost_price,
                "historical_sample_size": {
                    "total_units_sold": reg_units,
                    "transaction_count": reg_tx,
                    "active_sales_days": reg_active_days,
                    "period_duration_days": baseline_lookback_days,
                    "daily_sales_rate": round(reg_daily_rate, 2)
                },
                "baseline_period": {
                    "type": "RECENT_NON_FESTIVAL_BASELINE",
                    "name": f"Recent 60-Day Store Run-Rate",
                    "period_str": baseline_period_str,
                    "duration_days": baseline_lookback_days,
                    "start_date": str(reg_row["earliest_sale"] or "N/A"),
                    "end_date": str(reg_row["latest_sale"] or "N/A")
                },
                "target_period": {
                    "name": f"{fest_name} {target_year}",
                    "duration_days": target_days,
                    "period_str": target_period_str
                },
                "calculation_details": {
                    "formula_name": formula_name,
                    "formula_latex": formula_latex,
                    "arithmetic_breakdown": arithmetic,
                    "applied_growth_rate": growth_multiplier,
                    "applied_surge_multiplier": cat_surge,
                    "partial_period_note": "No previous festival occurrence sales found for this product. Derived from recent non-festival run-rate scaled by category surge factor.",
                    "spike_analysis": {
                        "has_spike": False,
                        "description": None,
                        "trimmed": False,
                        "untrimmed_units": reg_units,
                        "normalized_units": reg_units
                    }
                },
                "uncertainty_limitations": STANDARD_UNCERTAINTY_LIMITATIONS,
                "is_manual": False,
                "is_guaranteed": False
            }

        # -----------------------------------------------------------------
        # STEP 3: INSUFFICIENT HISTORICAL DATA (NO FABRICATED NUMBERS)
        # -----------------------------------------------------------------
        # Check if user specified a manual daily planning estimate
        if manual_daily_estimate is not None and manual_daily_estimate > 0:
            manual_units = math.ceil(manual_daily_estimate * target_days)
            status = "MANUAL_PLANNING_ESTIMATE"
            status_label = "✏️ Manual Planning Estimate (User-Defined Assumption)"
            formula_name = "User-Defined Daily Target × Festival Duration"
            formula_latex = "Estimated Units = ⌈Manual Daily Target × Target Duration Days⌉"
            arithmetic = f"⌈{manual_daily_estimate:.1f} units/day × {target_days} days⌉ = {manual_units} units"
            est_units_final = manual_units
            is_manual = True
        else:
            status = "INSUFFICIENT_HISTORICAL_DATA"
            status_label = "⚠️ Insufficient historical data"
            formula_name = "No Formula Applied (Zero Historical Transactions)"
            formula_latex = "N/A (Historical Transactions = 0)"
            arithmetic = "0 historical sales transactions recorded in FestivePulse SQLite database. Mathematical run-rate cannot be computed without empirical data."
            est_units_final = 0
            is_manual = False

        return {
            "product_id": product_id,
            "product_name": p_row["product_name"],
            "sku": p_row["sku"],
            "category_name": p_row["category_name"],
            "festival_name": fest_name,
            "status": status,
            "status_label": status_label,
            "method": "MANUAL_PLANNING_ESTIMATE" if is_manual else "INSUFFICIENT_HISTORICAL_DATA",
            "method_description": "Manual planning estimate" if is_manual else "Insufficient historical data",
            "multiplier": growth_multiplier,
            "estimated_demand_units": est_units_final,
            "daily_festival_demand": round(est_units_final / float(target_days), 2),
            "festival_window_days": target_days,
            "baseline_units": 0,
            "estimated_units": est_units_final,
            "estimated_units_raw": float(est_units_final),
            "daily_run_rate": round(est_units_final / float(target_days), 2),
            "estimated_revenue": round(est_units_final * selling_price, 2),
            "estimated_cost": round(est_units_final * cost_price, 2),
            "estimated_profit": round(est_units_final * (selling_price - cost_price), 2),
            "selling_price": selling_price,
            "cost_price": cost_price,
            "historical_sample_size": {
                "total_units_sold": 0,
                "transaction_count": 0,
                "active_sales_days": 0,
                "period_duration_days": 0,
                "daily_sales_rate": 0.0
            },
            "baseline_period": {
                "type": "NONE",
                "name": "No Historical Baseline Available",
                "period_str": "No transactions found in database for this SKU",
                "duration_days": 0,
                "start_date": "N/A",
                "end_date": "N/A"
            },
            "target_period": {
                "name": f"{fest_name} {target_year}",
                "duration_days": target_days,
                "period_str": target_period_str
            },
            "calculation_details": {
                "formula_name": formula_name,
                "formula_latex": formula_latex,
                "arithmetic_breakdown": arithmetic,
                "applied_growth_rate": growth_multiplier,
                "applied_surge_multiplier": None,
                "partial_period_note": "Product has zero historical sales. No baseline fabricated.",
                "spike_analysis": {
                    "has_spike": False,
                    "description": None,
                    "trimmed": False,
                    "untrimmed_units": 0,
                    "normalized_units": 0
                }
            },
            "uncertainty_limitations": [
                "Zero historical sales found in FestivePulse database. All manual planning figures represent subjective retail assumptions.",
                "Actual demand may vary drastically from unverified manual targets."
            ] + STANDARD_UNCERTAINTY_LIMITATIONS,
            "is_manual": is_manual,
            "is_guaranteed": False
        }

    finally:
        conn.close()


def generate_demand_forecast_table(
    target_occurrence_id: int,
    category_id: Optional[int] = None,
    growth_multiplier: float = 1.0,
    trim_spikes: bool = False,
    manual_overrides: Optional[Dict[int, float]] = None
) -> pd.DataFrame:
    """
    Computes transparent demand estimates across all active products.
    Keeps forecasts strictly separated from actual sales ledgers.
    """
    manual_overrides = manual_overrides or {}
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        sql = "SELECT product_id FROM products WHERE is_active = 1"
        params: List[Any] = []
        if category_id:
            sql += " AND category_id = ?"
            params.append(category_id)
        sql += " ORDER BY product_name ASC"

        cursor.execute(sql, tuple(params))
        p_ids = [row["product_id"] for row in cursor.fetchall()]

        records = []
        for pid in p_ids:
            man_est = manual_overrides.get(pid)
            est = estimate_product_demand(
                product_id=pid,
                target_occurrence_id=target_occurrence_id,
                growth_multiplier=growth_multiplier,
                manual_daily_estimate=man_est,
                trim_spikes=trim_spikes
            )
            records.append({
                "product_id": est["product_id"],
                "sku": est["sku"],
                "product_name": est["product_name"],
                "category_name": est["category_name"],
                "status": est["status"],
                "status_label": est["status_label"],
                "estimated_units": est["estimated_units"],
                "daily_run_rate": est["daily_run_rate"],
                "hist_units_sold": est["historical_sample_size"]["total_units_sold"],
                "hist_transactions": est["historical_sample_size"]["transaction_count"],
                "hist_period_days": est["historical_sample_size"]["period_duration_days"],
                "target_period_days": est["target_period"]["duration_days"],
                "baseline_period": est["baseline_period"]["name"],
                "formula_name": est["calculation_details"]["formula_name"],
                "formula_latex": est["calculation_details"]["formula_latex"],
                "arithmetic_breakdown": est["calculation_details"]["arithmetic_breakdown"],
                "has_spike": est["calculation_details"]["spike_analysis"]["has_spike"],
                "spike_description": est["calculation_details"]["spike_analysis"]["description"],
                "selling_price": est["selling_price"],
                "cost_price": est["cost_price"],
                "estimated_revenue": est["estimated_revenue"],
                "estimated_cost": est["estimated_cost"],
                "estimated_profit": est["estimated_profit"],
                "is_manual": est["is_manual"],
                "is_guaranteed": est["is_guaranteed"],
                "uncertainty_note": est["uncertainty_limitations"][0]
            })

        return pd.DataFrame(records)
    finally:
        conn.close()
