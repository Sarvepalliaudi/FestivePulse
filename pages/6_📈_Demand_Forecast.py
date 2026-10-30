"""
FestivePulse — Transparent, Non-AI Festival Demand Estimation
Auditable Operations Research Models Grounded in Empirical Sales History.
No AI, no black boxes, no fabricated data, no guaranteed outcome claims.
"""

import streamlit as st
import plotly.express as px
from database.queries import get_all_festival_occurrences, get_categories
from services.demand_estimation_service import generate_demand_forecast_table
from services.currency_utils import format_inr
from services.ui_components import (
    apply_custom_css,
    render_festival_header,
    get_festive_plotly_layout,
    render_standard_sidebar
)

st.set_page_config(page_title="Demand Forecast — FestivePulse", page_icon="📈", layout="wide")
apply_custom_css()
render_festival_header()
render_standard_sidebar()

st.title("📈 Transparent Festival Demand Estimation")
st.markdown(
    "**Auditable Operations Research:** Grounded purely in empirical sales transactions stored in FestivePulse SQLite. "
    "Compares daily sales across previous festival occurrences and baseline periods, accounting for differing campaign durations. "
    "Zero AI models, zero fabricated figures, zero black boxes."
)

# Initialize session state for manual planning overrides if not present
if "manual_demand_overrides" not in st.session_state:
    st.session_state["manual_demand_overrides"] = {}

# Target Festival Selection
occ_df = get_all_festival_occurrences()
if occ_df.empty:
    st.warning("⚠️ No festival occurrences found in database. Configure festivals in Festival Management first.")
    st.stop()

occ_options = {}
for _, r in occ_df.iterrows():
    s_dt = str(r["campaign_start_date"])
    e_dt = str(r["campaign_end_date"])
    occ_options[r["occurrence_id"]] = f"{r['festival_name']} {r['year']} ({s_dt} to {e_dt})"

default_occ = next((r["occurrence_id"] for _, r in occ_df.iterrows() if r["is_current_active"]), list(occ_options.keys())[0])

# Top Controls Bar
st.subheader("⚙️ Planning Parameters & Filters")
col_sel1, col_sel2, col_sel3, col_sel4 = st.columns([1.6, 1.0, 1.0, 1.2])

occ_keys = list(occ_options.keys())
default_occ_idx = occ_keys.index(default_occ) if default_occ in occ_keys else 0

with col_sel1:
    target_occ = st.selectbox(
        "Target Festival Campaign:",
        options=occ_keys,
        format_func=lambda x: occ_options[x],
        index=default_occ_idx
    )

with col_sel2:
    growth_factor = st.slider(
        "Target Growth Factor (g):",
        min_value=0.5,
        max_value=2.5,
        value=1.10,
        step=0.05,
        format="%.2fx",
        help="Planned retail volume growth rate. 1.10x represents a planned +10% increase over past festival run-rate."
    )
    st.caption(f"Applies {(growth_factor - 1.0) * 100:+.0f}% planned growth factor.")

with col_sel3:
    cats = get_categories()
    cat_opts = {0: "All Categories"}
    for _, c in cats.iterrows():
        cat_opts[c["category_id"]] = c["category_name"]
    filter_cat = st.selectbox("Product Category:", options=list(cat_opts.keys()), format_func=lambda x: cat_opts[x])

with col_sel4:
    trim_spikes = st.checkbox(
        "Trim Institutional Spikes",
        value=False,
        help="When enabled, if a single day accounted for ≥50% of historical sales (e.g. bulk corporate gifting), "
             "it is normalized to the median daily retail rate to prevent overstocking."
    )
    if st.button("🔄 Reset Manual Overrides"):
        st.session_state["manual_demand_overrides"] = {}
        st.rerun()

cat_arg = None if filter_cat == 0 else filter_cat

# Generate Forecast Table
forecast_df = generate_demand_forecast_table(
    target_occurrence_id=target_occ,
    category_id=cat_arg,
    growth_multiplier=growth_factor,
    trim_spikes=trim_spikes,
    manual_overrides=st.session_state["manual_demand_overrides"]
)

# Prominent Uncertainty Limitations & Disclaimers Banner
st.info(
    "🛡️ **Uncertainty Limitations & Planning Notice:**\n"
    "- **Non-Guaranteed Estimates:** Projections are purely operational benchmarks derived from historical daily sales and do not guarantee future revenue.\n"
    "- **Exogenous Factors:** Calculations do not account for external macroeconomic shifts, unseasonable weather, or hyper-local competitor discounting.\n"
    "- **Forecast Isolation:** Demand projections remain strictly isolated within planning worksheets and are never written to actual sales ledgers."
)

if not forecast_df.empty:
    # Summary Metrics
    total_proj_units = int(forecast_df["estimated_units"].sum())
    empirical_units = int(forecast_df[forecast_df["is_manual"] == False]["estimated_units"].sum())
    manual_units = int(forecast_df[forecast_df["is_manual"] == True]["estimated_units"].sum())
    insufficient_count = int((forecast_df["status"] == "INSUFFICIENT_HISTORICAL_DATA").sum())

    total_proj_rev = float(forecast_df["estimated_revenue"].sum())
    total_proj_cost = float(forecast_df["estimated_cost"].sum())
    total_proj_profit = float(forecast_df["estimated_profit"].sum())
    margin_pct = (total_proj_profit / total_proj_rev * 100.0) if total_proj_rev > 0 else 0.0

    st.markdown("### 📊 Overall Festival Campaign Projections")
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric(
            "Total Projected Units",
            f"{total_proj_units:,} units",
            help="Sum of all empirical run-rate estimates plus user-defined manual planning targets."
        )
        st.caption(f"📈 Empirical: {empirical_units:,} | ✏️ Manual: {manual_units:,} | ⚠️ Cold Start: {insufficient_count} SKUs")

    with m2:
        st.metric("Projected Festival Revenue", format_inr(total_proj_rev))
        st.caption("Based on current catalog selling prices.")

    with m3:
        st.metric("Projected COGS Capital Required", format_inr(total_proj_cost))
        st.caption("Estimated procurement expenditure at cost price.")

    with m4:
        st.metric(
            "Projected Gross Margin",
            format_inr(total_proj_profit),
            delta=f"{margin_pct:.1f}% Margin"
        )
        st.caption("Estimated revenue minus estimated COGS.")

    st.divider()

    # Methodology & Documentation Expander
    with st.expander("📖 Documented Calculation Methodology & Mathematical Formulas", expanded=False):
        st.markdown(r"""
        #### 1. Duration-Normalized Previous Festival Run-Rate (YoY)
        Applied when FestivePulse finds sales transactions for this product during a prior occurrence of the **same festival**.
        
        $$\text{Historical Daily Sales Rate} = \frac{U_{\text{hist}}}{D_{\text{hist}}}$$
        $$\text{Estimated Units} = \left\lceil \left(\frac{U_{\text{hist}}}{D_{\text{hist}}}\right) \times D_{\text{target}} \times g \right\rceil$$
        
        - $U_{\text{hist}}$: Actual units sold during the previous festival occurrence.
        - $D_{\text{hist}}$: Number of calendar days in the historical festival campaign.
        - $D_{\text{target}}$: Number of calendar days in the target festival campaign.
        - $g$: User-selected planned business growth multiplier (e.g. $1.10 = +10\%$).
        - Normalizing by daily rate ensures partial or varying campaign durations do not distort projections.

        ---

        #### 2. Off-Season Baseline Run-Rate with Category Surge Multiplier
        Applied when no prior festival occurrence sales exist for this SKU, but recent non-festival sales (past 60 days) exist.
        
        $$\text{Baseline Daily Sales Rate} = \frac{U_{\text{base}}}{60}$$
        $$\text{Estimated Units} = \left\lceil \left(\frac{U_{\text{base}}}{60}\right) \times M_{\text{surge}} \times D_{\text{target}} \times g \right\rceil$$
        
        - $M_{\text{surge}}$: Empirical category surge multiplier configured for this festival (e.g. $2.5\times$ for Sweets during Diwali).

        ---

        #### 3. Cold Start / Insufficient Historical Data
        If **zero historical sales** exist for a product across both festival and baseline periods:
        - FestivePulse displays **"Insufficient historical data"** and projects **0 units**.
        - **No fake numbers are invented.**
        - Retail managers are provided an optional, clearly labelled **Manual Planning Estimate** input:
        
        $$\text{Manual Target Units} = \left\lceil \text{Manual Daily Units} \times D_{\text{target}} \right\rceil$$
        
        - Clearly flagged in all reports as: `✏️ [Manual Planning Estimate — User-Defined Assumption]`.

        ---

        #### 4. Institutional Bulk Spike Detection
        If a single day or invoice represents $\ge 50\%$ of the entire historical period's sales (and $\ge 10$ units), it is flagged as an institutional/corporate bulk order.
        When **"Trim Institutional Spikes"** is enabled, the outlier day is normalized to the median daily retail rate to prevent ordering excess inventory for one-time corporate gifts.
        """)

    # Visual Chart
    st.subheader("📊 Projected Units by Product & Estimation Status")
    color_map = {
        "EMPIRICAL_FESTIVAL_YOY": "#059669",
        "EMPIRICAL_RECENT_BASELINE": "#2563EB",
        "INSUFFICIENT_HISTORICAL_DATA": "#DC2626",
        "MANUAL_PLANNING_ESTIMATE": "#D97706"
    }

    fig_bar = px.bar(
        forecast_df,
        x="product_name",
        y="estimated_units",
        color="status",
        text="estimated_units",
        labels={
            "product_name": "Product Name",
            "estimated_units": "Estimated Demand Units",
            "status": "Estimation Category"
        },
        title=f"Projected Units Breakdown — {occ_options[target_occ]}",
        color_discrete_map=color_map,
        hover_data=["sku", "category_name", "daily_run_rate", "baseline_period", "status_label"]
    )
    fig_bar.update_layout(get_festive_plotly_layout(), xaxis_tickangle=-25)
    fig_bar.update_traces(textposition="outside")
    st.plotly_chart(fig_bar, use_container_width=True)

    # Auditable Demand Worksheet
    st.subheader("📋 Auditable Demand Worksheet")
    st.caption("Every calculation is step-by-step verified against SQLite transactional records. No simulated figures.")

    # Format display columns
    display_df = forecast_df.copy()
    display_df["sample_size_str"] = display_df.apply(
        lambda r: f"{r['hist_units_sold']} units ({r['hist_transactions']} tx / {r['hist_period_days']} days)"
        if r["hist_units_sold"] > 0 else "0 tx (No History)",
        axis=1
    )
    display_df["formatted_rev"] = display_df["estimated_revenue"].apply(format_inr)
    display_df["formatted_cost"] = display_df["estimated_cost"].apply(format_inr)
    display_df["formatted_profit"] = display_df["estimated_profit"].apply(format_inr)

    view_table = display_df[[
        "status_label",
        "sku",
        "product_name",
        "category_name",
        "estimated_units",
        "daily_run_rate",
        "sample_size_str",
        "baseline_period",
        "arithmetic_breakdown",
        "formatted_rev",
        "formatted_cost",
        "formatted_profit"
    ]].rename(columns={
        "status_label": "Evidence Status",
        "sku": "SKU",
        "product_name": "Product",
        "category_name": "Category",
        "estimated_units": "Projected Units",
        "daily_run_rate": "Daily Rate (units/day)",
        "sample_size_str": "Historical Sample Size",
        "baseline_period": "Baseline Period",
        "arithmetic_breakdown": "Calculation Breakdown",
        "formatted_rev": "Projected Sales (₹)",
        "formatted_cost": "Cost (₹)",
        "formatted_profit": "Gross Margin (₹)"
    })

    st.dataframe(view_table, use_container_width=True, hide_index=True)

    # CSV Export Button
    csv_bytes = forecast_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="📥 Export Auditable Demand Forecast (CSV)",
        data=csv_bytes,
        file_name=f"festivepulse_demand_forecast_occ_{target_occ}.csv",
        mime="text/csv",
        help="Export full audit table including historical sample sizes, formulas, and arithmetic breakdowns."
    )

    st.divider()

    # Interactive SKU Drilldown & Manual Planning Studio
    st.subheader("🔍 SKU Drilldown & Manual Planning Studio")
    st.markdown("Inspect the mathematical audit trail for any SKU or provide a manual planning estimate for cold-start products.")

    sku_options = {row["product_id"]: f"{row['sku']} — {row['product_name']} ({row['status']})" for _, row in forecast_df.iterrows()}
    selected_pid = st.selectbox(
        "Select Product for Deep Audit:",
        options=list(sku_options.keys()),
        format_func=lambda x: sku_options[x]
    )

    selected_row = forecast_df[forecast_df["product_id"] == selected_pid].iloc[0]

    col_drill1, col_drill2 = st.columns([1.2, 1.0])

    with col_drill1:
        st.markdown(f"#### Audit Breakdown: **{selected_row['product_name']}** (`{selected_row['sku']}`)")
        st.markdown(f"**Evidence Category:** `{selected_row['status_label']}`")
        st.markdown(f"**Baseline Period:** {selected_row['baseline_period']}")
        st.markdown(f"**Target Window:** {selected_row['target_period_days']} days")
        st.markdown(f"**Historical Sample Size:** {selected_row['hist_units_sold']} units across {selected_row['hist_transactions']} transactions in {selected_row['hist_period_days']} days")
        
        st.markdown("##### 📐 Formula Applied")
        st.code(f"{selected_row['formula_name']}\n{selected_row['formula_latex']}", language="markdown")

        st.markdown("##### 🧮 Step-by-Step Arithmetic")
        st.success(f"**Calculation:** {selected_row['arithmetic_breakdown']}")

        if selected_row["has_spike"]:
            st.warning(f"⚠️ **Institutional Spike Notice:** {selected_row['spike_description']}")

        st.markdown("##### 🛡️ Specific Uncertainty Limitations")
        st.write(selected_row["uncertainty_note"])

    with col_drill2:
        st.markdown("#### ✏️ Manual Planning Estimate Override")
        st.caption(
            "For cold-start products with **'Insufficient historical data'**, specify an operational planning target. "
            "This will be clearly labelled as a user-defined manual assumption in all reports."
        )

        current_override = st.session_state["manual_demand_overrides"].get(selected_pid, 0.0)
        target_days = int(selected_row["target_period_days"])

        with st.form(key=f"manual_override_form_{selected_pid}"):
            manual_daily = st.number_input(
                "Planned Daily Sales Target (units/day):",
                min_value=0.0,
                max_value=1000.0,
                value=float(current_override),
                step=1.0,
                help=f"Multiplying this by {target_days} target festival days computes total planned units."
            )
            
            calc_manual_total = int(manual_daily * target_days)
            st.caption(f"Planned Campaign Total: **{calc_manual_total} units** ({manual_daily:.1f} units/day × {target_days} days)")

            submit_col1, submit_col2 = st.columns(2)
            with submit_col1:
                save_btn = st.form_submit_button("💾 Save Manual Target")
            with submit_col2:
                clear_btn = st.form_submit_button("❌ Clear Override")

            if save_btn:
                if manual_daily > 0:
                    st.session_state["manual_demand_overrides"][selected_pid] = manual_daily
                    st.success(f"Saved manual target of {manual_daily} units/day ({calc_manual_total} total units).")
                    st.rerun()
                else:
                    st.session_state["manual_demand_overrides"].pop(selected_pid, None)
                    st.info("Cleared override.")
                    st.rerun()

            if clear_btn:
                st.session_state["manual_demand_overrides"].pop(selected_pid, None)
                st.info("Override removed.")
                st.rerun()

        if selected_row["is_manual"]:
            st.warning("⚠️ **Notice:** This SKU is currently using a **Manual Planning Estimate (User-Defined Assumption)**.")

else:
    st.info("No active products available for demand estimation.")
