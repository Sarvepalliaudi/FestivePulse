"""
FestivePulse — Dashboard Analytics Service
Computes real-time executive retail KPIs, chart series, and inventory status
strictly using actual SQLite records without hardcoding or fabricated data.
"""

from datetime import date, datetime, timedelta
from typing import Optional, Dict, Any, List
import pandas as pd
from database.connection import get_db_connection, query_df


def parse_filter_date(val: Any) -> Optional[str]:
    """Helper to safely format dates into YYYY-MM-DD strings."""
    if val is None:
        return None
    if isinstance(val, (datetime, date)):
        return val.strftime("%Y-%m-%d")
    s = str(val).strip()
    return s if s else None


def check_database_state() -> Dict[str, Any]:
    """
    Inspects actual SQLite database to determine if it is completely empty,
    partially configured, or contains demonstration sample data.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # Product count
        cursor.execute("SELECT COUNT(*) FROM products")
        product_count = cursor.fetchone()[0]

        # Invoice count
        cursor.execute("SELECT COUNT(*) FROM sales_invoices")
        invoice_count = cursor.fetchone()[0]

        # Festival calendar count
        cursor.execute("SELECT COUNT(*) FROM festival_calendar")
        calendar_count = cursor.fetchone()[0]

        # Check for sample data indicators
        cursor.execute("SELECT trade_name FROM business_settings WHERE setting_id = 1")
        row = cursor.fetchone()
        trade_name = row[0] if row else ""
        
        cursor.execute("SELECT COUNT(*) FROM sales_invoices WHERE invoice_number LIKE 'INV-202526-%' OR invoice_number LIKE 'INV-2025-%' OR invoice_number LIKE 'INV-2026-%'")
        sample_inv_count = cursor.fetchone()[0]

        is_sample_data = (trade_name == "FestivePulse Retailers") or (sample_inv_count > 0)
        is_empty = (product_count == 0) and (invoice_count == 0)

        return {
            "is_empty": is_empty,
            "product_count": product_count,
            "invoice_count": invoice_count,
            "calendar_count": calendar_count,
            "is_sample_data": is_sample_data,
            "sample_label": "Sample Retail Demonstration Data (Shree Ganesh Utsav Bhandar & Festive Emporium)" if is_sample_data else None
        }
    finally:
        conn.close()


def get_dashboard_kpis(
    start_date: Optional[Any] = None,
    end_date: Optional[Any] = None,
    category_id: Optional[int] = None,
    product_id: Optional[int] = None,
    reference_date: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Calculates actual KPIs strictly from SQLite database records:
    1. Total Sales (net of returns, completed invoices only)
    2. Sales This Month (completed sales in current month)
    3. Gross Profit (where cost data is available)
    4. Current Inventory Value (active stock on hand valuation)
    5. Low-Stock Product Count (stock <= safety stock)
    6. Upcoming Configured Festivals
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        ref_d = datetime.strptime(str(reference_date), "%Y-%m-%d").date() if reference_date else date.today()
        cur_month_start = date(ref_d.year, ref_d.month, 1).strftime("%Y-%m-%d")
        # Last day of current month
        if ref_d.month == 12:
            next_month = date(ref_d.year + 1, 1, 1)
        else:
            next_month = date(ref_d.year, ref_d.month + 1, 1)
        cur_month_end = (next_month - timedelta(days=1)).strftime("%Y-%m-%d")

        s_date = parse_filter_date(start_date)
        e_date = parse_filter_date(end_date)

        # -------------------------------------------------------------
        # 1. TOTAL SALES & SALES THIS MONTH
        # -------------------------------------------------------------
        # Base filter conditions
        invoice_conditions = ["inv.status = 'COMPLETED'"]
        params: List[Any] = []

        if s_date:
            invoice_conditions.append("inv.invoice_date >= ?")
            params.append(s_date)
        if e_date:
            invoice_conditions.append("inv.invoice_date <= ?")
            params.append(e_date)

        where_clause = " AND ".join(invoice_conditions)

        # Check if product or category filter is active
        if product_id:
            sales_sql = f"""
                SELECT 
                    COALESCE(SUM(si.total_item_amount), 0) AS gross_sales,
                    COUNT(DISTINCT inv.invoice_id) AS invoice_count
                FROM sales_items si
                JOIN sales_invoices inv ON si.invoice_id = inv.invoice_id
                WHERE {where_clause} AND si.product_id = ?
            """
            cursor.execute(sales_sql, tuple(params + [product_id]))
            sales_res = cursor.fetchone()
            gross_sales = float(sales_res["gross_sales"])
            inv_count = int(sales_res["invoice_count"])

            # Returns for this product
            ret_conditions = ["r.product_id = ?"]
            ret_params = [product_id]
            if s_date:
                ret_conditions.append("r.return_date >= ?")
                ret_params.append(s_date)
            if e_date:
                ret_conditions.append("r.return_date <= ?")
                ret_params.append(e_date)
            ret_sql = f"SELECT COALESCE(SUM(refund_amount), 0) FROM sales_returns r WHERE {' AND '.join(ret_conditions)}"
            cursor.execute(ret_sql, tuple(ret_params))
            returns_amt = float(cursor.fetchone()[0] or 0.0)

        elif category_id:
            sales_sql = f"""
                SELECT 
                    COALESCE(SUM(si.total_item_amount), 0) AS gross_sales,
                    COUNT(DISTINCT inv.invoice_id) AS invoice_count
                FROM sales_items si
                JOIN sales_invoices inv ON si.invoice_id = inv.invoice_id
                JOIN products p ON si.product_id = p.product_id
                WHERE {where_clause} AND p.category_id = ?
            """
            cursor.execute(sales_sql, tuple(params + [category_id]))
            sales_res = cursor.fetchone()
            gross_sales = float(sales_res["gross_sales"])
            inv_count = int(sales_res["invoice_count"])

            # Returns for this category
            ret_conditions = ["p.category_id = ?"]
            ret_params = [category_id]
            if s_date:
                ret_conditions.append("r.return_date >= ?")
                ret_params.append(s_date)
            if e_date:
                ret_conditions.append("r.return_date <= ?")
                ret_params.append(e_date)
            ret_sql = f"""
                SELECT COALESCE(SUM(r.refund_amount), 0)
                FROM sales_returns r
                JOIN products p ON r.product_id = p.product_id
                WHERE {' AND '.join(ret_conditions)}
            """
            cursor.execute(ret_sql, tuple(ret_params))
            returns_amt = float(cursor.fetchone()[0] or 0.0)

        else:
            # Entire store sales
            sales_sql = f"""
                SELECT 
                    COALESCE(SUM(net_total_amount), 0) AS gross_sales,
                    COUNT(invoice_id) AS invoice_count
                FROM sales_invoices inv
                WHERE {where_clause}
            """
            cursor.execute(sales_sql, tuple(params))
            sales_res = cursor.fetchone()
            gross_sales = float(sales_res["gross_sales"])
            inv_count = int(sales_res["invoice_count"])

            # Returns overall
            ret_conditions = ["1=1"]
            ret_params = []
            if s_date:
                ret_conditions.append("return_date >= ?")
                ret_params.append(s_date)
            if e_date:
                ret_conditions.append("return_date <= ?")
                ret_params.append(e_date)
            ret_sql = f"SELECT COALESCE(SUM(refund_amount), 0) FROM sales_returns WHERE {' AND '.join(ret_conditions)}"
            cursor.execute(ret_sql, tuple(ret_params))
            returns_amt = float(cursor.fetchone()[0] or 0.0)

        total_sales = max(0.0, gross_sales - returns_amt)

        # Sales this month
        month_params = [cur_month_start, cur_month_end]
        if product_id:
            cursor.execute("""
                SELECT COALESCE(SUM(si.total_item_amount), 0)
                FROM sales_items si
                JOIN sales_invoices inv ON si.invoice_id = inv.invoice_id
                WHERE inv.status = 'COMPLETED'
                  AND inv.invoice_date >= ? AND inv.invoice_date <= ?
                  AND si.product_id = ?
            """, (cur_month_start, cur_month_end, product_id))
            m_gross = float(cursor.fetchone()[0] or 0.0)

            cursor.execute("""
                SELECT COALESCE(SUM(refund_amount), 0)
                FROM sales_returns
                WHERE return_date >= ? AND return_date <= ? AND product_id = ?
            """, (cur_month_start, cur_month_end, product_id))
            m_ret = float(cursor.fetchone()[0] or 0.0)
        elif category_id:
            cursor.execute("""
                SELECT COALESCE(SUM(si.total_item_amount), 0)
                FROM sales_items si
                JOIN sales_invoices inv ON si.invoice_id = inv.invoice_id
                JOIN products p ON si.product_id = p.product_id
                WHERE inv.status = 'COMPLETED'
                  AND inv.invoice_date >= ? AND inv.invoice_date <= ?
                  AND p.category_id = ?
            """, (cur_month_start, cur_month_end, category_id))
            m_gross = float(cursor.fetchone()[0] or 0.0)

            cursor.execute("""
                SELECT COALESCE(SUM(r.refund_amount), 0)
                FROM sales_returns r
                JOIN products p ON r.product_id = p.product_id
                WHERE r.return_date >= ? AND r.return_date <= ? AND p.category_id = ?
            """, (cur_month_start, cur_month_end, category_id))
            m_ret = float(cursor.fetchone()[0] or 0.0)
        else:
            cursor.execute("""
                SELECT COALESCE(SUM(net_total_amount), 0)
                FROM sales_invoices
                WHERE status = 'COMPLETED'
                  AND invoice_date >= ? AND invoice_date <= ?
            """, (cur_month_start, cur_month_end))
            m_gross = float(cursor.fetchone()[0] or 0.0)

            cursor.execute("""
                SELECT COALESCE(SUM(refund_amount), 0)
                FROM sales_returns
                WHERE return_date >= ? AND return_date <= ?
            """, (cur_month_start, cur_month_end))
            m_ret = float(cursor.fetchone()[0] or 0.0)

        sales_this_month = max(0.0, m_gross - m_ret)

        # -------------------------------------------------------------
        # 2. GROSS PROFIT WHERE COST DATA IS AVAILABLE
        # -------------------------------------------------------------
        # Only includes items where unit_cost_price IS NOT NULL AND unit_cost_price > 0
        profit_conditions = ["inv.status = 'COMPLETED'", "si.unit_cost_price IS NOT NULL", "si.unit_cost_price > 0"]
        profit_params: List[Any] = []
        if s_date:
            profit_conditions.append("inv.invoice_date >= ?")
            profit_params.append(s_date)
        if e_date:
            profit_conditions.append("inv.invoice_date <= ?")
            profit_params.append(e_date)
        if product_id:
            profit_conditions.append("si.product_id = ?")
            profit_params.append(product_id)
        elif category_id:
            profit_conditions.append("p.category_id = ?")
            profit_params.append(category_id)

        join_cat = "JOIN products p ON si.product_id = p.product_id" if category_id else ""
        profit_sql = f"""
            SELECT 
                COALESCE(SUM(si.gross_profit), 0) AS gross_profit,
                COALESCE(SUM(si.unit_cost_price * si.quantity), 0) AS cogs,
                COALESCE(SUM(si.taxable_value), 0) AS taxable_revenue,
                COUNT(si.item_id) AS items_with_cost
            FROM sales_items si
            JOIN sales_invoices inv ON si.invoice_id = inv.invoice_id
            {join_cat}
            WHERE {' AND '.join(profit_conditions)}
        """
        cursor.execute(profit_sql, tuple(profit_params))
        prof_res = cursor.fetchone()
        gross_profit = float(prof_res["gross_profit"])
        cogs = float(prof_res["cogs"])
        items_with_cost = int(prof_res["items_with_cost"])

        # Count total items sold to compute coverage percentage
        all_items_cond = ["inv.status = 'COMPLETED'"]
        all_items_params: List[Any] = []
        if s_date:
            all_items_cond.append("inv.invoice_date >= ?")
            all_items_params.append(s_date)
        if e_date:
            all_items_cond.append("inv.invoice_date <= ?")
            all_items_params.append(e_date)
        if product_id:
            all_items_cond.append("si.product_id = ?")
            all_items_params.append(product_id)
        elif category_id:
            all_items_cond.append("p.category_id = ?")
            all_items_params.append(category_id)

        cursor.execute(f"""
            SELECT COUNT(si.item_id) AS total_items
            FROM sales_items si
            JOIN sales_invoices inv ON si.invoice_id = inv.invoice_id
            {join_cat}
            WHERE {' AND '.join(all_items_cond)}
        """, tuple(all_items_params))
        total_items_sold = int(cursor.fetchone()["total_items"] or 0)
        cost_coverage_pct = (items_with_cost / total_items_sold * 100.0) if total_items_sold > 0 else 100.0

        # Adjust for returns where cost is known
        ret_cogs_cond = ["1=1"]
        ret_cogs_params = []
        if s_date:
            ret_cogs_cond.append("r.return_date >= ?")
            ret_cogs_params.append(s_date)
        if e_date:
            ret_cogs_cond.append("r.return_date <= ?")
            ret_cogs_params.append(e_date)
        if product_id:
            ret_cogs_cond.append("r.product_id = ?")
            ret_cogs_params.append(product_id)
        elif category_id:
            ret_cogs_cond.append("p.category_id = ?")
            ret_cogs_params.append(category_id)

        cursor.execute(f"""
            SELECT 
                COALESCE(SUM((r.refund_amount - COALESCE(r.tax_refund_amount, 0)) - (COALESCE(b.unit_cost, p.cost_price, 0) * r.quantity)), 0) AS returned_profit
            FROM sales_returns r
            LEFT JOIN inventory_batches b ON r.batch_id = b.batch_id
            JOIN products p ON r.product_id = p.product_id
            WHERE {' AND '.join(ret_cogs_cond)}
        """, tuple(ret_cogs_params))
        returned_profit = float(cursor.fetchone()[0] or 0.0)
        net_gross_profit = max(0.0, gross_profit - returned_profit)

        # -------------------------------------------------------------
        # 3. CURRENT INVENTORY VALUE
        # -------------------------------------------------------------
        # Valuation based on active stock in inventory batches (or product cost_price)
        inv_val_cond = ["b.quantity_available > 0"]
        inv_val_params: List[Any] = []
        if product_id:
            inv_val_cond.append("b.product_id = ?")
            inv_val_params.append(product_id)
        elif category_id:
            inv_val_cond.append("p.category_id = ?")
            inv_val_params.append(category_id)

        inv_val_sql = f"""
            SELECT COALESCE(SUM(b.quantity_available * b.unit_cost), 0) AS total_val
            FROM inventory_batches b
            JOIN products p ON b.product_id = p.product_id
            WHERE p.is_active = 1 AND {' AND '.join(inv_val_cond)}
        """
        cursor.execute(inv_val_sql, tuple(inv_val_params))
        current_inventory_value = float(cursor.fetchone()["total_val"] or 0.0)

        # If batches have 0 value, fallback to product level cost_price * current_stock
        if current_inventory_value == 0:
            prod_val_cond = ["p.is_active = 1"]
            prod_val_params: List[Any] = []
            if product_id:
                prod_val_cond.append("p.product_id = ?")
                prod_val_params.append(product_id)
            elif category_id:
                prod_val_cond.append("p.category_id = ?")
                prod_val_params.append(category_id)
            cursor.execute(f"""
                SELECT COALESCE(SUM(p.cost_price * COALESCE(b_sub.qty, 0)), 0)
                FROM products p
                LEFT JOIN (
                    SELECT product_id, SUM(quantity_available) AS qty
                    FROM inventory_batches
                    GROUP BY product_id
                ) b_sub ON p.product_id = b_sub.product_id
                WHERE {' AND '.join(prod_val_cond)}
            """, tuple(prod_val_params))
            current_inventory_value = float(cursor.fetchone()[0] or 0.0)

        # -------------------------------------------------------------
        # 4. LOW-STOCK PRODUCT COUNT
        # -------------------------------------------------------------
        # Number of active products where total available stock <= min_safety_stock
        ls_cond = ["p.is_active = 1"]
        ls_params: List[Any] = []
        if product_id:
            ls_cond.append("p.product_id = ?")
            ls_params.append(product_id)
        elif category_id:
            ls_cond.append("p.category_id = ?")
            ls_params.append(category_id)

        cursor.execute(f"""
            SELECT COUNT(*) AS low_stock_count
            FROM (
                SELECT p.product_id, p.min_safety_stock, COALESCE(SUM(b.quantity_available), 0) AS stock
                FROM products p
                LEFT JOIN inventory_batches b ON p.product_id = b.product_id
                WHERE {' AND '.join(ls_cond)}
                GROUP BY p.product_id
                HAVING stock <= p.min_safety_stock
            )
        """, tuple(ls_params))
        low_stock_count = int(cursor.fetchone()["low_stock_count"] or 0)

        # Total active products in current filter
        cursor.execute(f"SELECT COUNT(*) FROM products p WHERE {' AND '.join(ls_cond)}", tuple(ls_params))
        total_products = int(cursor.fetchone()[0] or 0)

        # -------------------------------------------------------------
        # 5. UPCOMING CONFIGURED FESTIVALS
        # -------------------------------------------------------------
        cursor.execute("""
            SELECT calendar_id, festival_name, region, start_date, end_date,
                   category, planning_window_days, planning_start_date, is_sample_date, is_verified
            FROM festival_calendar
            WHERE end_date >= ?
            ORDER BY start_date ASC
            LIMIT 5
        """, (ref_d.strftime("%Y-%m-%d"),))
        upcoming_rows = [dict(r) for r in cursor.fetchall()]

        for u in upcoming_rows:
            u_start = datetime.strptime(u["start_date"], "%Y-%m-%d").date()
            u["days_until"] = (u_start - ref_d).days

        return {
            "total_sales": total_sales,
            "sales_this_month": sales_this_month,
            "gross_profit": net_gross_profit,
            "cost_coverage_pct": round(cost_coverage_pct, 1),
            "items_with_cost": items_with_cost,
            "total_items_sold": total_items_sold,
            "current_inventory_value": current_inventory_value,
            "low_stock_product_count": low_stock_count,
            "total_products": total_products,
            "invoice_count": inv_count,
            "upcoming_festivals": upcoming_rows,
            "current_month_name": ref_d.strftime("%B %Y")
        }
    finally:
        conn.close()


def get_revenue_over_time(
    start_date: Optional[Any] = None,
    end_date: Optional[Any] = None,
    category_id: Optional[int] = None,
    product_id: Optional[int] = None
) -> pd.DataFrame:
    """
    Returns time-series revenue and invoice counts reflecting the selected filters.
    """
    s_date = parse_filter_date(start_date)
    e_date = parse_filter_date(end_date)

    conditions = ["inv.status = 'COMPLETED'"]
    params: List[Any] = []

    if s_date:
        conditions.append("inv.invoice_date >= ?")
        params.append(s_date)
    if e_date:
        conditions.append("inv.invoice_date <= ?")
        params.append(e_date)

    if product_id:
        conditions.append("si.product_id = ?")
        params.append(product_id)
        sql = f"""
            SELECT inv.invoice_date,
                   COUNT(DISTINCT inv.invoice_id) AS invoice_count,
                   SUM(si.total_item_amount) AS revenue,
                   SUM(si.gross_profit) AS gross_profit
            FROM sales_items si
            JOIN sales_invoices inv ON si.invoice_id = inv.invoice_id
            WHERE {' AND '.join(conditions)}
            GROUP BY inv.invoice_date
            ORDER BY inv.invoice_date ASC
        """
    elif category_id:
        conditions.append("p.category_id = ?")
        params.append(category_id)
        sql = f"""
            SELECT inv.invoice_date,
                   COUNT(DISTINCT inv.invoice_id) AS invoice_count,
                   SUM(si.total_item_amount) AS revenue,
                   SUM(si.gross_profit) AS gross_profit
            FROM sales_items si
            JOIN sales_invoices inv ON si.invoice_id = inv.invoice_id
            JOIN products p ON si.product_id = p.product_id
            WHERE {' AND '.join(conditions)}
            GROUP BY inv.invoice_date
            ORDER BY inv.invoice_date ASC
        """
    else:
        sql = f"""
            SELECT invoice_date,
                   COUNT(invoice_id) AS invoice_count,
                   SUM(net_total_amount) AS revenue,
                   SUM(total_taxable_amount) AS taxable_revenue
            FROM sales_invoices inv
            WHERE {' AND '.join(conditions)}
            GROUP BY invoice_date
            ORDER BY invoice_date ASC
        """

    return query_df(sql, tuple(params))


def get_top_selling_products(
    limit: int = 10,
    start_date: Optional[Any] = None,
    end_date: Optional[Any] = None,
    category_id: Optional[int] = None
) -> pd.DataFrame:
    """
    Returns top-selling products by revenue and quantity sold within the filtered scope.
    """
    s_date = parse_filter_date(start_date)
    e_date = parse_filter_date(end_date)

    conditions = ["inv.status = 'COMPLETED'"]
    params: List[Any] = []

    if s_date:
        conditions.append("inv.invoice_date >= ?")
        params.append(s_date)
    if e_date:
        conditions.append("inv.invoice_date <= ?")
        params.append(e_date)
    if category_id:
        conditions.append("p.category_id = ?")
        params.append(category_id)

    sql = f"""
        SELECT p.product_name,
               c.category_name,
               SUM(si.quantity) AS total_units_sold,
               SUM(si.total_item_amount) AS total_revenue,
               SUM(si.gross_profit) AS total_profit
        FROM sales_items si
        JOIN products p ON si.product_id = p.product_id
        JOIN product_categories c ON p.category_id = c.category_id
        JOIN sales_invoices inv ON si.invoice_id = inv.invoice_id
        WHERE {' AND '.join(conditions)}
        GROUP BY p.product_id
        ORDER BY total_revenue DESC
        LIMIT ?
    """
    params.append(limit)
    return query_df(sql, tuple(params))


def get_stock_status_breakdown(category_id: Optional[int] = None) -> pd.DataFrame:
    """
    Computes stock health distribution (Adequate, Low Stock, Out of Stock)
    across actual inventory stock records.
    """
    conditions = ["p.is_active = 1"]
    params: List[Any] = []
    if category_id:
        conditions.append("p.category_id = ?")
        params.append(category_id)

    sql = f"""
        SELECT 
            p.product_id,
            p.product_name,
            c.category_name,
            p.min_safety_stock,
            COALESCE(SUM(b.quantity_available), 0) AS current_stock,
            COALESCE(SUM(b.quantity_available * b.unit_cost), 0) AS stock_value,
            CASE 
                WHEN COALESCE(SUM(b.quantity_available), 0) = 0 THEN 'Out of Stock'
                WHEN COALESCE(SUM(b.quantity_available), 0) <= p.min_safety_stock THEN 'Low Stock'
                ELSE 'In Stock'
            END AS stock_status
        FROM products p
        JOIN product_categories c ON p.category_id = c.category_id
        LEFT JOIN inventory_batches b ON p.product_id = b.product_id
        WHERE {' AND '.join(conditions)}
        GROUP BY p.product_id
    """
    return query_df(sql, tuple(params))


def get_festival_period_comparisons() -> pd.DataFrame:
    """
    Aggregates actual revenue and sales volume across completed festival campaign periods.
    Returns comparison records when enough data exists.
    """
    sql = """
        SELECT 
            f.festival_name,
            o.year,
            o.occurrence_id,
            o.festival_date,
            o.campaign_start_date,
            o.campaign_end_date,
            COUNT(DISTINCT inv.invoice_id) AS total_invoices,
            COALESCE(SUM(inv.net_total_amount), 0) AS campaign_revenue,
            COALESCE(SUM(si.quantity), 0) AS units_sold,
            COALESCE(SUM(si.gross_profit), 0) AS campaign_profit
        FROM festival_occurrences o
        JOIN festivals f ON o.festival_id = f.festival_id
        LEFT JOIN sales_invoices inv ON inv.occurrence_id = o.occurrence_id AND inv.status = 'COMPLETED'
        LEFT JOIN sales_items si ON inv.invoice_id = si.invoice_id
        GROUP BY o.occurrence_id
        HAVING campaign_revenue > 0
        ORDER BY o.year ASC, o.festival_date ASC
    """
    return query_df(sql)
