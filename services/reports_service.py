"""
FestivePulse — Comprehensive Analytics & Audit Reporting Engine
Generates official CSV and PDF reports for:
1. Sales Summary & Tax Ledger
2. Inventory Valuation & Stock Health
3. Auditable Stock Movement Ledger
4. Multi-Year Festival Performance Comparisons
5. Operating Expenses & Overheads
6. Deterministic Forecast-Based Stock Procurement Plans

INVARIANTS:
- 100% Non-AI, deterministic calculations grounded in SQLite database records.
- Explicit Report Generation Date, Currency INR, and Calculation Definitions.
- Clear, unambiguous distinction between ACTUAL RESULTS and ESTIMATE/FORECAST PROJECTIONS.
- Repeated table headers across pages (repeatRows=1) and NumberedCanvas page numbering (Page X of Y).
- Safe Unicode handling with elegant layout formatting for portrait and landscape views.
- Graceful empty-state reporting without crashes or corrupted output files.
"""

import io
from datetime import datetime, date
from typing import Dict, Any, List, Optional, Tuple, Union
import pandas as pd

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether, HRFlowable
)
from reportlab.pdfgen import canvas

from database.connection import query_df, get_db_connection
from database.queries import get_business_settings
from services.currency_utils import format_inr
from services.expense_service import normalize_category, get_financial_pnl_statement
from services.stock_planning_service import generate_festival_stock_plan_table, analyze_budget_excess
from services.security_service import sanitize_df_for_csv
from config import EXPENSE_CATEGORIES


# ==============================================================================
# 1. REPORTLAB NUMBERED CANVAS (PAGE X OF Y & AUDIT FOOTER)
# ==============================================================================

class NumberedCanvas(canvas.Canvas):
    """
    Two-pass canvas that accumulates all drawn pages, calculates total page count,
    and paints a consistent running header/footer with page numbers, generation timestamp,
    and system identification.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states: List[Dict[str, Any]] = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_running_footer(num_pages)
            super().showPage()
        super().save()

    def draw_running_footer(self, page_count: int):
        self.saveState()
        self.setFont("Helvetica", 7.5)
        self.setFillColor(colors.HexColor("#64748B"))
        page_w, page_h = self._pagesize

        # Running rule above footer
        self.setStrokeColor(colors.HexColor("#CBD5E1"))
        self.setLineWidth(0.5)
        self.line(10 * mm, 11 * mm, page_w - 10 * mm, 11 * mm)

        # Footer Left: Brand & Currency Standard
        self.drawString(10 * mm, 7 * mm, "FestivePulse AI — Local SQLite Database System Record | Currency: INR (Indian Rupee)")

        # Footer Right: Page X of Y
        page_str = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(page_w - 10 * mm, 7 * mm, page_str)
        self.restoreState()


# ==============================================================================
# 2. FORMATTING HELPERS
# ==============================================================================

def clean_xml(text: Any) -> str:
    """Escapes XML entities for ReportLab Paragraphs."""
    if text is None:
        return ""
    s = str(text)
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return s


def format_inr_clean(val: Any) -> str:
    """Formats numeric amounts as clean INR currency string for PDF & CSV."""
    if val is None or pd.isna(val):
        return "INR 0.00"
    try:
        f_val = float(val)
        return f"INR {f_val:,.2f}"
    except (ValueError, TypeError):
        return str(val)


def get_current_timestamp_str() -> str:
    """Returns official formatted audit generation timestamp."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")


# ==============================================================================
# 3. REPORT DATA EXTRACTORS
# ==============================================================================

def get_sales_summary_data(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    occurrence_id: Optional[int] = None,
    region: Optional[str] = None,
    product_id: Optional[int] = None,
    category_id: Optional[int] = None
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Extracts actual recorded sales transactions, taxes, and profitability."""
    sql = """
        SELECT 
            inv.invoice_number,
            inv.invoice_date,
            inv.status,
            inv.payment_mode,
            COALESCE(c.customer_name, 'Direct Retail Counter') AS customer_name,
            COALESCE(c.city, 'Local') AS customer_city,
            COALESCE(f.festival_name, 'Non-Festival / Regular') AS festival_name,
            fo.year AS festival_year,
            p.product_id,
            p.sku,
            p.product_name,
            pc.category_name,
            si.quantity,
            si.unit_selling_price,
            si.unit_cost_price,
            si.discount_percent,
            si.taxable_value,
            si.gst_rate,
            si.cgst_amount,
            si.sgst_amount,
            si.igst_amount,
            si.total_item_amount,
            si.gross_profit
        FROM sales_items si
        JOIN sales_invoices inv ON si.invoice_id = inv.invoice_id
        JOIN products p ON si.product_id = p.product_id
        LEFT JOIN product_categories pc ON p.category_id = pc.category_id
        LEFT JOIN customers c ON inv.customer_id = c.customer_id
        LEFT JOIN festival_occurrences fo ON inv.occurrence_id = fo.occurrence_id
        LEFT JOIN festivals f ON fo.festival_id = f.festival_id
        WHERE 1=1
    """
    params: List[Any] = []
    filters_desc: Dict[str, str] = {}

    if start_date:
        sql += " AND inv.invoice_date >= ?"
        params.append(start_date)
        filters_desc["From Date"] = start_date
    if end_date:
        sql += " AND inv.invoice_date <= ?"
        params.append(end_date)
        filters_desc["To Date"] = end_date
    if occurrence_id:
        sql += " AND inv.occurrence_id = ?"
        params.append(occurrence_id)
        filters_desc["Festival Occurrence ID"] = str(occurrence_id)
    if product_id:
        sql += " AND si.product_id = ?"
        params.append(product_id)
        filters_desc["Product ID"] = str(product_id)
    if category_id:
        sql += " AND p.category_id = ?"
        params.append(category_id)
        filters_desc["Category ID"] = str(category_id)
    if region and region != "ALL" and region != "Pan-India":
        sql += " AND (f.primary_regions LIKE ? OR c.state LIKE ?)"
        r_pat = f"%{region}%"
        params.extend([r_pat, r_pat])
        filters_desc["Region"] = region

    sql += " ORDER BY inv.invoice_date DESC, inv.invoice_id DESC"
    df = query_df(sql, tuple(params))

    # Calculate summary KPIs
    tot_billed = float(df["total_item_amount"].sum()) if not df.empty else 0.0
    tot_taxable = float(df["taxable_value"].sum()) if not df.empty else 0.0
    tot_cgst = float(df["cgst_amount"].sum()) if not df.empty else 0.0
    tot_sgst = float(df["sgst_amount"].sum()) if not df.empty else 0.0
    tot_igst = float(df["igst_amount"].sum()) if not df.empty else 0.0
    tot_tax = tot_cgst + tot_sgst + tot_igst
    tot_units = int(df["quantity"].sum()) if not df.empty else 0
    tot_gp = float(df["gross_profit"].sum()) if not df.empty else 0.0
    gp_margin = round((tot_gp / tot_taxable * 100.0), 2) if tot_taxable > 0 else 0.0

    meta = {
        "title": "Sales Summary & Tax Invoicing Ledger",
        "classification": "ACTUAL (Recorded Database Ledger Records)",
        "generated_at": get_current_timestamp_str(),
        "currency": "INR",
        "filters_applied": filters_desc or {"Filters": "All Records (Unfiltered)"},
        "calculation_definitions": {
            "Gross Line Total": "quantity * unit_selling_price - line_discount + GST taxes",
            "Taxable Value": "Taxable counter revenue after deducting item and trade discounts",
            "CGST & SGST": "50% each of applicable GST slab rate for intra-state supply",
            "IGST": "100% of GST slab rate for inter-state supply",
            "Cost of Goods Sold (COGS)": "quantity * immutable unit_cost_price snapshot recorded at transaction time",
            "Gross Profit": "Taxable Value - COGS"
        },
        "summary_kpis": [
            {"label": "Total Gross Sales", "value": format_inr_clean(tot_billed)},
            {"label": "Taxable Turnover", "value": format_inr_clean(tot_taxable)},
            {"label": "Total GST Collected", "value": format_inr_clean(tot_tax)},
            {"label": "Total Units Sold", "value": f"{tot_units:,} units"},
            {"label": "Gross Profit", "value": format_inr_clean(tot_gp)},
            {"label": "Gross Margin %", "value": f"{gp_margin:.1f}%"}
        ]
    }
    return df, meta


def get_inventory_report_data(
    category_id: Optional[int] = None,
    low_stock_only: bool = False,
    is_perishable: Optional[int] = None,
    region: Optional[str] = None
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Extracts on-hand physical stock, batch valuation, and safety status."""
    sql = """
        SELECT 
            p.product_id,
            p.sku,
            p.product_name,
            pc.category_name AS category,
            p.unit_of_measure,
            p.cost_price,
            p.selling_price,
            p.mrp,
            p.min_safety_stock,
            p.reorder_quantity,
            p.is_perishable,
            p.shelf_life_days,
            p.region_tags,
            COALESCE(SUM(b.quantity_available), 0) AS total_available_stock,
            COALESCE(SUM(b.quantity_available * b.unit_cost), 0) AS total_cost_valuation,
            COALESCE(SUM(b.quantity_available * p.selling_price), 0) AS total_retail_valuation,
            COUNT(b.batch_id) AS active_batches_count
        FROM products p
        LEFT JOIN product_categories pc ON p.category_id = pc.category_id
        LEFT JOIN inventory_batches b ON p.product_id = b.product_id AND b.quantity_available > 0
        WHERE p.is_active = 1
    """
    params: List[Any] = []
    filters_desc: Dict[str, str] = {}

    if category_id:
        sql += " AND p.category_id = ?"
        params.append(category_id)
        filters_desc["Category ID"] = str(category_id)
    if is_perishable is not None:
        sql += " AND p.is_perishable = ?"
        params.append(is_perishable)
        filters_desc["Perishability"] = "Perishable Items Only" if is_perishable else "Non-Perishable Only"
    if region and region != "ALL" and region != "Pan-India":
        sql += " AND (p.region_tags LIKE ? OR p.region_tags LIKE '%Pan-India%')"
        params.append(f"%{region}%")
        filters_desc["Region"] = region

    sql += " GROUP BY p.product_id"

    if low_stock_only:
        sql += " HAVING total_available_stock <= p.min_safety_stock"
        filters_desc["Stock Status"] = "Low Stock Alerts Only"

    sql += " ORDER BY p.product_name ASC"
    df = query_df(sql, tuple(params))

    # Add derived status column
    if not df.empty:
        df["status"] = df.apply(
            lambda r: "CRITICAL LOW" if r["total_available_stock"] <= 0
            else ("LOW STOCK" if r["total_available_stock"] <= r["min_safety_stock"] else "HEALTHY"),
            axis=1
        )
    else:
        df["status"] = []

    tot_units = int(df["total_available_stock"].sum()) if not df.empty else 0
    tot_cost_val = float(df["total_cost_valuation"].sum()) if not df.empty else 0.0
    tot_retail_val = float(df["total_retail_valuation"].sum()) if not df.empty else 0.0
    low_stock_count = int((df["status"] != "HEALTHY").sum()) if not df.empty else 0
    potential_gp = tot_retail_val - tot_cost_val

    meta = {
        "title": "Inventory Valuation & Stock Status Report",
        "classification": "ACTUAL (Physical On-Hand Inventory Records)",
        "generated_at": get_current_timestamp_str(),
        "currency": "INR",
        "filters_applied": filters_desc or {"Filters": "All Active Products"},
        "calculation_definitions": {
            "Total Available Stock": "SUM(batch.quantity_available) across all unexpired batches in warehouse",
            "Cost Valuation (Asset)": "SUM(batch.quantity_available * batch.unit_cost) - True local inventory cost value",
            "Retail Valuation": "SUM(batch.quantity_available * product.selling_price) - Anticipated counter turnover",
            "Potential Gross Profit": "Retail Valuation - Cost Valuation",
            "Low Stock Status": "Flagged as LOW STOCK if Available Stock <= Min Safety Stock; CRITICAL if zero"
        },
        "summary_kpis": [
            {"label": "Total Units On-Hand", "value": f"{tot_units:,} units"},
            {"label": "Total Cost Valuation", "value": format_inr_clean(tot_cost_val)},
            {"label": "Total Retail Value", "value": format_inr_clean(tot_retail_val)},
            {"label": "Potential Gross Profit", "value": format_inr_clean(potential_gp)},
            {"label": "Low Stock Alerts", "value": f"{low_stock_count} SKUs"}
        ]
    }
    return df, meta


def get_stock_movements_data(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    product_id: Optional[int] = None,
    category_id: Optional[int] = None,
    movement_type: Optional[str] = None
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Extracts immutable stock movement audit ledger."""
    sql = """
        SELECT 
            sm.movement_id,
            sm.created_at,
            sm.movement_type,
            sm.quantity,
            sm.unit_cost,
            sm.total_cost_impact,
            sm.reference_type,
            COALESCE(sm.reference_id, '-') AS reference_id,
            sm.reason,
            p.sku,
            p.product_name,
            pc.category_name,
            COALESCE(ib.batch_number, '-') AS batch_number
        FROM stock_movements sm
        JOIN products p ON sm.product_id = p.product_id
        LEFT JOIN product_categories pc ON p.category_id = pc.category_id
        LEFT JOIN inventory_batches ib ON sm.batch_id = ib.batch_id
        WHERE 1=1
    """
    params: List[Any] = []
    filters_desc: Dict[str, str] = {}

    if start_date:
        sql += " AND DATE(sm.created_at) >= ?"
        params.append(start_date)
        filters_desc["From Date"] = start_date
    if end_date:
        sql += " AND DATE(sm.created_at) <= ?"
        params.append(end_date)
        filters_desc["To Date"] = end_date
    if product_id:
        sql += " AND sm.product_id = ?"
        params.append(product_id)
        filters_desc["Product ID"] = str(product_id)
    if category_id:
        sql += " AND p.category_id = ?"
        params.append(category_id)
        filters_desc["Category ID"] = str(category_id)
    if movement_type and movement_type != "ALL":
        sql += " AND sm.movement_type = ?"
        params.append(movement_type)
        filters_desc["Movement Type"] = movement_type

    sql += " ORDER BY sm.movement_id DESC"
    df = query_df(sql, tuple(params))

    # Aggregates
    tot_inward = int(df[df["quantity"] > 0]["quantity"].sum()) if not df.empty else 0
    tot_outward = int(abs(df[df["quantity"] < 0]["quantity"].sum())) if not df.empty else 0
    tot_cost_impact = float(df["total_cost_impact"].sum()) if not df.empty else 0.0

    meta = {
        "title": "Stock Movement Audit Ledger Report",
        "classification": "ACTUAL (Auditable Stock Movement Ledger)",
        "generated_at": get_current_timestamp_str(),
        "currency": "INR",
        "filters_applied": filters_desc or {"Filters": "All Recorded Movements"},
        "calculation_definitions": {
            "Quantity Change": "+ positive for inbound receipts/returns; - negative for sales, damage, shrinkage",
            "Unit Cost": "Recorded batch purchase cost at the exact time of stock movement",
            "Total Cost Impact": "|Quantity| * Unit Cost - Absolute ledger financial valuation impact",
            "Inward Movement": "Units received into warehouse via supplier purchase or sales return restock",
            "Outward Movement": "Units depleted via sales billing, customer returns, or damage write-offs"
        },
        "summary_kpis": [
            {"label": "Total Ledger Movements", "value": f"{len(df):,} events"},
            {"label": "Total Inward Receipts", "value": f"+{tot_inward:,} units"},
            {"label": "Total Outward Depletion", "value": f"-{tot_outward:,} units"},
            {"label": "Gross Ledger Impact", "value": format_inr_clean(tot_cost_impact)}
        ]
    }
    return df, meta


def get_festival_comparisons_data(
    festival_id: Optional[int] = None,
    year_start: Optional[int] = None,
    year_end: Optional[int] = None,
    region: Optional[str] = None
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Compares actual historical campaign results across festivals and years."""
    sql = """
        SELECT 
            fo.occurrence_id,
            f.festival_id,
            f.festival_name,
            f.festival_code,
            fo.year,
            fo.campaign_start_date,
            fo.campaign_end_date,
            fo.festival_date,
            f.primary_regions
        FROM festival_occurrences fo
        JOIN festivals f ON fo.festival_id = f.festival_id
        WHERE 1=1
    """
    params: List[Any] = []
    filters_desc: Dict[str, str] = {}

    if festival_id:
        sql += " AND f.festival_id = ?"
        params.append(festival_id)
        filters_desc["Festival ID"] = str(festival_id)
    if year_start:
        sql += " AND fo.year >= ?"
        params.append(year_start)
        filters_desc["From Year"] = str(year_start)
    if year_end:
        sql += " AND fo.year <= ?"
        params.append(year_end)
        filters_desc["To Year"] = str(year_end)
    if region and region != "ALL" and region != "Pan-India":
        sql += " AND (f.primary_regions LIKE ? OR f.primary_regions LIKE '%Pan-India%')"
        params.append(f"%{region}%")
        filters_desc["Region"] = region

    sql += " ORDER BY fo.year DESC, f.festival_name ASC"
    occ_df = query_df(sql, tuple(params))

    # Evaluate P&L for each occurrence using deterministic expense service
    records = []
    for _, r in occ_df.iterrows():
        occ_id = int(r["occurrence_id"])
        pnl = get_financial_pnl_statement(occurrence_id=occ_id, include_general_overheads=False)
        records.append({
            "occurrence_id": occ_id,
            "festival_name": r["festival_name"],
            "year": r["year"],
            "campaign_window": f"{r['campaign_start_date']} to {r['campaign_end_date']}",
            "invoices_count": pnl["invoice_count"],
            "units_sold": pnl["total_units_sold"],
            "gross_billed": pnl["gross_billed"],
            "discounts": pnl["total_discounts"],
            "net_revenue": pnl["net_sales_revenue"],
            "net_cogs": pnl["net_cogs"],
            "gross_profit": pnl["gross_profit"],
            "gross_margin_pct": pnl["gross_margin_pct"],
            "operating_expenses": pnl["total_included_expenses"],
            "net_operating_profit": pnl["net_operating_profit"],
            "roi_pct": pnl["festival_roi_pct"]
        })

    df = pd.DataFrame(records)

    tot_net_rev = float(df["net_revenue"].sum()) if not df.empty else 0.0
    tot_cogs = float(df["net_cogs"].sum()) if not df.empty else 0.0
    tot_exp = float(df["operating_expenses"].sum()) if not df.empty else 0.0
    tot_net_prof = float(df["net_operating_profit"].sum()) if not df.empty else 0.0
    avg_roi = round((tot_net_prof / (tot_cogs + tot_exp) * 100.0), 2) if (tot_cogs + tot_exp) > 0 else 0.0

    meta = {
        "title": "Festival Campaign Comparative Performance Report",
        "classification": "ACTUAL (Comparative Historic Campaign Performance)",
        "generated_at": get_current_timestamp_str(),
        "currency": "INR",
        "filters_applied": filters_desc or {"Filters": "All Configured Festival Occurrences"},
        "calculation_definitions": {
            "Net Sales Revenue": "Gross Billed Sales - Discounts - Customer Sales Returns",
            "Net COGS": "SUM(snapshot unit_cost * units_sold) - Returned COGS",
            "Gross Profit": "Net Sales Revenue - Net COGS",
            "Operating Expenses": "SUM(Auditable expenses tagged to campaign: Rent, Transport, Packaging, Wages, Marketing, Other)",
            "Net Operating Profit": "Gross Profit - Operating Expenses",
            "Festival ROI %": "(Net Operating Profit / (Net COGS + Operating Expenses)) * 100"
        },
        "summary_kpis": [
            {"label": "Festivals Analyzed", "value": f"{len(df)} campaigns"},
            {"label": "Cumulative Net Revenue", "value": format_inr_clean(tot_net_rev)},
            {"label": "Total Campaign Expenses", "value": format_inr_clean(tot_exp)},
            {"label": "Net Operating Profit", "value": format_inr_clean(tot_net_prof)},
            {"label": "Cumulative Campaign ROI", "value": f"{avg_roi:.1f}%"}
        ]
    }
    return df, meta


def get_expense_summary_data(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    category: Optional[str] = None,
    occurrence_id: Optional[int] = None,
    status: Optional[str] = None
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Extracts operational expense vouchers, categories, and audit status."""
    sql = """
        SELECT 
            e.expense_id,
            e.expense_date,
            e.expense_category AS category,
            e.amount,
            COALESCE(e.description, e.notes, '-') AS description,
            e.status,
            e.payment_mode,
            COALESCE(e.vendor_name, '-') AS vendor_name,
            COALESCE(e.invoice_receipt_no, '-') AS invoice_receipt_no,
            COALESCE(f.festival_name, 'General Store Overhead') AS festival_name,
            fo.year AS festival_year
        FROM expenses e
        LEFT JOIN festival_occurrences fo ON e.occurrence_id = fo.occurrence_id
        LEFT JOIN festivals f ON fo.festival_id = f.festival_id
        WHERE 1=1
    """
    params: List[Any] = []
    filters_desc: Dict[str, str] = {}

    if start_date:
        sql += " AND e.expense_date >= ?"
        params.append(start_date)
        filters_desc["From Date"] = start_date
    if end_date:
        sql += " AND e.expense_date <= ?"
        params.append(end_date)
        filters_desc["To Date"] = end_date
    if category and category != "ALL":
        sql += " AND e.expense_category = ?"
        params.append(normalize_category(category))
        filters_desc["Category"] = category
    if occurrence_id:
        sql += " AND e.occurrence_id = ?"
        params.append(occurrence_id)
        filters_desc["Festival Occurrence ID"] = str(occurrence_id)
    if status and status != "ALL":
        sql += " AND e.status = ?"
        params.append(status)
        filters_desc["Audit Status"] = status

    sql += " ORDER BY e.expense_date DESC, e.expense_id DESC"
    df = query_df(sql, tuple(params))

    # Aggregates
    active_df = df[df["status"].isin(["ACTIVE", "CORRECTED"])] if not df.empty else pd.DataFrame()
    tot_active_amt = float(active_df["amount"].sum()) if not active_df.empty else 0.0
    cancelled_amt = float(df[df["status"] == "CANCELLED"]["amount"].sum()) if not df.empty else 0.0

    meta = {
        "title": "Operating Expenses & Overheads Audit Report",
        "classification": "ACTUAL (Auditable Expense Vouchers & Overheads)",
        "generated_at": get_current_timestamp_str(),
        "currency": "INR",
        "filters_applied": filters_desc or {"Filters": "All Recorded Expenses"},
        "calculation_definitions": {
            "Active Operating Expenses": "SUM(amount) for all vouchers in ACTIVE or CORRECTED state",
            "Cancelled Vouchers": "Recorded with audit reason and permanently excluded from P&L",
            "Operational Classifications": "Rent (Stall/Store), Transport (Freight), Packaging, Wages, Marketing, Other"
        },
        "summary_kpis": [
            {"label": "Total Active Vouchers", "value": f"{len(active_df)} entries"},
            {"label": "Total Operating Outflow", "value": format_inr_clean(tot_active_amt)},
            {"label": "Cancelled / Excluded Vouchers", "value": format_inr_clean(cancelled_amt)}
        ]
    }
    return df, meta


def get_forecast_stock_plan_data(
    occurrence_id: int,
    purchasing_budget: float,
    category_id: Optional[int] = None,
    product_ids: Optional[List[int]] = None,
    growth_multiplier: float = 1.10
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Computes deterministic festival procurement plan using historical demand and inventory buffers.
    CLEARLY LABELED AS ESTIMATES AND PLANNING PROJECTIONS.
    """
    plan_items, budget_eval = generate_festival_stock_plan_table(
        occurrence_id=occurrence_id,
        purchasing_budget=purchasing_budget,
        selected_product_ids=product_ids,
        category_id=category_id,
        growth_multiplier=growth_multiplier
    )

    # Convert to DataFrame
    df = pd.DataFrame(plan_items)

    # Fetch Festival Metadata
    conn = get_db_connection()
    fest_info = "Festival Campaign"
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT f.festival_name, fo.year, fo.campaign_start_date, fo.campaign_end_date
            FROM festival_occurrences fo
            JOIN festivals f ON fo.festival_id = f.festival_id
            WHERE fo.occurrence_id = ?
        """, (occurrence_id,))
        f_row = cursor.fetchone()
        if f_row:
            fest_info = f"{f_row['festival_name']} {f_row['year']} ({f_row['campaign_start_date']} to {f_row['campaign_end_date']})"
    finally:
        conn.close()

    meta = {
        "title": f"Forecast-Based Stock Planning Report — {fest_info}",
        "classification": "ESTIMATES & PLANNING PROJECTIONS (Deterministic Formulas — Non-Guaranteed Forecasts)",
        "generated_at": get_current_timestamp_str(),
        "currency": "INR",
        "filters_applied": {
            "Festival Campaign": fest_info,
            "Purchasing Budget": format_inr_clean(purchasing_budget),
            "Target YoY Growth Multiplier": f"{growth_multiplier:.2f}x ({int((growth_multiplier - 1.0) * 100)}% Growth)"
        },
        "calculation_definitions": {
            "Planned Demand (ESTIMATE)": "Deterministic projection from historical festival sales or baseline velocity",
            "Usable Stock (ACTUAL)": "Current physically available unexpired inventory in warehouse",
            "Safety Stock Buffer": "Buffer quantity configured to absorb festive supply chain delays",
            "Suggested Purchase Quantity": "max(0, Planned Demand + Safety Stock - Usable Stock)",
            "Pack Size Rounding": "Rounded up to supplier minimum carton pack size",
            "Estimated Purchase Cost": "Suggested Purchase Quantity * Current Catalog Unit Purchase Cost",
            "Budget Variance": "Total Planned Procurement Cost - Purchasing Budget"
        },
        "summary_kpis": [
            {"label": "Configured Purchasing Budget", "value": format_inr_clean(purchasing_budget)},
            {"label": "Total Estimated Purchase Cost", "value": format_inr_clean(budget_eval['total_planned_cost'])},
            {"label": "Budget Utilization %", "value": f"{budget_eval['budget_utilization_pct']:.1f}%"},
            {"label": "Budget Status", "value": "⚠️ Budget Exceeded" if budget_eval['is_budget_exceeded'] else "✅ Within Budget"},
            {"label": "Variance (Surplus / Excess)", "value": format_inr_clean(budget_eval['overrun_amount']) if budget_eval['is_budget_exceeded'] else format_inr_clean(purchasing_budget - budget_eval['total_planned_cost'])}
        ],
        "budget_analysis": budget_eval
    }
    return df, meta


# ==============================================================================
# 4. UNIFIED CSV EXPORT GENERATOR
# ==============================================================================

def generate_report_csv(df: pd.DataFrame, meta: Dict[str, Any]) -> str:
    """
    Serializes report into official UTF-8 CSV string with structured metadata header,
    data classification label, calculation definitions, and tabular records.
    """
    output = io.StringIO()

    # 1. Metadata & Classification Header
    output.write(f"# ==============================================================================\n")
    output.write(f"# FESTIVEPULSE AI — OFFICIAL RETAIL SYSTEM REPORT\n")
    output.write(f"# Report Title: {meta['title']}\n")
    output.write(f"# DATA CLASSIFICATION: {meta['classification']}\n")
    output.write(f"# Generated On: {meta['generated_at']}\n")
    output.write(f"# Currency: {meta['currency']} (All monetary figures in Indian Rupees)\n")
    output.write(f"# ------------------------------------------------------------------------------\n")
    output.write(f"# ACTIVE FILTERS APPLIED:\n")
    for k, v in meta.get("filters_applied", {}).items():
        output.write(f"#   * {k}: {v}\n")
    output.write(f"# ------------------------------------------------------------------------------\n")
    output.write(f"# CALCULATION DEFINITIONS & FORMULAS:\n")
    for k, v in meta.get("calculation_definitions", {}).items():
        output.write(f"#   * {k}: {v}\n")
    output.write(f"# ==============================================================================\n\n")

    # 2. Main Tabular Data
    if not df.empty:
        # Sanitize against CSV formula injection (DDE) for spreadsheet security
        safe_df = sanitize_df_for_csv(df)
        csv_body = safe_df.to_csv(index=False)
        output.write(csv_body)
    else:
        output.write("# NOTE: No database records matched the selected filter criteria.\n")

    return output.getvalue()


# ==============================================================================
# 5. UNIFIED PROFESSIONAL PDF GENERATOR (REPORTLAB)
# ==============================================================================

def generate_report_pdf(
    df: pd.DataFrame,
    meta: Dict[str, Any],
    orientation: str = "landscape"
) -> bytes:
    """
    Renders professional, publication-grade PDF report using ReportLab:
    - Landscape or Portrait orientation with sensible margins
    - NumberedCanvas (Page X of Y, Timestamp, Currency INR)
    - Repeated table headers (repeatRows=1)
    - Clean distinction between ACTUAL and ESTIMATE classifications
    - Calculation definitions callout box
    - Itemized data table with text auto-wrapping
    - Handles empty reports cleanly
    """
    buffer = io.BytesIO()
    pagesize = landscape(A4) if orientation == "landscape" else A4
    page_w, page_h = pagesize

    # Margins: 10mm left/right, 10mm top/bottom
    doc = SimpleDocTemplate(
        buffer,
        pagesize=pagesize,
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=14 * mm
    )

    styles = getSampleStyleSheet()

    # Custom Typography Tokens
    h_title = ParagraphStyle(
        "RepTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        textColor=colors.HexColor("#0F172A"),
        alignment=TA_LEFT
    )
    h_store = ParagraphStyle(
        "RepStore",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#475569"),
        alignment=TA_RIGHT
    )
    badge_actual = ParagraphStyle(
        "BadgeActual",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#065F46"),
        alignment=TA_LEFT
    )
    badge_estimate = ParagraphStyle(
        "BadgeEstimate",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#9A3412"),
        alignment=TA_LEFT
    )
    filter_style = ParagraphStyle(
        "FilterText",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7.5,
        leading=9.5,
        textColor=colors.HexColor("#334155")
    )
    def_title = ParagraphStyle(
        "DefTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#1E293B")
    )
    def_body = ParagraphStyle(
        "DefBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7,
        leading=9,
        textColor=colors.HexColor("#475569")
    )
    th_style = ParagraphStyle(
        "TH",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7.5,
        leading=9,
        textColor=colors.HexColor("#0F172A"),
        alignment=TA_CENTER
    )
    td_style = ParagraphStyle(
        "TD",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7,
        leading=8.5,
        textColor=colors.HexColor("#1E293B")
    )
    td_right = ParagraphStyle(
        "TDRight",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=7,
        leading=8.5,
        textColor=colors.HexColor("#1E293B"),
        alignment=TA_RIGHT
    )
    td_right_bold = ParagraphStyle(
        "TDRightBold",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7,
        leading=8.5,
        textColor=colors.HexColor("#0F172A"),
        alignment=TA_RIGHT
    )

    story = []

    # 1. Header Row: Store Profile (Left) & Title/Timestamp (Right)
    settings = get_business_settings()
    b_name = settings.get("business_name", "FestivePulse AI Retail Command")
    gstin = settings.get("gstin", "")
    phone = settings.get("phone", "")
    city = settings.get("city", "Mumbai")
    state = settings.get("state", "Maharashtra")

    store_header_html = f"<b>{clean_xml(b_name.upper())}</b><br/>"
    if gstin:
        store_header_html += f"GSTIN: {clean_xml(gstin)} | "
    store_header_html += f"City: {clean_xml(city)}, {clean_xml(state)}<br/>"
    store_header_html += f"Generated: {meta['generated_at']} | Currency: {meta['currency']}"

    is_estimate = "ESTIMATE" in meta["classification"]
    badge_bg = colors.HexColor("#FFEDD5") if is_estimate else colors.HexColor("#D1FAE5")
    badge_border = colors.HexColor("#F97316") if is_estimate else colors.HexColor("#10B981")
    badge_style = badge_estimate if is_estimate else badge_actual

    badge_p = Paragraph(f"● <b>DATA CLASSIFICATION: {clean_xml(meta['classification'])}</b>", badge_style)
    badge_table = Table([[badge_p]], colWidths=[120 * mm if orientation == "landscape" else 95 * mm])
    badge_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), badge_bg),
        ('BOX', (0, 0), (-1, -1), 0.5, badge_border),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
    ]))

    header_table_data = [
        [
            Paragraph(clean_xml(meta["title"]), h_title),
            Paragraph(store_header_html, h_store)
        ],
        [
            badge_table,
            Paragraph("", h_store)
        ]
    ]
    usable_w = (page_w - 20 * mm)
    head_table = Table(header_table_data, colWidths=[usable_w * 0.60, usable_w * 0.40])
    head_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
    ]))
    story.append(head_table)
    story.append(Spacer(1, 3 * mm))

    # 2. Applied Filters & Calculation Definitions Block
    filt_items = [f"<b>{clean_xml(k)}:</b> {clean_xml(v)}" for k, v in meta.get("filters_applied", {}).items()]
    filt_str = " | ".join(filt_items)

    def_items = [f"<b>{clean_xml(k)}:</b> {clean_xml(v)}" for k, v in meta.get("calculation_definitions", {}).items()]
    def_str = "<br/>".join([f"• {item}" for item in def_items])

    param_block_data = [
        [
            Paragraph(f"<b>Active Filter Parameters:</b> {filt_str}", filter_style)
        ],
        [
            Paragraph(f"<b>Calculation Definitions &amp; Methodology:</b><br/>{def_str}", def_body)
        ]
    ]
    param_table = Table(param_block_data, colWidths=[usable_w])
    param_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(param_table)
    story.append(Spacer(1, 3 * mm))

    # 3. Executive KPI Metric Cards
    kpis = meta.get("summary_kpis", [])
    if kpis:
        kpi_cells = []
        for k in kpis:
            k_p = Paragraph(f"<font color='#64748B' size=6>{clean_xml(k['label']).upper()}</font><br/><b><font color='#0F172A' size=8>{clean_xml(k['value'])}</font></b>", td_style)
            kpi_cells.append(k_p)
        
        kpi_w = usable_w / len(kpis)
        kpi_table = Table([kpi_cells], colWidths=[kpi_w] * len(kpis))
        kpi_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#F1F5F9")),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#94A3B8")),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(kpi_table)
        story.append(Spacer(1, 3 * mm))

    # 4. Main Tabular Records
    if df.empty:
        # Empty State
        empty_data = [[
            Paragraph("<b>ℹ️ No records found matching the selected filter parameters.</b><br/>Try broadening your date range or adjusting category/region filters.", def_title)
        ]]
        empty_table = Table(empty_data, colWidths=[usable_w])
        empty_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#FEF2F2")),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#FECACA")),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(empty_table)
    else:
        # Build Table Data
        # Select concise display columns based on report type to fit page perfectly
        disp_cols, col_widths, headers = _get_columns_layout_for_pdf(df, meta["title"], usable_w)

        table_rows = []
        # Header Row
        header_cells = [Paragraph(f"<b>{clean_xml(h)}</b>", th_style) for h in headers]
        table_rows.append(header_cells)

        for _, row in df.iterrows():
            row_cells = []
            for col in disp_cols:
                raw_val = row.get(col, "")
                # Format numbers or money
                if isinstance(raw_val, float):
                    if "pct" in col or "percent" in col:
                        cell_p = Paragraph(f"{raw_val:.1f}%", td_right)
                    elif "amount" in col or "profit" in col or "cost" in col or "revenue" in col or "price" in col or "value" in col or "val" in col:
                        cell_p = Paragraph(f"INR {raw_val:,.2f}", td_right)
                    else:
                        cell_p = Paragraph(f"{raw_val:,.2f}", td_right)
                elif isinstance(raw_val, int):
                    cell_p = Paragraph(f"{raw_val:,}", td_right)
                else:
                    cell_p = Paragraph(clean_xml(str(raw_val)), td_style)
                row_cells.append(cell_p)
            table_rows.append(row_cells)

        # Build Table with repeatRows=1 for repeating headers on every page!
        data_table = Table(table_rows, colWidths=col_widths, repeatRows=1)
        data_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#E2E8F0")),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#94A3B8")),
            ('INNERGRID', (0, 0), (-1, -1), 0.3, colors.HexColor("#E2E8F0")),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ('LEFTPADDING', (0, 0), (-1, -1), 3),
            ('RIGHTPADDING', (0, 0), (-1, -1), 3),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        story.append(data_table)

    # Build Document using NumberedCanvas
    doc.build(story, canvasmaker=NumberedCanvas)
    return buffer.getvalue()


def _get_columns_layout_for_pdf(
    df: pd.DataFrame,
    title: str,
    total_w: float
) -> Tuple[List[str], List[float], List[str]]:
    """Assigns optimal column subsets, widths, and titles for crisp layout rendering."""
    title_lower = title.lower()

    if "sales" in title_lower:
        cols = ["invoice_number", "invoice_date", "customer_name", "sku", "product_name", "quantity", "unit_selling_price", "taxable_value", "total_item_amount", "gross_profit"]
        headers = ["Invoice #", "Date", "Customer", "SKU", "Product Name", "Qty", "Price", "Taxable", "Total Billed", "Gross Profit"]
        # Total widths must equal total_w
        ratios = [0.10, 0.08, 0.12, 0.09, 0.19, 0.05, 0.09, 0.09, 0.10, 0.09]

    elif "inventory" in title_lower:
        cols = ["sku", "product_name", "category", "unit_of_measure", "cost_price", "selling_price", "total_available_stock", "total_cost_valuation", "total_retail_valuation", "status"]
        headers = ["SKU", "Product Name", "Category", "UoM", "Cost", "Price", "Stock", "Cost Value", "Retail Value", "Status"]
        ratios = [0.10, 0.20, 0.12, 0.05, 0.08, 0.08, 0.07, 0.10, 0.10, 0.10]

    elif "stock movement" in title_lower:
        cols = ["movement_id", "created_at", "sku", "product_name", "batch_number", "movement_type", "quantity", "unit_cost", "total_cost_impact", "reason"]
        headers = ["ID", "Timestamp", "SKU", "Product Name", "Batch #", "Type", "Qty", "Unit Cost", "Cost Impact", "Reason"]
        ratios = [0.05, 0.11, 0.09, 0.18, 0.10, 0.10, 0.06, 0.08, 0.09, 0.14]

    elif "festival campaign" in title_lower or "comparative" in title_lower:
        cols = ["festival_name", "year", "invoices_count", "units_sold", "gross_billed", "discounts", "net_revenue", "net_cogs", "gross_profit", "operating_expenses", "net_operating_profit", "roi_pct"]
        headers = ["Festival", "Year", "Bills", "Units", "Gross Sales", "Discounts", "Net Revenue", "Net COGS", "Gross Profit", "Expenses", "Net Profit", "ROI %"]
        ratios = [0.14, 0.05, 0.05, 0.06, 0.09, 0.07, 0.09, 0.09, 0.09, 0.09, 0.10, 0.08]

    elif "expenses" in title_lower:
        cols = ["expense_id", "expense_date", "category", "amount", "description", "status", "vendor_name", "festival_name"]
        headers = ["ID", "Date", "Category", "Amount", "Description", "Status", "Vendor", "Festival Scope"]
        ratios = [0.06, 0.09, 0.12, 0.11, 0.26, 0.08, 0.14, 0.14]

    elif "forecast" in title_lower or "procurement" in title_lower:
        cols = ["sku", "product_name", "category_name", "supplier_name", "usable_stock", "planned_demand", "safety_stock", "edited_purchase_quantity", "unit_cost", "planned_procurement_cost", "procurement_status"]
        headers = ["SKU", "Product Name", "Category", "Supplier", "Stock", "Demand", "Safety", "Order Qty", "Unit Cost", "Est Cost", "Status"]
        ratios = [0.09, 0.18, 0.10, 0.11, 0.06, 0.06, 0.06, 0.07, 0.08, 0.09, 0.10]

    else:
        # Fallback to first available columns in df
        cols = list(df.columns[:8])
        headers = [c.replace("_", " ").title() for c in cols]
        ratios = [1.0 / len(cols)] * len(cols)

    # Filter to existing columns in df
    final_cols = [c for c in cols if c in df.columns]
    # Re-normalize ratios
    final_ratios = [ratios[cols.index(c)] for c in final_cols]
    norm_factor = sum(final_ratios)
    widths = [(r / norm_factor) * total_w for r in final_ratios]
    final_headers = [headers[cols.index(c)] for c in final_cols]

    return final_cols, widths, final_headers
