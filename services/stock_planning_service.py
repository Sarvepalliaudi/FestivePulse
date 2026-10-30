"""
FestivePulse — Deterministic Festival Stock Planning Service
Implements strictly formula-based procurement planning:
  Suggested purchase quantity = max(0, planned demand + safety stock - usable stock)
  Estimated purchase cost = purchase quantity * recorded unit cost

Budget evaluation, top-contributor excess analysis, and manual override tracking.
100% Non-AI. Zero automated order placements.
"""

import math
from typing import Dict, Any, List, Optional, Tuple
import pandas as pd
from database.connection import get_db_connection
from services.demand_estimation_service import estimate_product_demand


def get_usable_stock(product_id: int) -> int:
    """
    Returns existing usable stock on hand:
    Unexpired, positive available quantity from active inventory batches.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COALESCE(SUM(quantity_available), 0) AS usable_stock
            FROM inventory_batches
            WHERE product_id = ?
              AND quantity_available > 0
              AND (expiry_date IS NULL OR expiry_date >= DATE('now'))
        """, (product_id,))
        row = cursor.fetchone()
        return int(row["usable_stock"]) if row else 0
    finally:
        conn.close()


def compute_product_stock_plan(
    product_id: int,
    occurrence_id: int,
    growth_multiplier: float = 1.10,
    manual_demand_override: Optional[float] = None,
    configured_safety_stock: Optional[int] = None,
    manual_purchase_override: Optional[int] = None,
    trim_spikes: bool = False
) -> Dict[str, Any]:
    """
    Computes deterministic stock planning for a single product.

    Formula:
      Suggested purchase quantity = max(0, planned demand + safety stock - usable stock)
      Estimated purchase cost = suggested purchase quantity * unit cost

    Supports pack size rounding and preserves both original calculation and user overrides.
    """
    p_id = int(product_id)
    occ_id = int(occurrence_id)
    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # 1. Product Master & Supplier Information
        cursor.execute("""
            SELECT p.product_id, p.sku, p.product_name, p.category_id, p.cost_price, p.selling_price,
                   p.min_safety_stock, p.reorder_quantity, p.is_perishable, p.shelf_life_days,
                   c.category_name
            FROM products p
            JOIN product_categories c ON p.category_id = c.category_id
            WHERE p.product_id = ?
        """, (p_id,))
        p = cursor.fetchone()
        if not p:
            raise ValueError(f"Product ID {product_id} not found.")

        # Supplier & Lead Time
        cursor.execute("""
            SELECT s.supplier_name, s.average_lead_time_days
            FROM inventory_batches b
            JOIN suppliers s ON b.supplier_id = s.supplier_id
            WHERE b.product_id = ?
            ORDER BY b.received_date DESC LIMIT 1
        """, (p_id,))
        sup_row = cursor.fetchone()
        supplier_name = sup_row["supplier_name"] if sup_row else "Primary Distributor"
        lead_time_days = int(sup_row["average_lead_time_days"]) if sup_row else 7

        # 2. Demand Estimation
        demand_est = estimate_product_demand(
            product_id=p_id,
            target_occurrence_id=occ_id,
            growth_multiplier=growth_multiplier,
            manual_daily_estimate=manual_demand_override,
            trim_spikes=trim_spikes
        )
        planned_demand = int(demand_est.get("estimated_units", 0))
        fest_window = int(demand_est.get("festival_window_days", 10))
        demand_status = demand_est.get("status", "INSUFFICIENT_HISTORICAL_DATA")
        demand_status_label = demand_est.get("status_label", "⚠️ Insufficient historical data")

        # 3. Existing Usable Stock (Unexpired stock on hand)
        usable_stock = get_usable_stock(p_id)

        # 4. Explicitly Configured Safety Stock
        # If user explicitly provides safety stock in plan, use that; otherwise use p.min_safety_stock
        if configured_safety_stock is not None:
            safety_stock = max(0, int(configured_safety_stock))
            safety_source = "User Configured"
        else:
            safety_stock = max(0, int(p["min_safety_stock"] or 0))
            safety_source = "Product Safety Stock Default"

        # 5. Deterministic Purchase Quantity Formula:
        # Suggested purchase quantity = max(0, planned demand + safety stock - usable stock)
        gross_required = planned_demand + safety_stock
        raw_suggested = max(0, gross_required - usable_stock)

        daily_rate = planned_demand / max(1, fest_window)
        lead_time_demand = math.ceil(daily_rate * lead_time_days)
        reorder_point = lead_time_demand + safety_stock

        # Pack Size / Reorder Quantity Rounding
        pack_size = int(p["reorder_quantity"]) if p["reorder_quantity"] and p["reorder_quantity"] > 0 else 1
        if raw_suggested > 0 and pack_size > 1:
            packs_needed = math.ceil(raw_suggested / float(pack_size))
            original_suggested = packs_needed * pack_size
            rounding_note = f"Rounded to pack size of {pack_size} ({packs_needed} packs = {original_suggested} units)"
        else:
            original_suggested = raw_suggested
            rounding_note = "Exact unit quantity (no pack rounding)"

        # 6. Manual Overrides
        if manual_purchase_override is not None:
            edited_quantity = max(0, int(manual_purchase_override))
            is_overridden = True
            override_delta = edited_quantity - original_suggested
        else:
            edited_quantity = original_suggested
            is_overridden = False
            override_delta = 0

        # 7. Recorded Unit Cost & Procurement Cost Calculation
        unit_cost = float(p["cost_price"] or 0.0)
        original_procurement_cost = round(original_suggested * unit_cost, 2)
        planned_procurement_cost = round(edited_quantity * unit_cost, 2)

        # 8. Step-by-Step Arithmetic String
        arithmetic = (
            f"max(0, {planned_demand} demand + {safety_stock} safety - {usable_stock} usable) "
            f"= max(0, {gross_required} - {usable_stock}) = {raw_suggested} units"
        )
        if pack_size > 1 and raw_suggested > 0:
            arithmetic += f" → {original_suggested} units ({rounding_note})"

        # 9. Stock Sufficiency Evaluation
        is_sufficient = (usable_stock >= gross_required)
        if is_sufficient:
            procurement_status = "SUFFICIENT_STOCK"
            status_badge = "✅ Sufficient Stock (No Purchase Required)"
        elif is_overridden:
            procurement_status = "OVERRIDDEN"
            status_badge = f"✏️ Overridden ({edited_quantity} units planned)"
        else:
            procurement_status = "ORDER_REQUIRED"
            status_badge = f"🛒 Purchase Required ({original_suggested} units)"

        # 10. Perishable Shelf-Life Assessment
        is_perishable = bool(p["is_perishable"])
        shelf_life = p["shelf_life_days"]
        staggered_schedule = []
        is_spoilage_risk = False
        spoilage_warning = ""

        if is_perishable and shelf_life:
            max_holding = shelf_life - 2
            if max_holding < (fest_window + lead_time_days) and edited_quantity > 0:
                is_spoilage_risk = True
                spoilage_warning = (
                    f"⚠️ SPOILAGE RISK: Shelf life is {shelf_life} days, but festival campaign is {fest_window} days. "
                    f"Ordering all {edited_quantity} units at once risks expiration. Stagger delivery across 3 phases."
                )
                b1 = math.ceil(edited_quantity * 0.40)
                b2 = math.ceil(edited_quantity * 0.40)
                b3 = edited_quantity - (b1 + b2)
                staggered_schedule = [
                    {"phase": "Delivery 1 (Pre-festival buildup)", "quantity": b1, "timing": "T-7 days to peak"},
                    {"phase": "Delivery 2 (Peak surge replenishment)", "quantity": b2, "timing": "T-2 days to peak"},
                    {"phase": "Delivery 3 (Final holiday run)", "quantity": max(0, b3), "timing": "Festival eve"}
                ]

        return {
            "product_id": product_id,
            "product_name": p["product_name"],
            "sku": p["sku"],
            "category_id": p["category_id"],
            "category_name": p["category_name"],
            "supplier_name": supplier_name,
            "lead_time_days": lead_time_days,
            "usable_stock": usable_stock,
            "stock_on_hand": usable_stock,  # Backwards compatibility key
            "planned_demand": planned_demand,
            "estimated_festival_demand": planned_demand,  # Backwards compatibility key
            "demand_status": demand_status,
            "demand_status_label": demand_status_label,
            "safety_stock": safety_stock,
            "safety_source": safety_source,
            "reorder_point": reorder_point,
            "lead_time_demand": lead_time_demand,
            "gross_required": gross_required,
            "raw_suggested_quantity": raw_suggested,
            "pack_size": pack_size,
            "rounding_note": rounding_note,
            "original_suggested_quantity": original_suggested,
            "recommended_order_quantity": edited_quantity,  # Backwards compatibility key
            "edited_purchase_quantity": edited_quantity,
            "is_overridden": is_overridden,
            "override_delta": override_delta,
            "unit_cost": unit_cost,
            "original_procurement_cost": original_procurement_cost,
            "planned_procurement_cost": planned_procurement_cost,
            "estimated_procurement_cost": planned_procurement_cost,  # Backwards compatibility key
            "arithmetic_breakdown": arithmetic,
            "is_sufficient": is_sufficient,
            "procurement_status": procurement_status,
            "status_badge": status_badge,
            "is_perishable": is_perishable,
            "shelf_life_days": shelf_life,
            "is_spoilage_risk": is_spoilage_risk,
            "spoilage_warning": spoilage_warning,
            "staggered_schedule": staggered_schedule,
            "festival_window_days": fest_window
        }
    finally:
        conn.close()


def analyze_budget_excess(
    items: List[Dict[str, Any]],
    purchasing_budget: float
) -> Dict[str, Any]:
    """
    Analyzes purchasing budget utilization and identifies top contributors to budget excess.

    Returns:
      - is_budget_exceeded: bool
      - overrun_amount: float
      - budget_utilization_pct: float
      - top_contributors: ranked list of top products by procurement cost
      - explanation_narrative: transparent text breakdown explaining the excess
    """
    total_planned_cost = sum(item["planned_procurement_cost"] for item in items)
    total_original_cost = sum(item["original_procurement_cost"] for item in items)
    purchasing_budget = max(0.0, float(purchasing_budget))

    is_budget_exceeded = (total_planned_cost > purchasing_budget)
    overrun_amount = max(0.0, round(total_planned_cost - purchasing_budget, 2))
    budget_utilization_pct = round((total_planned_cost / purchasing_budget * 100.0), 1) if purchasing_budget > 0 else 0.0

    # Calculate individual share of total planned cost
    contributions = []
    for item in items:
        cost = item["planned_procurement_cost"]
        share_pct = round((cost / total_planned_cost * 100.0), 1) if total_planned_cost > 0 else 0.0
        contributions.append({
            "product_id": item["product_id"],
            "sku": item["sku"],
            "product_name": item["product_name"],
            "planned_quantity": item["edited_purchase_quantity"],
            "unit_cost": item["unit_cost"],
            "planned_cost": cost,
            "cost_share_pct": share_pct
        })

    # Sort descending by cost
    contributions.sort(key=lambda x: x["planned_cost"], reverse=True)

    # Narrative generation
    if is_budget_exceeded:
        # Identify top contributors making up the excess
        top_items = [c for c in contributions if c["planned_cost"] > 0][:3]
        top_desc_list = [
            f"**{c['product_name']}** (₹{c['planned_cost']:,.2f}, {c['cost_share_pct']}% of total plan)"
            for c in top_items
        ]
        top_desc_str = ", ".join(top_desc_list)
        narrative = (
            f"⚠️ **Purchasing Budget Exceeded by ₹{overrun_amount:,.2f}** "
            f"({budget_utilization_pct:.1f}% budget utilization vs ₹{purchasing_budget:,.2f} limit). "
            f"The primary cost drivers contributing most to the excess are: {top_desc_str}. "
            f"Adjusting quantities or staggering delivery phases for these high-value items will bring the plan within budget."
        )
    else:
        surplus = round(purchasing_budget - total_planned_cost, 2)
        narrative = (
            f"✅ **Plan Within Budget:** Total planned procurement is ₹{total_planned_cost:,.2f} "
            f"({budget_utilization_pct:.1f}% of ₹{purchasing_budget:,.2f} budget). "
            f"Remaining unallocated capital: ₹{surplus:,.2f}."
        )

    return {
        "purchasing_budget": purchasing_budget,
        "total_planned_cost": round(total_planned_cost, 2),
        "total_original_cost": round(total_original_cost, 2),
        "is_budget_exceeded": is_budget_exceeded,
        "overrun_amount": overrun_amount,
        "budget_utilization_pct": budget_utilization_pct,
        "top_contributors": contributions,
        "explanation_narrative": narrative
    }


def generate_festival_stock_plan_table(
    occurrence_id: int,
    purchasing_budget: float,
    selected_product_ids: Optional[List[int]] = None,
    category_id: Optional[int] = None,
    growth_multiplier: float = 1.10,
    manual_demand_overrides: Optional[Dict[int, float]] = None,
    safety_stock_overrides: Optional[Dict[int, int]] = None,
    manual_purchase_overrides: Optional[Dict[int, int]] = None,
    trim_spikes: bool = False
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Generates complete stock planning worksheet and budget analysis.
    """
    manual_demand_overrides = manual_demand_overrides or {}
    safety_stock_overrides = safety_stock_overrides or {}
    manual_purchase_overrides = manual_purchase_overrides or {}

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
        all_active_pids = [r["product_id"] for r in cursor.fetchall()]
    finally:
        conn.close()

    # Filter to selected product IDs if specified
    if selected_product_ids is not None:
        pids_to_process = [pid for pid in all_active_pids if pid in selected_product_ids]
    else:
        pids_to_process = all_active_pids

    items = []
    for pid in pids_to_process:
        d_override = manual_demand_overrides.get(pid)
        ss_override = safety_stock_overrides.get(pid)
        p_override = manual_purchase_overrides.get(pid)

        item_plan = compute_product_stock_plan(
            product_id=pid,
            occurrence_id=occurrence_id,
            growth_multiplier=growth_multiplier,
            manual_demand_override=d_override,
            configured_safety_stock=ss_override,
            manual_purchase_override=p_override,
            trim_spikes=trim_spikes
        )
        items.append(item_plan)

    budget_analysis = analyze_budget_excess(items, purchasing_budget)
    df = pd.DataFrame(items)
    return df, budget_analysis
