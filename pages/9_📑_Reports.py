"""
FestivePulse — Comprehensive Operational & Audit Reports Engine
Generates official, downloadable CSV and PDF reports:
1. Sales Summary & Tax Ledger
2. Inventory Valuation & Stock Health
3. Stock Movement Audit Ledger
4. Multi-Year Festival Performance Comparisons
5. Operating Expenses & Overheads
6. Deterministic Forecast-Based Stock Procurement Plans
7. GST Tax Filings & Khata Credit Reconciliation

INVARIANTS:
- 100% Non-AI, deterministic calculations grounded in SQLite records.
- Explicit Report Generation Date, Currency INR, and Calculation Definitions.
- Unambiguous visual classification: ACTUAL (Recorded Database Records) vs ESTIMATES (Deterministic Formulas).
- Unicode-safe ReportLab PDF with repeating table headers (repeatRows=1) and NumberedCanvas page numbering.
- Valid CSV and PDF downloads for both populated and empty filtered states.
"""

from datetime import datetime, date, timedelta
import streamlit as st
import pandas as pd

from database.connection import query_df, db_session
from services.currency_utils import format_inr
from services.ui_components import (
    apply_custom_css,
    render_festival_header,
    render_standard_sidebar
)
from services.reports_service import (
    get_sales_summary_data,
    get_inventory_report_data,
    get_stock_movements_data,
    get_festival_comparisons_data,
    get_expense_summary_data,
    get_forecast_stock_plan_data,
    generate_report_csv,
    generate_report_pdf
)
from config import EXPENSE_CATEGORIES

st.set_page_config(page_title="Operational & Audit Reports — FestivePulse", page_icon="📑", layout="wide")
apply_custom_css()
render_festival_header()
render_standard_sidebar()

st.title("📑 Official Reports & Audit Export Center")
st.caption(
    "All analytical reports are generated strictly from immutable SQLite database ledgers using deterministic formulas. "
    "Every download contains an official generation timestamp, Currency INR, calculation definitions, and a transparent data classification."
)

# Fetch master data for dropdowns
cat_df = query_df("SELECT category_id, category_name FROM product_categories ORDER BY category_name")
category_options = {None: "All Categories"}
for _, r in cat_df.iterrows():
    category_options[int(r["category_id"])] = r["category_name"]

prod_df = query_df("SELECT product_id, sku, product_name FROM products WHERE is_active = 1 ORDER BY product_name")
product_options = {None: "All Products"}
for _, r in prod_df.iterrows():
    product_options[int(r["product_id"])] = f"{r['product_name']} ({r['sku']})"

fest_occ_df = query_df("""
    SELECT fo.occurrence_id, f.festival_name, fo.year, fo.campaign_start_date, fo.campaign_end_date
    FROM festival_occurrences fo
    JOIN festivals f ON fo.festival_id = f.festival_id
    ORDER BY fo.year DESC, f.festival_name ASC
""")
occurrence_options = {None: "All Campaigns / General"}
for _, r in fest_occ_df.iterrows():
    occurrence_options[int(r["occurrence_id"])] = f"{r['festival_name']} {r['year']} ({r['campaign_start_date']} to {r['campaign_end_date']})"

fest_df = query_df("SELECT festival_id, festival_name FROM festivals ORDER BY festival_name")
festival_options = {None: "All Festivals"}
for _, r in fest_df.iterrows():
    festival_options[int(r["festival_id"])] = r["festival_name"]

region_choices = [
    "ALL", "Pan-India", "North India", "South India", "West India", "East India",
    "Maharashtra", "Tamil Nadu", "Gujarat", "West Bengal", "Kerala", "Karnataka", "Telangana", "Delhi NCR"
]

report_tabs = st.tabs([
    "🧾 Sales Summary",
    "📦 Inventory Valuation",
    "📋 Stock Movements",
    "📊 Festival Comparisons",
    "💰 Expense Summary",
    "📈 Forecast Stock Plan",
    "🏛️ GST & Khata Credit"
])


def render_report_header_and_downloads(
    df: pd.DataFrame,
    meta: dict,
    base_filename: str,
    pdf_orientation: str = "landscape"
):
    """Renders classification badge, definitions expander, KPI cards, and CSV/PDF download buttons."""
    is_estimate = "ESTIMATE" in meta.get("classification", "")
    badge_color = "#EA580C" if is_estimate else "#059669"
    badge_bg = "#FFEDD5" if is_estimate else "#D1FAE5"

    st.markdown(
        f"""
        <div style="background-color: {badge_bg}; border-left: 5px solid {badge_color}; padding: 10px 14px; border-radius: 4px; margin-bottom: 12px;">
            <span style="font-weight: 700; color: {badge_color}; font-size: 0.92rem;">● DATA CLASSIFICATION: {meta['classification']}</span><br/>
            <span style="color: #475569; font-size: 0.82rem;">Generated: <b>{meta['generated_at']}</b> | Currency: <b>{meta['currency']} (Indian Rupee)</b></span>
        </div>
        """,
        unsafe_allow_html=True
    )

    # Active Filters & Definitions Expander
    with st.expander("ℹ️ View Calculation Definitions & Filter Parameters", expanded=False):
        c1, c2 = st.columns([1, 1.4])
        with c1:
            st.markdown("**Applied Filter Parameters:**")
            for k, v in meta.get("filters_applied", {}).items():
                st.markdown(f"- **{k}:** `{v}`")
        with c2:
            st.markdown("**Calculation Definitions & Formulas:**")
            for k, v in meta.get("calculation_definitions", {}).items():
                st.markdown(f"- **{k}:** {v}")

    # Executive KPI Metric Cards
    kpis = meta.get("summary_kpis", [])
    if kpis:
        cols = st.columns(len(kpis))
        for idx, kpi in enumerate(kpis):
            with cols[idx]:
                st.metric(label=kpi["label"], value=kpi["value"])

    st.divider()

    # Pre-generate download payloads
    csv_string = generate_report_csv(df, meta)
    csv_bytes = csv_string.encode("utf-8-sig")
    pdf_bytes = generate_report_pdf(df, meta, orientation=pdf_orientation)

    # Download Buttons
    d_col1, d_col2, d_col3 = st.columns([1.2, 1.2, 2.6])
    timestamp_slug = datetime.now().strftime("%Y%m%d_%H%M")
    with d_col1:
        st.download_button(
            label="📄 Download Official PDF Report",
            data=pdf_bytes,
            file_name=f"{base_filename}_{timestamp_slug}.pdf",
            mime="application/pdf",
            use_container_width=True,
            type="primary"
        )
    with d_col2:
        st.download_button(
            label="📊 Download Detailed CSV Data",
            data=csv_bytes,
            file_name=f"{base_filename}_{timestamp_slug}.csv",
            mime="text/csv",
            use_container_width=True
        )
    with d_col3:
        st.caption(f"Includes {len(df)} records | Page Size: A4 ({pdf_orientation.title()}) with repeated headers.")


# ==============================================================================
# TAB 1: SALES SUMMARY & TAX LEDGER
# ==============================================================================
with report_tabs[0]:
    st.subheader("🧾 Sales Summary & Profitability Ledger")
    st.markdown("Consolidated transaction audit of billed invoices, item line totals, GST collections, and gross profit.")

    with st.container(border=True):
        f1, f2, f3 = st.columns(3)
        with f1:
            sales_start = st.date_input("Start Date:", value=date.today() - timedelta(days=90), key="rep_s_start")
        with f2:
            sales_end = st.date_input("End Date:", value=date.today(), key="rep_s_end")
        with f3:
            sales_occ = st.selectbox("Festival Campaign:", options=list(occurrence_options.keys()), format_func=lambda x: occurrence_options[x], key="rep_s_occ")

        f4, f5, f6 = st.columns(3)
        with f4:
            sales_reg = st.selectbox("Customer Region:", options=region_choices, key="rep_s_reg")
        with f5:
            sales_cat = st.selectbox("Product Category:", options=list(category_options.keys()), format_func=lambda x: category_options[x], key="rep_s_cat")
        with f6:
            sales_prod = st.selectbox("Specific Product:", options=list(product_options.keys()), format_func=lambda x: product_options[x], key="rep_s_prod")

    # Fetch data
    sales_df, sales_meta = get_sales_summary_data(
        start_date=sales_start.strftime("%Y-%m-%d"),
        end_date=sales_end.strftime("%Y-%m-%d"),
        occurrence_id=sales_occ,
        region=sales_reg if sales_reg != "ALL" else None,
        product_id=sales_prod,
        category_id=sales_cat
    )

    render_report_header_and_downloads(sales_df, sales_meta, "Sales_Summary_Report", pdf_orientation="landscape")

    if not sales_df.empty:
        disp_s = sales_df.copy()
        for m_col in ["unit_selling_price", "unit_cost_price", "taxable_value", "total_tax", "total_item_amount", "cogs_total", "gross_profit"]:
            if m_col in disp_s.columns:
                disp_s[m_col] = disp_s[m_col].apply(lambda x: format_inr(x))
        if "gross_margin_pct" in disp_s.columns:
            disp_s["gross_margin_pct"] = disp_s["gross_margin_pct"].apply(lambda x: f"{x:.1f}%")

        st.dataframe(disp_s.rename(columns={
            "invoice_number": "Invoice #",
            "invoice_date": "Date",
            "customer_name": "Customer",
            "festival_name": "Campaign",
            "sku": "SKU",
            "product_name": "Product",
            "quantity": "Qty",
            "unit_selling_price": "Rate (₹)",
            "taxable_value": "Taxable (₹)",
            "total_tax": "GST (₹)",
            "total_item_amount": "Total (₹)",
            "gross_profit": "Gross Profit (₹)",
            "gross_margin_pct": "Margin %"
        }), use_container_width=True, height=400)
    else:
        st.info("ℹ️ No sales records found matching the selected date, region, and product filters.")


# ==============================================================================
# TAB 2: INVENTORY VALUATION & STOCK HEALTH
# ==============================================================================
with report_tabs[1]:
    st.subheader("📦 Inventory Asset Valuation & Stock Status Report")
    st.markdown("Current warehouse inventory stock balances, cost asset valuation, counter turnover value, and buffer thresholds.")

    with st.container(border=True):
        i1, i2, i3, i4 = st.columns(4)
        with i1:
            inv_cat = st.selectbox("Category Filter:", options=list(category_options.keys()), format_func=lambda x: category_options[x], key="rep_i_cat")
        with i2:
            inv_reg = st.selectbox("Regional Focus:", options=region_choices, key="rep_i_reg")
        with i3:
            perish_filter = st.selectbox("Perishability:", options=[None, True, False], format_func=lambda x: "All Items" if x is None else ("Perishable Only" if x else "Non-Perishable Only"), key="rep_i_perish")
        with i4:
            st.write("")
            st.write("")
            low_stock_chk = st.checkbox("Show Low Stock Alerts Only", value=False, key="rep_i_low")

    inv_df, inv_meta = get_inventory_report_data(
        category_id=inv_cat,
        low_stock_only=low_stock_chk,
        region=inv_reg if inv_reg != "ALL" else None,
        is_perishable=perish_filter
    )

    render_report_header_and_downloads(inv_df, inv_meta, "Inventory_Valuation_Report", pdf_orientation="landscape")

    if not inv_df.empty:
        disp_i = inv_df.copy()
        for m_col in ["cost_price", "selling_price", "total_cost_valuation", "total_retail_valuation"]:
            if m_col in disp_i.columns:
                disp_i[m_col] = disp_i[m_col].apply(lambda x: format_inr(x))

        st.dataframe(disp_i.rename(columns={
            "sku": "SKU",
            "product_name": "Product Name",
            "category": "Category",
            "unit_of_measure": "UoM",
            "cost_price": "Unit Cost (₹)",
            "selling_price": "Retail Price (₹)",
            "total_available_stock": "On-Hand Stock",
            "min_safety_stock": "Safety Min",
            "total_cost_valuation": "Cost Asset Value (₹)",
            "total_retail_valuation": "Retail Value (₹)",
            "status": "Stock Status"
        }), use_container_width=True, height=400)
    else:
        st.info("ℹ️ No inventory items match the selected filter criteria.")


# ==============================================================================
# TAB 3: STOCK MOVEMENT AUDIT LEDGER
# ==============================================================================
with report_tabs[2]:
    st.subheader("📋 Stock Movement Audit Ledger")
    st.markdown("Chronological, immutable ledger of all inbound receipts, outbound sales depletions, damages, returns, and reconciliations.")

    movement_types = [
        "ALL", "PURCHASE_RECEIPT", "SALE_DEPLETION", "DAMAGE_WRITE_OFF",
        "AUDIT_ADJUSTMENT", "RETURN_RESTOCK", "INVENTORY_TRANSFER", "INITIAL_STOCK"
    ]

    with st.container(border=True):
        m1, m2, m3 = st.columns(3)
        with m1:
            mov_start = st.date_input("Start Date:", value=date.today() - timedelta(days=90), key="rep_m_start")
        with m2:
            mov_end = st.date_input("End Date:", value=date.today(), key="rep_m_end")
        with m3:
            mov_type = st.selectbox("Movement Type:", options=movement_types, key="rep_m_type")

        m4, m5 = st.columns(2)
        with m4:
            mov_cat = st.selectbox("Product Category:", options=list(category_options.keys()), format_func=lambda x: category_options[x], key="rep_m_cat")
        with m5:
            mov_prod = st.selectbox("Specific Product:", options=list(product_options.keys()), format_func=lambda x: product_options[x], key="rep_m_prod")

    mov_df, mov_meta = get_stock_movements_data(
        start_date=mov_start.strftime("%Y-%m-%d"),
        end_date=mov_end.strftime("%Y-%m-%d"),
        product_id=mov_prod,
        category_id=mov_cat,
        movement_type=mov_type if mov_type != "ALL" else None
    )

    render_report_header_and_downloads(mov_df, mov_meta, "Stock_Movement_Audit_Ledger", pdf_orientation="landscape")

    if not mov_df.empty:
        disp_m = mov_df.copy()
        for m_col in ["unit_cost", "total_cost_impact"]:
            if m_col in disp_m.columns:
                disp_m[m_col] = disp_m[m_col].apply(lambda x: format_inr(x))

        st.dataframe(disp_m.rename(columns={
            "movement_id": "Event #",
            "created_at": "Timestamp",
            "movement_type": "Movement Action",
            "quantity": "Units Changed",
            "unit_cost": "Unit Cost (₹)",
            "total_cost_impact": "Cost Impact (₹)",
            "sku": "SKU",
            "product_name": "Product Name",
            "batch_number": "Batch",
            "reason": "Audit Reason"
        }), use_container_width=True, height=400)
    else:
        st.info("ℹ️ No stock movements recorded for the chosen filters.")


# ==============================================================================
# TAB 4: FESTIVAL CAMPAIGN COMPARISONS
# ==============================================================================
with report_tabs[3]:
    st.subheader("📊 Multi-Year Festival Campaign Comparative Analysis")
    st.markdown("Compares financial performance across festive seasons, measuring billed turnover, net margins, campaign expenses, and marketing ROI.")

    with st.container(border=True):
        fc1, fc2, fc3, fc4 = st.columns(4)
        with fc1:
            comp_fest = st.selectbox("Festival:", options=list(festival_options.keys()), format_func=lambda x: festival_options[x], key="rep_fc_fest")
        with fc2:
            comp_yr_from = st.number_input("From Year:", min_value=2020, max_value=2030, value=2024, step=1, key="rep_fc_yf")
        with fc3:
            comp_yr_to = st.number_input("To Year:", min_value=2020, max_value=2030, value=2026, step=1, key="rep_fc_yt")
        with fc4:
            comp_reg = st.selectbox("Region Filter:", options=region_choices, key="rep_fc_reg")

    fest_comp_df, fest_comp_meta = get_festival_comparisons_data(
        festival_id=comp_fest,
        year_start=int(comp_yr_from),
        year_end=int(comp_yr_to),
        region=comp_reg if comp_reg != "ALL" else None
    )

    render_report_header_and_downloads(fest_comp_df, fest_comp_meta, "Festival_Campaign_Comparisons", pdf_orientation="landscape")

    if not fest_comp_df.empty:
        disp_fc = fest_comp_df.copy()
        for m_col in ["gross_billed", "discounts", "net_revenue", "net_cogs", "gross_profit", "operating_expenses", "net_operating_profit"]:
            if m_col in disp_fc.columns:
                disp_fc[m_col] = disp_fc[m_col].apply(lambda x: format_inr(x))
        if "gross_margin_pct" in disp_fc.columns:
            disp_fc["gross_margin_pct"] = disp_fc["gross_margin_pct"].apply(lambda x: f"{x:.1f}%")
        if "roi_pct" in disp_fc.columns:
            disp_fc["roi_pct"] = disp_fc["roi_pct"].apply(lambda x: f"{x:.1f}%")

        st.dataframe(disp_fc.rename(columns={
            "festival_name": "Festival",
            "year": "Year",
            "campaign_window": "Window",
            "invoices_count": "Bills",
            "units_sold": "Units Sold",
            "gross_billed": "Gross Sales (₹)",
            "discounts": "Discounts (₹)",
            "net_revenue": "Net Revenue (₹)",
            "net_cogs": "COGS (₹)",
            "gross_profit": "Gross Profit (₹)",
            "gross_margin_pct": "Margin %",
            "operating_expenses": "Expenses (₹)",
            "net_operating_profit": "Net Profit (₹)",
            "roi_pct": "ROI %"
        }), use_container_width=True, height=350)
    else:
        st.info("ℹ️ No festival occurrences match the selected filter criteria.")


# ==============================================================================
# TAB 5: OPERATING EXPENSE SUMMARY
# ==============================================================================
with report_tabs[4]:
    st.subheader("💰 Operating Expenses & Overheads Summary")
    st.markdown("Audited record of operational overheads (Rent, Logistics, Packaging, Staff Wages, Marketing) categorized and tracked against festival campaigns.")

    exp_cat_codes = ["ALL"] + [c[0] for c in EXPENSE_CATEGORIES]
    exp_cat_labels = {c[0]: c[1] for c in EXPENSE_CATEGORIES}
    exp_cat_labels["ALL"] = "All Expense Categories"

    with st.container(border=True):
        e1, e2, e3 = st.columns(3)
        with e1:
            exp_start = st.date_input("Start Date:", value=date.today() - timedelta(days=90), key="rep_e_start")
        with e2:
            exp_end = st.date_input("End Date:", value=date.today(), key="rep_e_end")
        with e3:
            exp_cat_sel = st.selectbox("Category:", options=exp_cat_codes, format_func=lambda x: exp_cat_labels.get(x, x), key="rep_e_cat")

        e4, e5 = st.columns(2)
        with e4:
            exp_occ_sel = st.selectbox("Festival Campaign Scope:", options=list(occurrence_options.keys()), format_func=lambda x: occurrence_options[x], key="rep_e_occ")
        with e5:
            exp_stat_sel = st.selectbox("Audit Status:", options=["ACTIVE", "REVERSED", "ALL"], index=0, key="rep_e_stat")

    exp_df, exp_meta = get_expense_summary_data(
        start_date=exp_start.strftime("%Y-%m-%d"),
        end_date=exp_end.strftime("%Y-%m-%d"),
        category=exp_cat_sel if exp_cat_sel != "ALL" else None,
        occurrence_id=exp_occ_sel,
        status=exp_stat_sel if exp_stat_sel != "ALL" else None
    )

    render_report_header_and_downloads(exp_df, exp_meta, "Operating_Expenses_Summary", pdf_orientation="landscape")

    if not exp_df.empty:
        disp_e = exp_df.copy()
        if "amount" in disp_e.columns:
            disp_e["amount"] = disp_e["amount"].apply(lambda x: format_inr(x))

        st.dataframe(disp_e.rename(columns={
            "expense_id": "Expense #",
            "expense_date": "Date",
            "category": "Category",
            "amount": "Amount (₹)",
            "description": "Description / Purpose",
            "status": "Audit Status",
            "vendor_name": "Vendor / Payee",
            "festival_name": "Associated Campaign"
        }), use_container_width=True, height=350)
    else:
        st.info("ℹ️ No expense records found matching the active filter criteria.")


# ==============================================================================
# TAB 6: FORECAST-BASED STOCK PROCUREMENT PLAN
# ==============================================================================
with report_tabs[5]:
    st.subheader("📈 Deterministic Forecast-Based Stock Procurement Plan")
    st.markdown(
        "Calculates recommended replenishment quantities using deterministic inventory planning formulas: "
        "`Order Quantity = max(0, Planned Demand + Safety Stock - Usable Stock)`. "
        "Evaluates capital outlay against configured purchasing budgets and highlights top cost contributors."
    )

    # Filter out None from occurrence choices for planning
    valid_occurrences = [k for k in occurrence_options.keys() if k is not None]
    if not valid_occurrences:
        st.warning("Please configure at least one festival occurrence to generate a stock plan.")
    else:
        with st.container(border=True):
            p1, p2, p3 = st.columns(3)
            with p1:
                plan_occ = st.selectbox("Target Festival Campaign:", options=valid_occurrences, format_func=lambda x: occurrence_options[x], key="rep_p_occ")
            with p2:
                plan_budget = st.number_input("Purchasing Budget (₹):", min_value=1000.0, max_value=10000000.0, value=75000.0, step=5000.0, key="rep_p_budg")
            with p3:
                plan_growth = st.slider("Target YoY Demand Growth Multiplier:", min_value=0.8, max_value=2.0, value=1.15, step=0.05, key="rep_p_growth", help="e.g. 1.15x represents 15% planned growth over baseline")

        plan_df, plan_meta = get_forecast_stock_plan_data(
            occurrence_id=plan_occ,
            purchasing_budget=float(plan_budget),
            growth_multiplier=float(plan_growth)
        )

        render_report_header_and_downloads(plan_df, plan_meta, "Forecast_Stock_Procurement_Plan", pdf_orientation="landscape")

        b_eval = plan_meta.get("budget_analysis", {})
        if b_eval.get("is_budget_exceeded"):
            st.error(
                f"⚠️ **Budget Limit Exceeded by {format_inr(b_eval['overrun_amount'])}!** "
                f"Total estimated cost is {format_inr(b_eval['total_planned_cost'])} against budget {format_inr(plan_budget)}. "
                f"Top excess contributors: {', '.join([c['product_name'] for c in b_eval.get('top_excess_contributors', [])[:3]])}"
            )
        else:
            st.success(
                f"✅ **Plan is within budget.** Allocated: {format_inr(plan_budget)} | Estimated Outlay: {format_inr(b_eval.get('total_planned_cost', 0))} | Surplus: {format_inr(plan_budget - b_eval.get('total_planned_cost', 0))}"
            )

        if not plan_df.empty:
            disp_p = plan_df.copy()
            for m_col in ["unit_cost", "planned_procurement_cost"]:
                if m_col in disp_p.columns:
                    disp_p[m_col] = disp_p[m_col].apply(lambda x: format_inr(x))

            st.dataframe(disp_p.rename(columns={
                "sku": "SKU",
                "product_name": "Product Name",
                "category_name": "Category",
                "supplier_name": "Supplier",
                "usable_stock": "Current Stock",
                "planned_demand": "Planned Demand (ESTIMATE)",
                "safety_stock": "Safety Buffer",
                "suggested_purchase_quantity": "Formula Qty",
                "pack_size": "Pack Size",
                "edited_purchase_quantity": "Recommended Order",
                "unit_cost": "Unit Cost (₹)",
                "planned_procurement_cost": "Est. Outlay (₹)",
                "procurement_status": "Procurement Status"
            }), use_container_width=True, height=400)
        else:
            st.info("ℹ️ No active catalog products found for procurement planning.")


# ==============================================================================
# TAB 7: GST LIABILITY & CUSTOMER KHATA CREDIT
# ==============================================================================
with report_tabs[6]:
    st.subheader("🏛️ GST Outward Supply & Customer Khata Reconciliation")
    st.markdown("Consolidated tax liabilities categorized by standard Indian GST slabs and informal customer credit balances.")

    gst_sub1, gst_sub2 = st.tabs(["🏛️ GSTR-3B Tax Summary", "📒 Customer Khata Ledger"])

    with gst_sub1:
        cg1, cg2 = st.columns(2)
        with cg1:
            gst_s = st.date_input("From Date:", value=date.today() - timedelta(days=90), key="gst_start")
        with cg2:
            gst_e = st.date_input("To Date:", value=date.today(), key="gst_end")

        gst_sql = """
            SELECT 
                si.gst_rate,
                SUM(si.taxable_value) AS total_taxable,
                SUM(si.cgst_amount) AS total_cgst,
                SUM(si.sgst_amount) AS total_sgst,
                SUM(si.igst_amount) AS total_igst,
                SUM(si.cgst_amount + si.sgst_amount + si.igst_amount) AS total_tax,
                SUM(si.total_item_amount) AS total_gross_billed
            FROM sales_items si
            JOIN sales_invoices inv ON si.invoice_id = inv.invoice_id
            WHERE inv.status = 'COMPLETED'
              AND inv.invoice_date BETWEEN ? AND ?
            GROUP BY si.gst_rate
            ORDER BY si.gst_rate ASC
        """
        gst_df = query_df(gst_sql, (gst_s.strftime("%Y-%m-%d"), gst_e.strftime("%Y-%m-%d")))

        if not gst_df.empty:
            grand_taxable = gst_df["total_taxable"].sum()
            grand_cgst = gst_df["total_cgst"].sum()
            grand_sgst = gst_df["total_sgst"].sum()
            grand_igst = gst_df["total_igst"].sum()
            grand_tax = gst_df["total_tax"].sum()

            k1, k2, k3, k4 = st.columns(4)
            with k1:
                st.metric("Total Taxable Turnover", format_inr(grand_taxable))
            with k2:
                st.metric("CGST Liability", format_inr(grand_cgst))
            with k3:
                st.metric("SGST Liability", format_inr(grand_sgst))
            with k4:
                st.metric("Total GST Payable", format_inr(grand_tax), delta=f"IGST: {format_inr(grand_igst)}")

            st.divider()

            disp_gst = gst_df.copy()
            disp_gst["gst_rate"] = disp_gst["gst_rate"].apply(lambda x: f"{x:.1f}%")
            for tc in ["total_taxable", "total_cgst", "total_sgst", "total_igst", "total_tax", "total_gross_billed"]:
                disp_gst[tc] = disp_gst[tc].apply(lambda x: format_inr(x))

            st.dataframe(
                disp_gst.rename(columns={
                    "gst_rate": "GST Slab",
                    "total_taxable": "Taxable Value (₹)",
                    "total_cgst": "CGST (₹)",
                    "total_sgst": "SGST (₹)",
                    "total_igst": "IGST (₹)",
                    "total_tax": "Total Tax (₹)",
                    "total_gross_billed": "Gross Billed (₹)"
                }),
                use_container_width=True
            )
        else:
            st.info("No completed sales transactions found in the selected date range.")

    with gst_sub2:
        khata_df = query_df("""
            SELECT customer_id, customer_name, phone, gstin, city, outstanding_credit, credit_limit
            FROM customers
            WHERE outstanding_credit > 0
            ORDER BY outstanding_credit DESC
        """)

        if not khata_df.empty:
            total_credit = khata_df["outstanding_credit"].sum()
            st.warning(f"Total Market Receivables / Outstanding Khata: **{format_inr(total_credit)}** across {len(khata_df)} customers.")

            disp_khata = khata_df.copy()
            disp_khata["outstanding_credit"] = disp_khata["outstanding_credit"].apply(lambda x: format_inr(x))
            disp_khata["credit_limit"] = disp_khata["credit_limit"].apply(lambda x: format_inr(x))

            st.dataframe(disp_khata.rename(columns={
                "customer_name": "Customer Name",
                "phone": "Phone",
                "gstin": "GSTIN",
                "city": "City",
                "outstanding_credit": "Outstanding Due (₹)",
                "credit_limit": "Approved Limit (₹)"
            }), use_container_width=True)

            st.markdown("#### 💵 Settle / Record Khata Payment Recovery")
            col_rec1, col_rec2, col_rec3 = st.columns(3)
            with col_rec1:
                rec_cust_map = {r["customer_id"]: f"{r['customer_name']} (Due: ₹{r['outstanding_credit']:,.0f})" for _, r in khata_df.iterrows()}
                chosen_rec_id = st.selectbox("Select Customer:", options=list(rec_cust_map.keys()), format_func=lambda x: rec_cust_map[x])
            with col_rec2:
                rec_amt = st.number_input("Amount Received (₹):", min_value=1.0, step=500.0, value=1000.0)
            with col_rec3:
                st.write("")
                st.write("")
                if st.button("Record Settlement", type="primary"):
                    with db_session() as conn:
                        cursor = conn.cursor()
                        cursor.execute("""
                            UPDATE customers
                            SET outstanding_credit = MAX(0.0, outstanding_credit - ?)
                            WHERE customer_id = ?
                        """, (rec_amt, chosen_rec_id))
                    st.success(f"Payment of {format_inr(rec_amt)} recorded successfully!")
                    st.rerun()
        else:
            st.success("✅ Excellent! All customer credit accounts are fully cleared. Zero outstanding Khata.")
