"""
FestivePulse — Expense Management & Profit/Loss (P&L) Accounting Service
Deterministic financial accounting with auditable edits/corrections,
cost snapshot preservation, returns/discount adjustments, and labeled expense exclusions.
100% Non-AI. Formulas fully documented and exposed.
"""

import json
from typing import Dict, Any, List, Optional
from database.connection import get_db_connection, db_session


STANDARD_CATEGORIES = {
    "RENT": "Rent (Store, Stall, Warehouse)",
    "TRANSPORT": "Transport & Freight (Logistics, Delivery)",
    "PACKAGING": "Packaging (Boxes, Pouches, Bags, Foils)",
    "WAGES": "Wages & Bonuses (Staff Overtime, Temporary Labor)",
    "MARKETING": "Marketing & Promotion (Ads, Banners, Social Campaigns)",
    "OTHER": "Other Costs (Utilities, Incidental Overheads)",
    # Aliases
    "TEMPORARY_STALL_RENT": "Rent (Store, Stall, Warehouse)",
    "TRANSPORT_FREIGHT": "Transport & Freight (Logistics, Delivery)",
    "PACKAGING_BOXES": "Packaging (Boxes, Pouches, Bags, Foils)",
    "STAFF_BONUS_OVERTIME": "Wages & Bonuses (Staff Overtime, Temporary Labor)",
    "MARKETING_BANNERS_PAMPHLETS": "Marketing & Promotion (Ads, Banners, Social Campaigns)",
    "FESTIVAL_DECORATION": "Other Costs (Store Decor)",
    "UTILITIES_POWER": "Other Costs (Power & Utilities)",
    "MISCELLANEOUS": "Other Costs (Miscellaneous)"
}


def normalize_category(category: str) -> str:
    """Normalizes category input to valid uppercase key."""
    if not category:
        return "OTHER"
    c_upper = category.strip().upper()
    if c_upper in STANDARD_CATEGORIES:
        return c_upper
    # Partial matching
    if "RENT" in c_upper:
        return "RENT"
    if "TRANSPORT" in c_upper or "FREIGHT" in c_upper or "LOGISTICS" in c_upper:
        return "TRANSPORT"
    if "PACKAG" in c_upper or "BOX" in c_upper:
        return "PACKAGING"
    if "WAGE" in c_upper or "STAFF" in c_upper or "SALAR" in c_upper or "BONUS" in c_upper:
        return "WAGES"
    if "MARKET" in c_upper or "AD" in c_upper or "PROMOT" in c_upper:
        return "MARKETING"
    return "OTHER"


def record_expense(
    amount: float,
    expense_date: str,
    category: str,
    description: Optional[str] = None,
    occurrence_id: Optional[int] = None,
    payment_mode: str = "CASH",
    vendor_name: Optional[str] = None,
    invoice_receipt_no: Optional[str] = None,
    notes: Optional[str] = None,
    created_by: str = "User"
) -> int:
    """
    Records an operational expense with audit logging.
    """
    if amount is None or float(amount) <= 0:
        raise ValueError("Expense amount must be strictly positive (> 0).")

    amt = round(float(amount), 2)
    norm_cat = normalize_category(category)
    desc = (description or notes or "Operating Expense").strip()

    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO expenses (
                expense_category, occurrence_id, expense_date, amount,
                payment_mode, vendor_name, invoice_receipt_no, description, notes, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE')
        """, (
            norm_cat, occurrence_id, expense_date, amt,
            payment_mode, vendor_name, invoice_receipt_no, desc, notes or desc
        ))
        exp_id = cursor.lastrowid

        # Record Create Audit Log
        snapshot = {
            "expense_id": exp_id,
            "category": norm_cat,
            "amount": amt,
            "expense_date": expense_date,
            "occurrence_id": occurrence_id,
            "description": desc,
            "payment_mode": payment_mode,
            "vendor_name": vendor_name,
            "invoice_receipt_no": invoice_receipt_no
        }
        cursor.execute("""
            INSERT INTO expense_audit_logs (expense_id, action, changed_by, new_values, reason)
            VALUES (?, 'CREATE', ?, ?, 'Initial expense entry recorded')
        """, (exp_id, created_by, json.dumps(snapshot)))

        return exp_id


def add_expense(
    expense_category: str,
    expense_date: str,
    amount: float,
    payment_mode: str = "CASH",
    occurrence_id: Optional[int] = None,
    vendor_name: Optional[str] = None,
    invoice_receipt_no: Optional[str] = None,
    notes: Optional[str] = None,
    description: Optional[str] = None
) -> int:
    """Backwards-compatible wrapper around record_expense."""
    return record_expense(
        amount=amount,
        expense_date=expense_date,
        category=expense_category,
        description=description or notes,
        occurrence_id=occurrence_id,
        payment_mode=payment_mode,
        vendor_name=vendor_name,
        invoice_receipt_no=invoice_receipt_no,
        notes=notes
    )


def edit_expense(
    expense_id: int,
    reason: str,
    amount: Optional[float] = None,
    expense_date: Optional[str] = None,
    category: Optional[str] = None,
    description: Optional[str] = None,
    occurrence_id: Optional[int] = None,
    payment_mode: Optional[str] = None,
    vendor_name: Optional[str] = None,
    invoice_receipt_no: Optional[str] = None,
    changed_by: str = "User",
    action_type: str = "CORRECTION"
) -> bool:
    """
    Edits/corrects an existing expense while preserving complete audit history.
    """
    if not reason or not reason.strip():
        raise ValueError("A documented audit reason is required for editing or correcting an expense.")

    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM expenses WHERE expense_id = ?", (expense_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Expense ID {expense_id} not found.")

        old_values = dict(row)
        if old_values.get("status") == "CANCELLED":
            raise ValueError("Cannot edit an expense that has already been cancelled.")

        # Determine new values
        new_amt = round(float(amount), 2) if amount is not None else float(old_values["amount"])
        if new_amt <= 0:
            raise ValueError("Expense amount must be strictly positive (> 0).")

        new_date = expense_date if expense_date is not None else old_values["expense_date"]
        new_cat = normalize_category(category) if category is not None else old_values["expense_category"]
        new_desc = description.strip() if description is not None else (old_values.get("description") or old_values.get("notes") or "")
        new_occ = occurrence_id if occurrence_id is not None else old_values["occurrence_id"]
        new_pay_mode = payment_mode if payment_mode is not None else old_values["payment_mode"]
        new_vendor = vendor_name if vendor_name is not None else old_values["vendor_name"]
        new_receipt = invoice_receipt_no if invoice_receipt_no is not None else old_values["invoice_receipt_no"]

        # Update record
        cursor.execute("""
            UPDATE expenses
            SET amount = ?, expense_date = ?, expense_category = ?, description = ?, notes = ?,
                occurrence_id = ?, payment_mode = ?, vendor_name = ?, invoice_receipt_no = ?,
                status = 'CORRECTED', updated_at = CURRENT_TIMESTAMP
            WHERE expense_id = ?
        """, (
            new_amt, new_date, new_cat, new_desc, new_desc,
            new_occ, new_pay_mode, new_vendor, new_receipt,
            expense_id
        ))

        new_values = {
            "expense_id": expense_id,
            "category": new_cat,
            "amount": new_amt,
            "expense_date": new_date,
            "occurrence_id": new_occ,
            "description": new_desc,
            "payment_mode": new_pay_mode,
            "vendor_name": new_vendor,
            "invoice_receipt_no": new_receipt,
            "status": "CORRECTED"
        }

        # Log audit correction
        cursor.execute("""
            INSERT INTO expense_audit_logs (expense_id, action, changed_by, previous_values, new_values, reason)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            expense_id, action_type, changed_by,
            json.dumps(old_values), json.dumps(new_values), reason.strip()
        ))

        return True


def cancel_expense(
    expense_id: int,
    reason: str,
    cancelled_by: str = "User"
) -> bool:
    """
    Cancels an expense, recording the cancellation reason in audit history.
    Cancelled expenses are preserved for compliance but excluded from P&L statements.
    """
    if not reason or not reason.strip():
        raise ValueError("A documented audit reason is required to cancel an expense.")

    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM expenses WHERE expense_id = ?", (expense_id,))
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"Expense ID {expense_id} not found.")

        old_values = dict(row)
        cursor.execute("""
            UPDATE expenses
            SET status = 'CANCELLED', updated_at = CURRENT_TIMESTAMP
            WHERE expense_id = ?
        """, (expense_id,))

        cursor.execute("""
            INSERT INTO expense_audit_logs (expense_id, action, changed_by, previous_values, new_values, reason)
            VALUES (?, 'CANCEL', ?, ?, ?, ?)
        """, (
            expense_id, cancelled_by,
            json.dumps(old_values), json.dumps({"status": "CANCELLED"}), reason.strip()
        ))

        return True


def get_expense_audit_trail(expense_id: int) -> List[Dict[str, Any]]:
    """Fetches complete audit revision trail for a specific expense."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT audit_id, expense_id, action, changed_by, previous_values, new_values, reason, changed_at
            FROM expense_audit_logs
            WHERE expense_id = ?
            ORDER BY audit_id ASC
        """, (expense_id,))
        rows = [dict(r) for r in cursor.fetchall()]
        for r in rows:
            if r["previous_values"]:
                try:
                    r["previous_values"] = json.loads(r["previous_values"])
                except Exception:
                    pass
            if r["new_values"]:
                try:
                    r["new_values"] = json.loads(r["new_values"])
                except Exception:
                    pass
        return rows
    finally:
        conn.close()


def get_financial_pnl_statement(
    occurrence_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    category_filter: Optional[str] = None,
    include_general_overheads: bool = True,
    include_spoilage: bool = False
) -> Dict[str, Any]:
    """
    Computes deterministic, auditable Profit & Loss (P&L) statement.

    Documented Mathematical Formulas:
      Gross Billed Revenue = SUM(invoice.subtotal_amount)
      Trade Discounts = SUM(invoice.discount_amount)
      Gross Taxable Sales = SUM(invoice.total_taxable_amount) = Gross Billed Revenue - Trade Discounts
      Returns Refund Taxable = SUM(sales_returns.refund_amount - sales_returns.tax_refund_amount)
      Net Sales Revenue = Gross Taxable Sales - Returns Refund Taxable

      COGS (Cost of Goods Sold) = SUM(sales_items.unit_cost_price * sales_items.quantity)
        - Uses actual recorded snapshot unit cost prices at time of sale.
        - Preserved when product catalog purchase costs subsequently change.
      Returned COGS = SUM(sales_items.unit_cost_price * sales_returns.quantity)
      Net COGS = COGS - Returned COGS

      Gross Profit = Net Sales Revenue - Net COGS
      Gross Margin % = (Gross Profit / Net Sales Revenue) * 100

      Included Expenses = SUM(expenses.amount WHERE status != 'CANCELLED' AND matches_filters)
      Net Operating Profit = Gross Profit - Included Expenses - Spoilage Loss
      Net Margin % = (Net Operating Profit / Net Sales Revenue) * 100

    Calculates net operating profit only when relevant expenses are included,
    and explicitly lists all labeled exclusions.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # -------------------------------------------------------------
        # 1. SALES REVENUE & DISCOUNTS
        # -------------------------------------------------------------
        sales_sql = """
            SELECT 
                COALESCE(SUM(inv.subtotal_amount), 0) AS gross_billed,
                COALESCE(SUM(inv.discount_amount), 0) AS total_discounts,
                COALESCE(SUM(inv.total_taxable_amount), 0) AS gross_taxable_revenue,
                COALESCE(SUM(inv.cgst_amount + inv.sgst_amount + inv.igst_amount), 0) AS total_gst_collected,
                COALESCE(SUM(inv.net_total_amount), 0) AS total_customer_receipts,
                COUNT(DISTINCT inv.invoice_id) AS invoice_count
            FROM sales_invoices inv
            WHERE inv.status = 'COMPLETED'
        """
        sales_params: List[Any] = []
        if occurrence_id:
            sales_sql += " AND inv.occurrence_id = ?"
            sales_params.append(occurrence_id)
        if start_date:
            sales_sql += " AND inv.invoice_date >= ?"
            sales_params.append(start_date)
        if end_date:
            sales_sql += " AND inv.invoice_date <= ?"
            sales_params.append(end_date)

        cursor.execute(sales_sql, tuple(sales_params))
        s_row = cursor.fetchone()

        gross_billed = float(s_row["gross_billed"]) if s_row else 0.0
        total_discounts = float(s_row["total_discounts"]) if s_row else 0.0
        gross_taxable_revenue = float(s_row["gross_taxable_revenue"]) if s_row else 0.0
        invoice_count = int(s_row["invoice_count"]) if s_row else 0

        # -------------------------------------------------------------
        # 2. COST OF GOODS SOLD (COGS) USING HISTORICAL COST SNAPSHOTS
        # -------------------------------------------------------------
        cogs_sql = """
            SELECT 
                COALESCE(SUM(si.unit_cost_price * si.quantity), 0) AS gross_cogs,
                COALESCE(SUM(si.quantity), 0) AS total_units_sold
            FROM sales_items si
            JOIN sales_invoices inv ON si.invoice_id = inv.invoice_id
            WHERE inv.status = 'COMPLETED'
        """
        cogs_params: List[Any] = []
        if occurrence_id:
            cogs_sql += " AND inv.occurrence_id = ?"
            cogs_params.append(occurrence_id)
        if start_date:
            cogs_sql += " AND inv.invoice_date >= ?"
            cogs_params.append(start_date)
        if end_date:
            cogs_sql += " AND inv.invoice_date <= ?"
            cogs_params.append(end_date)

        cursor.execute(cogs_sql, tuple(cogs_params))
        c_row = cursor.fetchone()
        gross_cogs = float(c_row["gross_cogs"]) if c_row else 0.0
        total_units_sold = int(c_row["total_units_sold"]) if c_row else 0

        # -------------------------------------------------------------
        # 3. SALES RETURNS & REVERSALS ADJUSTMENT
        # -------------------------------------------------------------
        returns_sql = """
            SELECT 
                COALESCE(SUM(sr.refund_amount), 0) AS total_refunded_gross,
                COALESCE(SUM(sr.tax_refund_amount), 0) AS total_tax_refunded,
                COALESCE(SUM(si.unit_cost_price * sr.quantity), 0) AS returned_cogs,
                COALESCE(SUM(sr.quantity), 0) AS returned_units_count,
                COUNT(sr.return_id) AS return_tx_count
            FROM sales_returns sr
            JOIN sales_invoices inv ON sr.invoice_id = inv.invoice_id
            LEFT JOIN sales_items si ON sr.item_id = si.item_id
            WHERE inv.status = 'COMPLETED'
        """
        returns_params: List[Any] = []
        if occurrence_id:
            returns_sql += " AND inv.occurrence_id = ?"
            returns_params.append(occurrence_id)
        if start_date:
            returns_sql += " AND sr.return_date >= ?"
            returns_params.append(start_date)
        if end_date:
            returns_sql += " AND sr.return_date <= ?"
            returns_params.append(end_date)

        cursor.execute(returns_sql, tuple(returns_params))
        r_row = cursor.fetchone()

        total_refunded_gross = float(r_row["total_refunded_gross"]) if r_row else 0.0
        total_tax_refunded = float(r_row["total_tax_refunded"]) if r_row else 0.0
        returned_taxable_sales = round(total_refunded_gross - total_tax_refunded, 2)
        returned_cogs = float(r_row["returned_cogs"]) if r_row else 0.0
        returned_units_count = int(r_row["returned_units_count"]) if r_row else 0

        # Net Sales Revenue and Net COGS
        net_sales_revenue = max(0.0, round(gross_taxable_revenue - returned_taxable_sales, 2))
        net_cogs = max(0.0, round(gross_cogs - returned_cogs, 2))
        net_units_sold = max(0, total_units_sold - returned_units_count)

        # Gross Profit
        gross_profit = round(net_sales_revenue - net_cogs, 2)
        gross_margin_pct = round((gross_profit / net_sales_revenue * 100.0), 2) if net_sales_revenue > 0 else 0.0

        # -------------------------------------------------------------
        # 4. OPERATING EXPENSES & LABELED EXCLUSIONS
        # -------------------------------------------------------------
        # Fetch all candidate expenses in scope to evaluate inclusions and exclusions
        all_exp_sql = "SELECT * FROM expenses WHERE 1=1"
        all_exp_params: List[Any] = []

        if start_date:
            all_exp_sql += " AND expense_date >= ?"
            all_exp_params.append(start_date)
        if end_date:
            all_exp_sql += " AND expense_date <= ?"
            all_exp_params.append(end_date)

        cursor.execute(all_exp_sql, tuple(all_exp_params))
        candidate_expenses = [dict(r) for r in cursor.fetchall()]

        included_expenses: List[Dict[str, Any]] = []
        labeled_exclusions: List[Dict[str, Any]] = []
        total_included_expenses = 0.0
        total_excluded_expenses = 0.0

        for exp in candidate_expenses:
            amt = float(exp["amount"])
            cat = exp["expense_category"]
            exp_status = exp.get("status", "ACTIVE")
            occ = exp["occurrence_id"]

            # Exclusion Case 1: Cancelled expense
            if exp_status == "CANCELLED":
                labeled_exclusions.append({
                    "expense_id": exp["expense_id"],
                    "category": cat,
                    "description": exp.get("description") or exp.get("notes") or "Cancelled Expense",
                    "amount": amt,
                    "reason": "Cancelled audit record; excluded from operating costs"
                })
                total_excluded_expenses += amt
                continue

            # Exclusion Case 2: Specific category filter applied
            if category_filter and normalize_category(cat) != normalize_category(category_filter):
                labeled_exclusions.append({
                    "expense_id": exp["expense_id"],
                    "category": cat,
                    "description": exp.get("description") or exp.get("notes") or "",
                    "amount": amt,
                    "reason": f"Excluded by active category filter (Filtering only for {category_filter})"
                })
                total_excluded_expenses += amt
                continue

            # Exclusion Case 3: Festival occurrence filter
            if occurrence_id is not None:
                if occ != occurrence_id:
                    # General overhead not tagged to this festival
                    if occ is None and not include_general_overheads:
                        labeled_exclusions.append({
                            "expense_id": exp["expense_id"],
                            "category": cat,
                            "description": exp.get("description") or exp.get("notes") or "",
                            "amount": amt,
                            "reason": "General store overhead not tagged to this festival campaign"
                        })
                        total_excluded_expenses += amt
                        continue
                    elif occ is not None:
                        # Belongs to a different festival
                        labeled_exclusions.append({
                            "expense_id": exp["expense_id"],
                            "category": cat,
                            "description": exp.get("description") or exp.get("notes") or "",
                            "amount": amt,
                            "reason": f"Tagged to different festival occurrence #{occ}"
                        })
                        total_excluded_expenses += amt
                        continue

            # Expense is INCLUDED in P&L
            included_expenses.append(exp)
            total_included_expenses += amt

        total_included_expenses = round(total_included_expenses, 2)
        total_excluded_expenses = round(total_excluded_expenses, 2)

        # Breakdown of included expenses by category
        exp_breakdown: Dict[str, float] = {}
        for ie in included_expenses:
            c = normalize_category(ie["expense_category"])
            exp_breakdown[c] = round(exp_breakdown.get(c, 0.0) + float(ie["amount"]), 2)

        # -------------------------------------------------------------
        # 5. SPOILAGE & DAMAGED STOCK LOSSES (OPTIONAL / SCOPED)
        # -------------------------------------------------------------
        spoilage_loss = 0.0
        if include_spoilage:
            loss_start = start_date
            loss_end = end_date
            if occurrence_id and not (loss_start and loss_end):
                cursor.execute("SELECT campaign_start_date, campaign_end_date FROM festival_occurrences WHERE occurrence_id = ?", (occurrence_id,))
                occ_dates = cursor.fetchone()
                if occ_dates:
                    if not loss_start:
                        loss_start = occ_dates["campaign_start_date"]
                    if not loss_end:
                        loss_end = occ_dates["campaign_end_date"]

            loss_sql = """
                SELECT COALESCE(SUM(cost_impact), 0) AS total_loss
                FROM stock_adjustments
                WHERE adjustment_type IN ('DAMAGE', 'EXPIRED', 'THEFT_SHRINKAGE')
            """
            loss_params: List[Any] = []
            if loss_start:
                loss_sql += " AND adjustment_date >= ?"
                loss_params.append(loss_start)
            if loss_end:
                loss_sql += " AND adjustment_date <= ?"
                loss_params.append(loss_end)

            cursor.execute(loss_sql, tuple(loss_params))
            loss_row = cursor.fetchone()
            spoilage_loss = round(float(loss_row["total_loss"]), 2) if loss_row else 0.0

        # -------------------------------------------------------------
        # 6. NET OPERATING PROFIT
        # -------------------------------------------------------------
        net_operating_profit = round(gross_profit - total_included_expenses - spoilage_loss, 2)
        net_margin_pct = round((net_operating_profit / net_sales_revenue * 100.0), 2) if net_sales_revenue > 0 else 0.0

        total_operating_capital = round(net_cogs + total_included_expenses, 2)
        operating_roi_pct = round((net_operating_profit / total_operating_capital * 100.0), 2) if total_operating_capital > 0 else 0.0

        # Documentation of formulas
        documented_formulas = {
            "Gross Billed Sales": "SUM(invoices.subtotal_amount)",
            "Discounts": "SUM(invoices.discount_amount)",
            "Net Sales Revenue": "(Gross Billed - Discounts) - (Customer Returns Net Taxable Refunds)",
            "Cost of Goods Sold (COGS)": "SUM(sales_items.unit_cost_price * sales_items.quantity) - Returned COGS [Immutable Snapshot Costs]",
            "Gross Profit": "Net Sales Revenue - Net COGS",
            "Gross Margin %": "(Gross Profit / Net Sales Revenue) * 100",
            "Net Operating Profit": "Gross Profit - Total Included Operating Expenses" + (" - Spoilage Losses" if include_spoilage else ""),
            "Net Operating Margin %": "(Net Operating Profit / Net Sales Revenue) * 100",
            "Return on Investment (ROI %)": "(Net Operating Profit / (Net COGS + Included Operating Expenses)) * 100"
        }

        return {
            "occurrence_id": occurrence_id,
            "start_date": start_date,
            "end_date": end_date,
            "gross_billed": gross_billed,
            "total_discounts": total_discounts,
            "gross_taxable_revenue": gross_taxable_revenue,
            "returns": {
                "total_refunded_gross": total_refunded_gross,
                "total_tax_refunded": total_tax_refunded,
                "net_taxable_returns": returned_taxable_sales,
                "returned_cogs": returned_cogs,
                "returned_units_count": returned_units_count
            },
            "net_sales_revenue": net_sales_revenue,
            "net_taxable_revenue": net_sales_revenue,  # Backwards compatibility key
            "invoice_count": invoice_count,
            "total_units_sold": net_units_sold,
            "gross_cogs": gross_cogs,
            "net_cogs": net_cogs,
            "total_cogs": net_cogs,  # Backwards compatibility key
            "gross_profit": gross_profit,
            "gross_margin_pct": gross_margin_pct,
            "total_expenses": total_included_expenses,  # Backwards compatibility key
            "total_included_expenses": total_included_expenses,
            "total_excluded_expenses": total_excluded_expenses,
            "spoilage_loss": spoilage_loss,
            "net_profit": net_operating_profit,  # Backwards compatibility key
            "net_operating_profit": net_operating_profit,
            "net_margin_pct": net_margin_pct,
            "festival_roi_pct": operating_roi_pct,
            "expense_breakdown": [{"expense_category": k, "category_total": v} for k, v in exp_breakdown.items()],
            "included_expenses": included_expenses,
            "labeled_exclusions": labeled_exclusions,
            "documented_formulas": documented_formulas,
            "has_exclusions": len(labeled_exclusions) > 0,
            "target_revenue": 0.0,
            "target_profit": 0.0,
            "budgeted_expenses": 0.0
        }
    finally:
        conn.close()


def get_festival_pnl_statement(occurrence_id: int) -> Dict[str, Any]:
    """
    Backwards compatible wrapper for festival P&L statement.
    Calculates sales revenue, discounts, historical snapshot COGS, returns, and labeled exclusions.
    """
    # Fetch campaign dates for targeted expense scope
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT campaign_start_date, campaign_end_date FROM festival_occurrences WHERE occurrence_id = ?", (occurrence_id,))
        occ_row = cursor.fetchone()
        s_date = str(occ_row["campaign_start_date"]) if occ_row else None
        e_date = str(occ_row["campaign_end_date"]) if occ_row else None

        # Fetch targets if any
        cursor.execute("""
            SELECT COALESCE(SUM(target_revenue), 0) AS target_rev,
                   COALESCE(SUM(target_profit), 0) AS target_prof,
                   COALESCE(SUM(budgeted_expenses), 0) AS target_exp
            FROM festival_sales_targets
            WHERE occurrence_id = ?
        """, (occurrence_id,))
        t_row = cursor.fetchone()
    finally:
        conn.close()

    pnl = get_financial_pnl_statement(
        occurrence_id=occurrence_id,
        start_date=s_date,
        end_date=e_date,
        include_general_overheads=False
    )
    if t_row:
        pnl["target_revenue"] = float(t_row["target_rev"])
        pnl["target_profit"] = float(t_row["target_prof"])
        pnl["budgeted_expenses"] = float(t_row["target_exp"])

    return pnl
