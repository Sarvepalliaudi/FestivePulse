"""
FestivePulse — High-Performance Parameterized SQL Queries & Analytic Aggregations
"""

import json
from typing import Optional, Dict, Any
import pandas as pd
from database.connection import query_df, get_db_connection


def get_business_settings() -> Dict[str, Any]:
    df = query_df("SELECT * FROM business_settings WHERE setting_id = 1")
    if not df.empty:
        return df.iloc[0].to_dict()
    return {}


def update_business_settings(
    business_name: str,
    trade_name: Optional[str] = "",
    phone: str = "",
    email: Optional[str] = "",
    gstin: Optional[str] = "",
    address_line1: str = "",
    address_line2: Optional[str] = "",
    city: str = "",
    state: str = "",
    state_code: str = "",
    pincode: str = "",
    primary_region: str = "Pan-India",
    timezone: str = "Asia/Kolkata",
    currency_display: str = "INR (₹)",
    report_footer_notes: str = "FestivePulse AI — Local SQLite Database System Record",
    report_page_orientation: str = "landscape",
    max_upload_size_mb: int = 10
) -> bool:
    """Updates business profile, regional localization, currency, timezone, and report settings using parameterized SQL."""
    from database.connection import db_session
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE business_settings
            SET business_name = ?,
                trade_name = ?,
                phone = ?,
                email = ?,
                gstin = ?,
                address_line1 = ?,
                address_line2 = ?,
                city = ?,
                state = ?,
                state_code = ?,
                pincode = ?,
                primary_region = ?,
                timezone = ?,
                currency_display = ?,
                report_footer_notes = ?,
                report_page_orientation = ?,
                max_upload_size_mb = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE setting_id = 1
        """, (
            business_name,
            trade_name or "",
            phone,
            email or "",
            (gstin or "").upper(),
            address_line1,
            address_line2 or "",
            city,
            state,
            state_code,
            pincode,
            primary_region,
            timezone,
            currency_display,
            report_footer_notes,
            report_page_orientation,
            max_upload_size_mb
        ))
        return cursor.rowcount > 0


def get_active_festival_occurrence() -> Optional[Dict[str, Any]]:
    sql = """
        SELECT o.*, f.festival_name, f.festival_code, f.typical_surge_multiplier, f.primary_regions
        FROM festival_occurrences o
        JOIN festivals f ON o.festival_id = f.festival_id
        WHERE o.is_current_active = 1
        LIMIT 1
    """
    df = query_df(sql)
    if not df.empty:
        row = df.iloc[0].to_dict()
        try:
            row["primary_regions"] = json.loads(row["primary_regions"])
        except Exception:
            row["primary_regions"] = []
        return row
    return None


def get_all_festival_occurrences(year: Optional[int] = None) -> pd.DataFrame:
    if year:
        sql = """
            SELECT o.*, f.festival_name, f.festival_code, f.typical_surge_multiplier
            FROM festival_occurrences o
            JOIN festivals f ON o.festival_id = f.festival_id
            WHERE o.year = ?
            ORDER BY o.festival_date ASC
        """
        return query_df(sql, (year,))
    else:
        sql = """
            SELECT o.*, f.festival_name, f.festival_code, f.typical_surge_multiplier
            FROM festival_occurrences o
            JOIN festivals f ON o.festival_id = f.festival_id
            ORDER BY o.year DESC, o.festival_date ASC
        """
        return query_df(sql)


def get_categories() -> pd.DataFrame:
    return query_df("SELECT * FROM product_categories ORDER BY category_name ASC")


def get_suppliers(only_active: bool = True) -> pd.DataFrame:
    if only_active:
        return query_df("SELECT * FROM suppliers WHERE is_active = 1 ORDER BY supplier_name ASC")
    return query_df("SELECT * FROM suppliers ORDER BY supplier_name ASC")


def get_products_with_stock(category_id: Optional[int] = None, festival_tag: Optional[str] = None, search: Optional[str] = None) -> pd.DataFrame:
    sql = """
        SELECT 
            p.product_id, p.sku, p.barcode, p.product_name, p.category_id,
            c.category_name, p.unit_of_measure, p.cost_price, p.selling_price, p.mrp,
            p.gst_rate, p.hsn_code, p.min_safety_stock, p.reorder_quantity,
            p.is_perishable, p.shelf_life_days, p.festival_tags, p.is_active,
            COALESCE(SUM(b.quantity_available), 0) AS current_stock,
            CASE 
                WHEN COALESCE(SUM(b.quantity_available), 0) = 0 THEN 'OUT_OF_STOCK'
                WHEN COALESCE(SUM(b.quantity_available), 0) <= p.min_safety_stock THEN 'CRITICAL'
                WHEN COALESCE(SUM(b.quantity_available), 0) > (p.min_safety_stock + p.reorder_quantity * 2) THEN 'OVERSTOCKED'
                ELSE 'ADEQUATE'
            END AS stock_status
        FROM products p
        JOIN product_categories c ON p.category_id = c.category_id
        LEFT JOIN inventory_batches b ON p.product_id = b.product_id AND (b.expiry_date IS NULL OR b.expiry_date >= DATE('now'))
        WHERE p.is_active = 1
    """
    params = []
    if category_id:
        sql += " AND p.category_id = ?"
        params.append(category_id)
    if search:
        sql += " AND (p.product_name LIKE ? OR p.sku LIKE ? OR p.barcode LIKE ?)"
        term = f"%{search}%"
        params.extend([term, term, term])
    
    sql += " GROUP BY p.product_id ORDER BY p.product_name ASC"
    df = query_df(sql, tuple(params))

    if festival_tag and not df.empty:
        # Filter in pandas for festival_tags JSON string containing the tag
        df = df[df["festival_tags"].str.contains(festival_tag, na=False, regex=False)]

    return df


def get_batches_for_product(product_id: int) -> pd.DataFrame:
    sql = """
        SELECT b.*, s.supplier_name,
               CASE 
                   WHEN b.expiry_date IS NULL THEN NULL
                   ELSE CAST(JULIANDAY(b.expiry_date) - JULIANDAY('now') AS INTEGER)
               END AS days_to_expiry
        FROM inventory_batches b
        LEFT JOIN suppliers s ON b.supplier_id = s.supplier_id
        WHERE b.product_id = ?
        ORDER BY b.expiry_date ASC, b.received_date ASC
    """
    return query_df(sql, (product_id,))


def get_expiring_batches(within_days: int = 15) -> pd.DataFrame:
    sql = """
        SELECT b.*, p.product_name, p.sku, p.unit_of_measure,
               CAST(JULIANDAY(b.expiry_date) - JULIANDAY('now') AS INTEGER) AS days_to_expiry
        FROM inventory_batches b
        JOIN products p ON b.product_id = p.product_id
        WHERE b.expiry_date IS NOT NULL 
          AND b.quantity_available > 0
          AND b.expiry_date <= DATE('now', '+' || ? || ' days')
        ORDER BY b.expiry_date ASC
    """
    return query_df(sql, (within_days,))


def get_dashboard_metrics(occurrence_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Computes key performance indicators for the active festival or all-time.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        occ_filter = "WHERE occurrence_id = ?" if occurrence_id else "WHERE 1=1"
        params = (occurrence_id,) if occurrence_id else ()

        # 1. Total Revenue & Invoices
        cursor.execute(f"""
            SELECT 
                COALESCE(SUM(net_total_amount), 0) AS total_revenue,
                COALESCE(SUM(total_taxable_amount), 0) AS taxable_sales,
                COALESCE(SUM(cgst_amount + sgst_amount + igst_amount), 0) AS total_tax,
                COUNT(invoice_id) AS total_invoices
            FROM sales_invoices
            {occ_filter} AND status = 'COMPLETED'
        """, params)
        rev_row = cursor.fetchone()

        # 2. Total COGS and Gross Profit
        items_filter = "WHERE inv.occurrence_id = ?" if occurrence_id else "WHERE 1=1"
        cursor.execute(f"""
            SELECT 
                COALESCE(SUM(si.unit_cost_price * si.quantity), 0) AS total_cogs,
                COALESCE(SUM(si.gross_profit), 0) AS gross_profit
            FROM sales_items si
            JOIN sales_invoices inv ON si.invoice_id = inv.invoice_id
            {items_filter} AND inv.status = 'COMPLETED'
        """, params)
        cogs_row = cursor.fetchone()

        # 3. Total Expenses
        exp_filter = "WHERE occurrence_id = ?" if occurrence_id else "WHERE 1=1"
        cursor.execute(f"""
            SELECT COALESCE(SUM(amount), 0) AS total_expenses
            FROM expenses
            {exp_filter}
        """, params)
        exp_row = cursor.fetchone()

        # 4. Critical Stock Alert Count
        cursor.execute("""
            SELECT COUNT(*) AS critical_count
            FROM (
                SELECT p.product_id, p.min_safety_stock, COALESCE(SUM(b.quantity_available), 0) AS stock
                FROM products p
                LEFT JOIN inventory_batches b ON p.product_id = b.product_id
                WHERE p.is_active = 1
                GROUP BY p.product_id
                HAVING stock <= p.min_safety_stock
            )
        """)
        crit_row = cursor.fetchone()

        # 5. Target comparison
        target_revenue = 0.0
        if occurrence_id:
            cursor.execute("SELECT COALESCE(SUM(target_revenue), 0) FROM festival_sales_targets WHERE occurrence_id = ?", (occurrence_id,))
            target_revenue = cursor.fetchone()[0] or 0.0

        total_rev = float(rev_row["total_revenue"])
        total_cogs = float(cogs_row["total_cogs"])
        gross_profit = float(cogs_row["gross_profit"])
        total_expenses = float(exp_row["total_expenses"])
        net_profit = gross_profit - total_expenses
        roi_pct = (net_profit / (total_cogs + total_expenses) * 100.0) if (total_cogs + total_expenses) > 0 else 0.0

        return {
            "total_revenue": total_rev,
            "taxable_sales": float(rev_row["taxable_sales"]),
            "total_tax": float(rev_row["total_tax"]),
            "total_invoices": int(rev_row["total_invoices"]),
            "total_cogs": total_cogs,
            "gross_profit": gross_profit,
            "gross_margin_pct": (gross_profit / total_rev * 100.0) if total_rev > 0 else 0.0,
            "total_expenses": total_expenses,
            "net_profit": net_profit,
            "festival_roi_pct": roi_pct,
            "critical_stock_count": int(crit_row["critical_count"]),
            "target_revenue": target_revenue,
            "target_completion_pct": (total_rev / target_revenue * 100.0) if target_revenue > 0 else 0.0
        }
    finally:
        conn.close()


def get_sales_trend(occurrence_id: Optional[int] = None) -> pd.DataFrame:
    sql = """
        SELECT invoice_date, 
               COUNT(invoice_id) AS invoice_count,
               SUM(net_total_amount) AS daily_revenue,
               SUM(total_taxable_amount) AS taxable_amount
        FROM sales_invoices
        WHERE status = 'COMPLETED'
    """
    params = []
    if occurrence_id:
        sql += " AND occurrence_id = ?"
        params.append(occurrence_id)
    sql += " GROUP BY invoice_date ORDER BY invoice_date ASC"
    return query_df(sql, tuple(params))


def get_sales_by_category(occurrence_id: Optional[int] = None) -> pd.DataFrame:
    sql = """
        SELECT c.category_name,
               SUM(si.quantity) AS total_units_sold,
               SUM(si.taxable_value) AS total_revenue,
               SUM(si.gross_profit) AS total_profit
        FROM sales_items si
        JOIN products p ON si.product_id = p.product_id
        JOIN product_categories c ON p.category_id = c.category_id
        JOIN sales_invoices inv ON si.invoice_id = inv.invoice_id
        WHERE inv.status = 'COMPLETED'
    """
    params = []
    if occurrence_id:
        sql += " AND inv.occurrence_id = ?"
        params.append(occurrence_id)
    sql += " GROUP BY c.category_id ORDER BY total_revenue DESC"
    return query_df(sql, tuple(params))


def get_sales_by_payment_mode(occurrence_id: Optional[int] = None) -> pd.DataFrame:
    sql = """
        SELECT payment_mode, 
               COUNT(invoice_id) AS invoice_count,
               SUM(net_total_amount) AS total_collected
        FROM sales_invoices
        WHERE status = 'COMPLETED'
    """
    params = []
    if occurrence_id:
        sql += " AND occurrence_id = ?"
        params.append(occurrence_id)
    sql += " GROUP BY payment_mode ORDER BY total_collected DESC"
    return query_df(sql, tuple(params))


def get_recent_invoices(limit: int = 10, occurrence_id: Optional[int] = None) -> pd.DataFrame:
    sql = """
        SELECT inv.invoice_id, inv.invoice_number, inv.invoice_date,
               COALESCE(cust.customer_name, 'Cash / Walk-in') AS customer_name,
               inv.payment_mode, inv.net_total_amount, inv.status
        FROM sales_invoices inv
        LEFT JOIN customers cust ON inv.customer_id = cust.customer_id
        WHERE 1=1
    """
    params = []
    if occurrence_id:
        sql += " AND inv.occurrence_id = ?"
        params.append(occurrence_id)
    sql += " ORDER BY inv.invoice_date DESC, inv.invoice_id DESC LIMIT ?"
    params.append(limit)
    return query_df(sql, tuple(params))
