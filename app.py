"""
FestivePulse — Festival Sales & Inventory Command Center
Main Application Entrypoint & Executive Overview
Calculates store metrics strictly using actual SQLite records.
"""

import streamlit as st
from config import APP_NAME, APP_TAGLINE, APP_ICON
from database.connection import init_db
from database.seed_data import seed_initial_data
from services.dashboard_service import check_database_state, get_dashboard_kpis
from services.currency_utils import format_compact_inr
from services.ui_components import (
    apply_custom_css,
    render_festival_header,
    render_kpi_card,
    render_standard_sidebar
)

# 1. Page Configuration
st.set_page_config(
    page_title=f"{APP_NAME} — Festival Sales & Inventory",
    page_icon=APP_ICON,
    layout="wide",
    initial_sidebar_state="expanded"
)

# 2. Database Initialization
init_db()

# 3. Apply Theme Styles
apply_custom_css()

# 4. Render Active Festival Top Banner
render_festival_header()

# 5. Check Database State
db_state = check_database_state()

# Main Welcome Hub
st.title("🪔 Welcome to FestivePulse")
st.markdown(
    f"*{APP_TAGLINE}*  \n"
    "**100% Deterministic & Non-AI:** All reorder points, safety buffers, surge multipliers, "
    "and tax liabilities use classical retail formulas and exact Indian accounting standards."
)

# If sample data is active, label it clearly
if db_state["is_sample_data"]:
    st.info(
        f"ℹ️ **{db_state['sample_label']} Active**\n\n"
        "Viewing realistic pre-configured retail demonstration records. "
        "Every KPI card and stock metric computes directly from actual SQLite database records."
    )

# Handle Empty Database State with Helpful Onboarding
if db_state["is_empty"]:
    st.warning("⚠️ **Store Database is Fresh & Empty** — No inventory or sales transactions recorded yet.")
    
    st.markdown("""
    ### 🚀 Getting Started with FestivePulse
    Follow these simple steps to configure your store:
    """)

    o1, o2, o3, o4 = st.columns(4)
    with o1:
        with st.container(border=True):
            st.markdown("#### 1. 🛍️ Add Products")
            st.write("Create your product catalog, categories, selling prices, MRP, and GST slabs.")
            st.page_link("pages/2_🛍️_Products.py", label="Open Products Catalog", icon="🛍️")
    with o2:
        with st.container(border=True):
            st.markdown("#### 2. 📦 Stock Batches")
            st.write("Receive inventory stock batches with costs, suppliers, and expiry dates.")
            st.page_link("pages/3_📦_Inventory.py", label="Open Inventory Manager", icon="📦")
    with o3:
        with st.container(border=True):
            st.markdown("#### 3. 🎉 Festival Calendar")
            st.write("Configure festival dates, regional variations, and procurement windows.")
            st.page_link("pages/5_🎉_Festivals.py", label="Open Festival Calendar", icon="🎉")
    with o4:
        with st.container(border=True):
            st.markdown("#### 4. 🧾 Billing & POS")
            st.write("Record customer sales with instant GST calculation and stock deduction.")
            st.page_link("pages/4_🧾_Billing_POS.py", label="Open POS Counter", icon="🧾")

    st.markdown("---")
    st.subheader("💡 Want to explore with realistic retail data first?")
    st.markdown("Click below to populate authentic Indian festival sales records, seasonal stock, and products.")

    if st.button("🚀 Load Demonstration Sample Data", type="primary", key="btn_load_sample_data_home"):
        seed_initial_data()
        st.success("Demo dataset loaded successfully! Reloading...")
        st.rerun()

    st.stop()

# 6. Actual Live KPIs from SQLite
kpis = get_dashboard_kpis()

st.subheader("⚡ Live Store Performance Snapshot")
kpi_c1, kpi_c2, kpi_c3, kpi_c4, kpi_c5, kpi_c6 = st.columns(6)

with kpi_c1:
    render_kpi_card(
        label="Total Sales",
        value=format_compact_inr(kpis["total_sales"]),
        subtext=f"{kpis['invoice_count']} Invoices Net",
        is_good=True
    )

with kpi_c2:
    render_kpi_card(
        label="Sales This Month",
        value=format_compact_inr(kpis["sales_this_month"]),
        subtext=kpis["current_month_name"],
        is_good=True
    )

with kpi_c3:
    render_kpi_card(
        label="Gross Profit",
        value=format_compact_inr(kpis["gross_profit"]),
        subtext=f"Cost Coverage: {kpis['cost_coverage_pct']}%",
        is_good=kpis["gross_profit"] >= 0
    )

with kpi_c4:
    render_kpi_card(
        label="Inventory Value",
        value=format_compact_inr(kpis["current_inventory_value"]),
        subtext="Valuation at Cost",
        is_good=True
    )

with kpi_c5:
    ls_count = kpis["low_stock_product_count"]
    render_kpi_card(
        label="Low-Stock SKUs",
        value=str(ls_count),
        subtext="Below Safety Buffer",
        delta="Order Required" if ls_count > 0 else "Optimal",
        is_good=ls_count == 0
    )

with kpi_c6:
    up_count = len(kpis["upcoming_festivals"])
    sub_desc = f"{kpis['upcoming_festivals'][0]['festival_name']} ({kpis['upcoming_festivals'][0]['days_until']}d)" if up_count > 0 else "None pending"
    render_kpi_card(
        label="Upcoming Festivals",
        value=f"{up_count} Configured",
        subtext=sub_desc,
        is_good=True
    )

st.divider()

# Quick Actions Grid
st.subheader("🚀 Quick Action Hub")
a1, a2, a3, a4 = st.columns(4)

with a1:
    st.info("🧾 **Point of Sale (POS)**\n\nGenerate rapid customer bills with instant GST calculation, UPI QR, and PDF receipts.")
    st.page_link("pages/4_🧾_Billing_POS.py", label="Open POS Counter", icon="🧾")

with a2:
    st.warning("🛒 **Reorder Advisor**\n\nDeterministic procurement sheets with lead time, safety stock, and perishable shelf-life split orders.")
    st.page_link("pages/7_🛒_Reorder_Advisor.py", label="View Reorder Advice", icon="🛒")

with a3:
    st.success("📈 **Executive Dashboard**\n\nInteractive charts for revenue trends, top-selling products, and stock health.")
    st.page_link("pages/1_📊_Dashboard.py", label="Open Full Analytics Dashboard", icon="📊")

with a4:
    st.error("🎉 **Festival Calendar**\n\nConfigure regional dates, overlapping planning windows, and 200-year future projections.")
    st.page_link("pages/5_🎉_Festivals.py", label="Open Festival Calendar", icon="🎉")

# Standard Sidebar with Store Profile & Developer Info
render_standard_sidebar()
