"""
FestivePulse — Executive Festival Analytics Dashboard
Visual KPIs, sales pace vs target, category mix, and payment distribution.
Calculates metrics strictly using actual SQLite records without hardcoding or fabricated data.
"""

from typing import Optional
from datetime import date, timedelta
import streamlit as st
import plotly.express as px

from database.queries import get_categories, get_products_with_stock
from database.seed_data import seed_initial_data
from services.dashboard_service import (
    check_database_state,
    get_dashboard_kpis,
    get_revenue_over_time,
    get_top_selling_products,
    get_stock_status_breakdown,
    get_festival_period_comparisons
)
from services.currency_utils import format_inr
from services.ui_components import (
    apply_custom_css,
    render_festival_header,
    render_kpi_card,
    get_festive_plotly_layout,
    render_standard_sidebar
)

# 1. Page Configuration & Theme
st.set_page_config(page_title="Executive Dashboard — FestivePulse", page_icon="📊", layout="wide")
apply_custom_css()
render_festival_header()
render_standard_sidebar()

# 2. Check Database State (Empty vs Populated vs Sample Demo Data)
db_state = check_database_state()

# Title
st.title("📊 FestivePulse Retail Command Center")
st.caption("Live business intelligence computed directly from your SQLite transactional ledger.")

# If sample data is active, label it clearly
if db_state["is_sample_data"]:
    st.info(
        f"ℹ️ **{db_state['sample_label']}**\n\n"
        "You are viewing realistic Indian festival demonstration records. "
        "Every KPI, chart point, and inventory value reflects actual SQLite database records."
    )

# 3. EMPTY DATABASE ONBOARDING SCREEN
if db_state["is_empty"]:
    st.warning("⚠️ **Your Store Database is Fresh & Empty** — No products or sales records found.")
    
    st.markdown("""
    ### 🚀 Getting Started with FestivePulse
    Follow these four simple steps to begin managing your festive retail store:
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

    if st.button("🚀 Load Demonstration Sample Data", type="primary", key="btn_load_sample_data"):
        seed_initial_data()
        st.success("Demo dataset loaded successfully! Reloading dashboard...")
        st.rerun()

    # Gracefully stop further execution so no empty charts or fake values render
    st.stop()


# 4. INTERACTIVE FILTER TOOLBAR
st.markdown("### 🔍 Dashboard Filters")
filter_col1, filter_col2, filter_col3, filter_col4 = st.columns([1.5, 1.2, 1.5, 0.8])

with filter_col1:
    date_preset = st.selectbox(
        "Date Period:",
        options=[
            "All Time",
            "This Month",
            "Last 30 Days",
            "Last 90 Days",
            "Custom Date Range"
        ],
        index=0
    )

today = date.today()
start_filter: Optional[date] = None
end_filter: Optional[date] = None

if date_preset == "This Month":
    start_filter = date(today.year, today.month, 1)
    end_filter = today
elif date_preset == "Last 30 Days":
    start_filter = today - timedelta(days=30)
    end_filter = today
elif date_preset == "Last 90 Days":
    start_filter = today - timedelta(days=90)
    end_filter = today
elif date_preset == "Custom Date Range":
    with filter_col1:
        c_sub1, c_sub2 = st.columns(2)
        with c_sub1:
            start_filter = st.date_input("Start Date", value=today - timedelta(days=30))
        with c_sub2:
            end_filter = st.date_input("End Date", value=today)

# Category Filter
categories_df = get_categories()
cat_options = {"all": "All Categories"}
if not categories_df.empty:
    for _, row in categories_df.iterrows():
        cat_options[row["category_id"]] = row["category_name"]

with filter_col2:
    selected_cat_key = st.selectbox(
        "Product Category:",
        options=list(cat_options.keys()),
        format_func=lambda x: cat_options[x],
        index=0
    )
selected_cat_id = None if selected_cat_key == "all" else int(selected_cat_key)

# Product Filter
prods_df = get_products_with_stock(category_id=selected_cat_id)
prod_options = {"all": "All Products"}
if not prods_df.empty:
    for _, row in prods_df.iterrows():
        prod_options[row["product_id"]] = f"{row['product_name']} ({row['sku']})"

with filter_col3:
    selected_prod_key = st.selectbox(
        "Specific Product:",
        options=list(prod_options.keys()),
        format_func=lambda x: prod_options[x],
        index=0
    )
selected_prod_id = None if selected_prod_key == "all" else int(selected_prod_key)

with filter_col4:
    st.write("")
    st.write("")
    if st.button("🔄 Reset", help="Clear all filters back to All Time"):
        st.rerun()

st.markdown("---")


# 5. FETCH ACTUAL KPIS FROM SQLITE
kpis = get_dashboard_kpis(
    start_date=start_filter,
    end_date=end_filter,
    category_id=selected_cat_id,
    product_id=selected_prod_id,
    reference_date=today
)

# Render 6 Mandatory KPI Cards
kpi_row1_col1, kpi_row1_col2, kpi_row1_col3 = st.columns(3)
kpi_row2_col1, kpi_row2_col2, kpi_row2_col3 = st.columns(3)

with kpi_row1_col1:
    render_kpi_card(
        label="Total Sales Revenue",
        value=format_inr(kpis["total_sales"]),
        subtext=f"{kpis['invoice_count']} Invoices (Net of Returns)",
        delta="Filtered Scope" if (start_filter or selected_cat_id or selected_prod_id) else "Lifetime Net",
        is_good=True
    )

with kpi_row1_col2:
    render_kpi_card(
        label="Sales This Month",
        value=format_inr(kpis["sales_this_month"]),
        subtext=f"Total in {kpis['current_month_name']}",
        delta="Current Pacing",
        is_good=True
    )

with kpi_row1_col3:
    render_kpi_card(
        label="Gross Profit",
        value=format_inr(kpis["gross_profit"]),
        subtext=f"Cost Data Available: {kpis['cost_coverage_pct']}% of items sold",
        delta="Profitable" if kpis["gross_profit"] > 0 else "No profit recorded",
        is_good=kpis["gross_profit"] >= 0
    )

with kpi_row2_col1:
    render_kpi_card(
        label="Current Inventory Valuation",
        value=format_inr(kpis["current_inventory_value"]),
        subtext="Available stock valuation at cost price",
        delta="In Warehouse",
        is_good=True
    )

with kpi_row2_col2:
    ls_count = kpis["low_stock_product_count"]
    render_kpi_card(
        label="Low-Stock SKUs",
        value=f"{ls_count} / {kpis['total_products']}",
        subtext="Products at or below safety stock",
        delta="Reorder Required" if ls_count > 0 else "Stock Healthy",
        is_good=ls_count == 0
    )

with kpi_row2_col3:
    upcoming_count = len(kpis["upcoming_festivals"])
    next_fest_desc = kpis["upcoming_festivals"][0]["festival_name"] if upcoming_count > 0 else "None pending"
    next_days = kpis["upcoming_festivals"][0]["days_until"] if upcoming_count > 0 else 0
    sub_desc = f"Next: {next_fest_desc} in {next_days}d" if upcoming_count > 0 else "All current festivals concluded"

    render_kpi_card(
        label="Upcoming Configured Festivals",
        value=f"{upcoming_count} Festivals",
        subtext=sub_desc,
        delta="Calendar Active",
        is_good=True
    )


# 6. UPCOMING FESTIVALS QUICK CARDS
if kpis["upcoming_festivals"]:
    with st.expander("🎉 **Upcoming Configured Festivals & Planning Windows**", expanded=False):
        u_cols = st.columns(min(len(kpis["upcoming_festivals"]), 4))
        for idx, u in enumerate(kpis["upcoming_festivals"][:4]):
            with u_cols[idx]:
                with st.container(border=True):
                    st.markdown(f"**{u['festival_name']}**")
                    st.caption(f"📍 {u['region']} • {u['category']}")
                    st.markdown(f"🗓️ **{u['start_date']}** ({u['days_until']} days away)")
                    st.caption(f"🛒 Prep Window: {u['planning_window_days']} days prior (Starts {u['planning_start_date']})")
                    if u.get("is_sample_date") and not u.get("is_verified"):
                        st.caption("⚠️ Sample date")
                    else:
                        st.caption("✅ Verified date")


st.divider()


# 7. INTERACTIVE CHARTS GRID (REFLECTING ACTUAL FILTERS)
st.subheader("📈 Performance Charts & Analytical Breakdown")

chart_row1_c1, chart_row1_c2 = st.columns([1.5, 1])

# CHART 1: REVENUE OVER TIME
with chart_row1_c1:
    st.markdown("#### 📅 Revenue Over Time")
    rev_trend_df = get_revenue_over_time(
        start_date=start_filter,
        end_date=end_filter,
        category_id=selected_cat_id,
        product_id=selected_prod_id
    )

    if not rev_trend_df.empty and len(rev_trend_df) >= 2:
        fig_trend = px.area(
            rev_trend_df,
            x="invoice_date",
            y="revenue",
            markers=True,
            title="Daily Net Sales Run-Rate (₹)",
            labels={"invoice_date": "Sale Date", "revenue": "Revenue (₹)"},
            color_discrete_sequence=["#D97706"]
        )
        fig_trend.update_layout(get_festive_plotly_layout())
        fig_trend.update_traces(line=dict(width=3), fillcolor="rgba(217, 119, 6, 0.25)")
        st.plotly_chart(fig_trend, use_container_width=True)
    elif not rev_trend_df.empty and len(rev_trend_df) == 1:
        st.info(f"Recorded 1 transaction date in this period: **{rev_trend_df.iloc[0]['invoice_date']}** — ₹{rev_trend_df.iloc[0]['revenue']:,.2f}. Additional daily sales will render a trend line.")
    else:
        st.info("No sales transactions found for the selected date range and filters.")

# CHART 2: TOP-SELLING PRODUCTS
with chart_row1_c2:
    st.markdown("#### 🏆 Top-Selling Products")
    top_prods_df = get_top_selling_products(
        limit=8,
        start_date=start_filter,
        end_date=end_filter,
        category_id=selected_cat_id
    )

    if not top_prods_df.empty:
        fig_top = px.bar(
            top_prods_df.sort_values(by="total_revenue", ascending=True),
            x="total_revenue",
            y="product_name",
            orientation="h",
            title="Revenue by Product (₹)",
            labels={"total_revenue": "Revenue (₹)", "product_name": "Product"},
            color="total_revenue",
            color_continuous_scale="Viridis"
        )
        fig_top.update_layout(get_festive_plotly_layout(), showlegend=False)
        fig_top.update_traces(texttemplate="₹%{x:,.0f}", textposition="outside")
        st.plotly_chart(fig_top, use_container_width=True)
    else:
        st.info("No sales recorded for products matching active filters.")


chart_row2_c1, chart_row2_c2 = st.columns(2)

# CHART 3: STOCK STATUS HEALTH
with chart_row2_c1:
    st.markdown("#### 📦 Stock Health Status")
    stock_df = get_stock_status_breakdown(category_id=selected_cat_id)

    if not stock_df.empty:
        status_summary = stock_df.groupby("stock_status").agg(
            product_count=("product_id", "count"),
            total_value=("stock_value", "sum")
        ).reset_index()

        fig_stock = px.pie(
            status_summary,
            names="stock_status",
            values="product_count",
            hole=0.45,
            title="Product SKU Availability",
            color="stock_status",
            color_discrete_map={
                "In Stock": "#10B981",
                "Low Stock": "#F59E0B",
                "Out of Stock": "#EF4444"
            }
        )
        fig_stock.update_layout(get_festive_plotly_layout())
        fig_stock.update_traces(textinfo="label+value+percent", textfont=dict(color="#FFFFFF"))
        st.plotly_chart(fig_stock, use_container_width=True)
    else:
        st.info("No active products in inventory.")

# CHART 4: FESTIVAL-PERIOD COMPARISONS (WHEN ENOUGH DATA EXISTS)
with chart_row2_c2:
    st.markdown("#### 🪔 Festival-Period Sales Comparisons")
    fest_comp_df = get_festival_period_comparisons()

    if not fest_comp_df.empty and len(fest_comp_df) >= 2:
        fest_comp_df["label"] = fest_comp_df["festival_name"] + " (" + fest_comp_df["year"].astype(str) + ")"
        fig_fest = px.bar(
            fest_comp_df,
            x="label",
            y="campaign_revenue",
            title="Actual Revenue by Festival Campaign Period",
            labels={"label": "Festival & Year", "campaign_revenue": "Total Revenue (₹)"},
            color="festival_name",
            color_discrete_sequence=["#D97706", "#E11D48", "#059669", "#3B82F6"]
        )
        fig_fest.update_layout(get_festive_plotly_layout(), showlegend=False)
        fig_fest.update_traces(texttemplate="₹%{y:,.0f}", textposition="outside")
        st.plotly_chart(fig_fest, use_container_width=True)
    elif not fest_comp_df.empty and len(fest_comp_df) == 1:
        row = fest_comp_df.iloc[0]
        st.info(
            f"ℹ️ **Single Campaign Recorded:** {row['festival_name']} {row['year']} (Revenue: {format_inr(row['campaign_revenue'])}, {int(row['total_invoices'])} invoices). "
            "Comparative cross-festival bar charts will automatically display as additional festival campaigns are executed."
        )
    else:
        st.info("No festival campaigns have recorded sales yet. Once festival-tagged sales are billed, comparative charts will appear here.")
