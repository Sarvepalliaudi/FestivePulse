"""
FestivePulse — Deterministic Festival Stock Planning & Procurement Advisor
Formula-based replenishment: max(0, planned demand + safety stock - usable stock)
Budget constraint analysis, top-contributor excess explanations, and manual override tracking.
100% Non-AI. Zero automated purchase orders.
"""

import streamlit as st
import pandas as pd
import plotly.express as px
from database.queries import get_all_festival_occurrences, get_categories, get_products
from services.stock_planning_service import generate_festival_stock_plan_table
from services.pdf_generator import generate_procurement_po_pdf
from services.currency_utils import format_inr
from services.ui_components import (
    apply_custom_css,
    render_festival_header,
    get_festive_plotly_layout,
    render_standard_sidebar
)

st.set_page_config(page_title="Festival Stock Planning — FestivePulse", page_icon="🛒", layout="wide")
apply_custom_css()
render_festival_header()
render_standard_sidebar()

st.title("🛒 Deterministic Festival Stock Planning")
st.markdown(
    "**Formula-Based Procurement Planning:** Evaluates planned festival demand, existing unexpired usable stock, "
    "and configured safety stock buffers using classical deterministic equations. "
    "Features budget limit verification, top-contributor excess analysis, and auditable manual overrides. "
    "**100% Non-AI. Zero automated order placements.**"
)

# Initialize session state for manual overrides
if "stock_purchase_overrides" not in st.session_state:
    st.session_state["stock_purchase_overrides"] = {}
if "stock_safety_overrides" not in st.session_state:
    st.session_state["stock_safety_overrides"] = {}

# 1. Festival & Planning Period Selection
occ_df = get_all_festival_occurrences()
if occ_df.empty:
    st.warning("⚠️ No festival campaigns configured in database. Configure festivals in Festival Management first.")
    st.stop()

occ_options = {}
for _, r in occ_df.iterrows():
    s_dt = str(r["campaign_start_date"])
    e_dt = str(r["campaign_end_date"])
    occ_options[r["occurrence_id"]] = f"{r['festival_name']} {r['year']} ({s_dt} to {e_dt})"

default_occ = next((r["occurrence_id"] for _, r in occ_df.iterrows() if r["is_current_active"]), list(occ_options.keys())[0])

# Top Control Panel
st.subheader("⚙️ Campaign & Budget Parameters")
col_cfg1, col_cfg2, col_cfg3 = st.columns([1.5, 1.2, 1.3])

with col_cfg1:
    target_occ = st.selectbox(
        "Target Festival & Planning Window:",
        options=list(occ_options.keys()),
        format_func=lambda x: occ_options[x],
        index=list(occ_options.keys()).index(default_occ)
    )
    # Display selected occurrence details
    selected_occ_meta = occ_df[occ_df["occurrence_id"] == target_occ].iloc[0]
    st.caption(
        f"📅 Campaign: **{selected_occ_meta['campaign_start_date']}** to **{selected_occ_meta['campaign_end_date']}** | "
        f"Peak: **{selected_occ_meta['peak_start_date']}** | Festival Day: **{selected_occ_meta['festival_date']}**"
    )

with col_cfg2:
    purchasing_budget = st.number_input(
        "Available Purchasing Budget (₹):",
        min_value=0.0,
        max_value=10000000.0,
        value=150000.0,
        step=5000.0,
        help="Total capital allocated for festival procurement. The planner warns when suggested purchases exceed this limit."
    )
    st.caption(f"Budget Limit: **{format_inr(purchasing_budget)}**")

with col_cfg3:
    growth_factor = st.slider(
        "Planned Business Growth Multiplier:",
        min_value=0.5,
        max_value=2.5,
        value=1.10,
        step=0.05,
        format="%.2fx",
        help="Volume growth factor applied to historical festival demand."
    )
    st.caption(f"Planned volume adjustment: {(growth_factor - 1.0) * 100:+.0f}% YoY.")

# Product Filters
col_fil1, col_fil2, col_fil3 = st.columns([1.2, 1.5, 1.3])

with col_fil1:
    cats = get_categories()
    cat_opts = {0: "All Categories"}
    for _, c in cats.iterrows():
        cat_opts[c["category_id"]] = c["category_name"]
    filter_cat = st.selectbox("Product Category:", options=list(cat_opts.keys()), format_func=lambda x: cat_opts[x])
    cat_arg = None if filter_cat == 0 else filter_cat

# Fetch active products matching category
all_prods_df = get_products(category_id=cat_arg)
active_prods = all_prods_df[all_prods_df["is_active"] == 1] if not all_prods_df.empty else pd.DataFrame()

with col_fil2:
    if not active_prods.empty:
        prod_dict = {row["product_id"]: f"{row['sku']} - {row['product_name']}" for _, row in active_prods.iterrows()}
        selected_pids = st.multiselect(
            "Filter Specific Products (leave blank for all):",
            options=list(prod_dict.keys()),
            format_func=lambda x: prod_dict[x],
            default=[]
        )
        pids_filter = selected_pids if selected_pids else None
    else:
        pids_filter = None

with col_fil3:
    st.write("")
    st.write("")
    only_orders = st.checkbox("Show Only Items Requiring Purchase (Qty > 0)", value=False)
    if st.button("🔄 Reset All Manual Overrides"):
        st.session_state["stock_purchase_overrides"] = {}
        st.session_state["stock_safety_overrides"] = {}
        st.rerun()

# Generate Stock Plan & Budget Analysis
plan_df, budget_analysis = generate_festival_stock_plan_table(
    occurrence_id=target_occ,
    purchasing_budget=purchasing_budget,
    selected_product_ids=pids_filter,
    category_id=cat_arg,
    growth_multiplier=growth_factor,
    safety_stock_overrides=st.session_state["stock_safety_overrides"],
    manual_purchase_overrides=st.session_state["stock_purchase_overrides"]
)

# Apply filter for table display if checkbox checked
display_plan_df = plan_df[plan_df["recommended_order_quantity"] > 0] if (only_orders and not plan_df.empty) else plan_df

# Advisory & Guardrail Callout
st.info(
    "🔒 **Advisory Notice & Deterministic Formulas:**\n"
    "- **Core Equation:** $\\text{Suggested Purchase Quantity} = \\max(0, \\text{Planned Demand} + \\text{Safety Stock} - \\text{Usable Stock})$.\n"
    "- **Zero Automated Ordering:** FestivePulse never automatically places orders or charges vendor accounts. "
    "All figures are procurement recommendations for managerial review and manual purchase order issuance.\n"
    "- **AI Disclaimer:** Estimates are derived from deterministic arithmetic and operations research formulas, not AI models."
)

if not plan_df.empty:
    total_planned_cost = budget_analysis["total_planned_cost"]
    total_orig_cost = budget_analysis["total_original_cost"]
    is_exceeded = budget_analysis["is_budget_exceeded"]
    overrun = budget_analysis["overrun_amount"]
    util_pct = budget_analysis["budget_utilization_pct"]

    total_planned_units = int(plan_df["edited_purchase_quantity"].sum())
    total_orig_units = int(plan_df["original_suggested_quantity"].sum())
    items_to_order_count = int((plan_df["edited_purchase_quantity"] > 0).sum())
    perish_risks = plan_df[plan_df["is_spoilage_risk"] == True]

    # Summary KPI Cards
    st.markdown("### 📊 Procurement Budget & Volume Overview")
    k1, k2, k3, k4 = st.columns(4)

    with k1:
        st.metric(
            "Available Budget",
            format_inr(purchasing_budget),
            help="Total capital allocated for this festival purchasing plan."
        )
        st.caption(f"{len(plan_df)} SKUs in plan scope")

    with k2:
        cost_delta = round(total_planned_cost - total_orig_cost, 2)
        delta_str = f"{cost_delta:+.2f} vs calc" if cost_delta != 0 else "Matches formula"
        st.metric(
            "Total Planned Purchase Cost",
            format_inr(total_planned_cost),
            delta=delta_str,
            delta_color="inverse" if cost_delta > 0 else "normal",
            help="Sum of (planned purchase quantity * recorded unit cost)."
        )
        st.caption(f"Original formula cost: {format_inr(total_orig_cost)}")

    with k3:
        if is_exceeded:
            st.metric(
                "Budget Overrun",
                format_inr(overrun),
                delta=f"{util_pct:.1f}% Utilized",
                delta_color="inverse",
                help="Amount by which planned procurement exceeds available capital."
            )
            st.caption("🚨 Budget limit breached")
        else:
            surplus = purchasing_budget - total_planned_cost
            st.metric(
                "Remaining Budget Surplus",
                format_inr(surplus),
                delta=f"{util_pct:.1f}% Utilized",
                delta_color="normal",
                help="Unallocated capital available."
            )
            st.caption("✅ Plan within budget")

    with k4:
        st.metric(
            "Planned Purchase Volume",
            f"{total_planned_units:,} units",
            delta=f"{items_to_order_count} SKUs requiring order",
            help="Total units to procure across all active products."
        )
        st.caption(f"Original formula volume: {total_orig_units:,} units")

    st.divider()

    # Budget Warning & Top Contributors Explanation
    if is_exceeded:
        st.error(f"🚨 **BUDGET LIMIT EXCEEDED: Procurement plan exceeds budget by {format_inr(overrun)} ({util_pct:.1f}% utilization).**")
        st.markdown(budget_analysis["explanation_narrative"])

        # Visual breakdown of top contributors
        st.markdown("##### 🔍 Top Drivers of Procurement Spend")
        top_contrib_df = pd.DataFrame(budget_analysis["top_contributors"][:5])
        if not top_contrib_df.empty:
            fig_top = px.bar(
                top_contrib_df,
                x="planned_cost",
                y="product_name",
                orientation="h",
                text="cost_share_pct",
                labels={"planned_cost": "Planned Spend (₹)", "product_name": "Product", "cost_share_pct": "Spend Share (%)"},
                title="Top Products by Procurement Spend Contribution",
                color="cost_share_pct",
                color_continuous_scale="Reds"
            )
            fig_top.update_layout(get_festive_plotly_layout(), yaxis={'categoryorder': 'total ascending'})
            fig_top.update_traces(texttemplate='%{text:.1f}% of spend', textposition='outside')
            st.plotly_chart(fig_top, use_container_width=True)
    else:
        st.success(budget_analysis["explanation_narrative"])

    # Perishable Spoilage Risks Warning
    if not perish_risks.empty:
        st.warning(f"⚠️ **Perishable Spoilage Notice:** {len(perish_risks)} product(s) have shelf life shorter than the festival campaign. A single bulk order risks inventory spoilage.")
        for _, p_risk in perish_risks.iterrows():
            with st.expander(f"📦 Staggered Delivery Recommendation: {p_risk['product_name']} (Shelf Life: {p_risk['shelf_life_days']} days)"):
                st.write(p_risk["spoilage_warning"])
                sched = p_risk.get("staggered_schedule", [])
                if sched:
                    st.dataframe(pd.DataFrame(sched), use_container_width=True, hide_index=True)

    # Auditable Stock Planning Worksheet
    st.subheader("📋 Auditable Festival Stock Planning Worksheet")
    st.caption("Displays both the original deterministic formula calculation and any user manual overrides side-by-side.")

    disp_table = display_plan_df.copy()
    disp_table["formatted_unit_cost"] = disp_table["unit_cost"].apply(format_inr)
    disp_table["formatted_orig_cost"] = disp_table["original_procurement_cost"].apply(format_inr)
    disp_table["formatted_planned_cost"] = disp_table["planned_procurement_cost"].apply(format_inr)

    view_columns = [
        "status_badge",
        "sku",
        "product_name",
        "category_name",
        "usable_stock",
        "planned_demand",
        "safety_stock",
        "original_suggested_quantity",
        "edited_purchase_quantity",
        "override_delta",
        "formatted_unit_cost",
        "formatted_orig_cost",
        "formatted_planned_cost",
        "arithmetic_breakdown"
    ]

    rename_map = {
        "status_badge": "Procurement Status",
        "sku": "SKU",
        "product_name": "Product Name",
        "category_name": "Category",
        "usable_stock": "Usable Stock",
        "planned_demand": "Planned Demand",
        "safety_stock": "Safety Buffer",
        "original_suggested_quantity": "Original Calc Qty",
        "edited_purchase_quantity": "Planned / Edited Qty",
        "override_delta": "Override Delta",
        "formatted_unit_cost": "Unit Cost (₹)",
        "formatted_orig_cost": "Original Cost (₹)",
        "formatted_planned_cost": "Planned Cost (₹)",
        "arithmetic_breakdown": "Calculation Formula Breakdown"
    }

    st.dataframe(disp_table[view_columns].rename(columns=rename_map), use_container_width=True, hide_index=True)

    # Export CSV & PDF Actions
    st.markdown("##### 📥 Export Procurement Plan")
    col_exp1, col_exp2 = st.columns(2)
    with col_exp1:
        csv_bytes = plan_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Download Procurement Worksheet (CSV)",
            data=csv_bytes,
            file_name=f"FestivePulse_Procurement_Plan_Occ_{target_occ}.csv",
            mime="text/csv",
            use_container_width=True,
            help="Exports auditable table with both original formula values and edited overrides."
        )

    with col_exp2:
        if st.button("📄 Generate Purchase Requisition PDF", type="primary", use_container_width=True):
            po_pdf_path = generate_procurement_po_pdf(target_occ)
            with open(po_pdf_path, "rb") as f:
                st.download_button(
                    label="📥 Download Purchase Order PDF",
                    data=f.read(),
                    file_name=f"Purchase_Order_Festival_{target_occ}.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )

    st.divider()

    # Manual Override & SKU Deep Dive Studio
    st.subheader("✏️ Manual Override & SKU Deep-Dive Studio")
    st.markdown("Inspect the arithmetic for any product, adjust safety stock, or manually override the purchase quantity.")

    sku_options = {row["product_id"]: f"{row['sku']} — {row['product_name']} ({row['procurement_status']})" for _, row in plan_df.iterrows()}
    selected_pid = st.selectbox(
        "Select Product to Inspect or Override:",
        options=list(sku_options.keys()),
        format_func=lambda x: sku_options[x]
    )

    selected_row = plan_df[plan_df["product_id"] == selected_pid].iloc[0]

    col_studio1, col_studio2 = st.columns([1.2, 1.0])

    with col_studio1:
        st.markdown(f"#### Audit Trail: **{selected_row['product_name']}** (`{selected_row['sku']}`)")
        st.markdown(f"**Category:** {selected_row['category_name']} | **Supplier:** {selected_row['supplier_name']} (Lead Time: {selected_row['lead_time_days']} days)")
        st.markdown(f"**Unit Cost:** {format_inr(selected_row['unit_cost'])} | **Pack Size:** {selected_row['pack_size']} units")
        
        st.markdown("##### 📐 Deterministic Inventory Math")
        st.code(
            "Suggested purchase quantity = max(0, planned demand + safety stock - usable stock)\n"
            f"Arithmetic: {selected_row['arithmetic_breakdown']}",
            language="markdown"
        )

        st.markdown("##### 📊 Comparison: Original Formula vs Edited")
        comp_m1, comp_m2, comp_m3 = st.columns(3)
        with comp_m1:
            st.metric("Original Calc Qty", f"{selected_row['original_suggested_quantity']} units")
            st.caption(f"Cost: {format_inr(selected_row['original_procurement_cost'])}")
        with comp_m2:
            st.metric("Planned / Edited Qty", f"{selected_row['edited_purchase_quantity']} units")
            st.caption(f"Cost: {format_inr(selected_row['planned_procurement_cost'])}")
        with comp_m3:
            delta = selected_row["override_delta"]
            st.metric("Override Delta", f"{delta:+d} units")
            st.caption("User override" if selected_row["is_overridden"] else "Formula default")

    with col_studio2:
        st.markdown("#### 🛠️ Adjust Safety Stock or Override Purchase Qty")
        current_ss = st.session_state["stock_safety_overrides"].get(selected_pid, int(selected_row["safety_stock"]))
        current_override_qty = st.session_state["stock_purchase_overrides"].get(selected_pid, int(selected_row["edited_purchase_quantity"]))

        with st.form(key=f"override_form_{selected_pid}"):
            new_safety_stock = st.number_input(
                "Configured Safety Stock (units):",
                min_value=0,
                max_value=10000,
                value=int(current_ss),
                step=5,
                help="Explicitly configured safety stock buffer. Overrides the default product safety stock."
            )

            new_purchase_qty = st.number_input(
                "Manual Purchase Quantity Override (units):",
                min_value=0,
                max_value=50000,
                value=int(current_override_qty),
                step=int(selected_row["pack_size"]) if selected_row["pack_size"] > 1 else 1,
                help="Explicitly override the suggested purchase quantity. Set equal to original calculation to remove override."
            )

            calc_new_cost = round(new_purchase_qty * selected_row["unit_cost"], 2)
            st.caption(f"Projected Procurement Spend: **{format_inr(calc_new_cost)}**")

            btn_col1, btn_col2 = st.columns(2)
            with btn_col1:
                save_override_btn = st.form_submit_button("💾 Save Changes")
            with btn_col2:
                reset_override_btn = st.form_submit_button("🔄 Reset to Formula")

            if save_override_btn:
                st.session_state["stock_safety_overrides"][selected_pid] = new_safety_stock
                if new_purchase_qty != selected_row["original_suggested_quantity"]:
                    st.session_state["stock_purchase_overrides"][selected_pid] = new_purchase_qty
                else:
                    st.session_state["stock_purchase_overrides"].pop(selected_pid, None)
                st.success(f"Updated settings for {selected_row['product_name']}.")
                st.rerun()

            if reset_override_btn:
                st.session_state["stock_safety_overrides"].pop(selected_pid, None)
                st.session_state["stock_purchase_overrides"].pop(selected_pid, None)
                st.info(f"Reset {selected_row['product_name']} to original formula values.")
                st.rerun()

else:
    st.info("No active products selected for stock planning.")
