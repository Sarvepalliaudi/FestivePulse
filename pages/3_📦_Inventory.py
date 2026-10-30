"""
FestivePulse — Inventory, Batch Tracking, Auditable Movement Ledger & Stock Reconciliation
"""

from datetime import date, timedelta
import streamlit as st
import pandas as pd
from database.queries import (
    get_products_with_stock, get_batches_for_product,
    get_expiring_batches, get_suppliers
)
from services.inventory_service import (
    receive_batch, record_stock_adjustment, get_inventory_valuation_metrics,
    reconcile_product_inventory, perform_physical_count_reconciliation,
    get_stock_movement_ledger
)
from repositories.inventory_repository import (
    InsufficientStockError, DuplicateBatchError,
    UnauthorizedNegativeStockError, VALID_MOVEMENT_TYPES
)
from services.currency_utils import format_inr
from services.ui_components import (
    apply_custom_css,
    render_festival_header,
    render_kpi_card,
    render_standard_sidebar
)

st.set_page_config(page_title="Inventory & Batches — FestivePulse", page_icon="📦", layout="wide")
apply_custom_css()
render_festival_header()
render_standard_sidebar()

st.title("📦 Inventory, Batches & Auditable Stock Ledger")

# Top Inventory Valuation & Health KPI Cards
val_metrics = get_inventory_valuation_metrics()
v1, v2, v3, v4, v5, v6 = st.columns(6)

with v1:
    render_kpi_card("Stock Valuation (Cost)", format_inr(val_metrics["total_cost_value"], show_decimals=False), "Capital Invested in Stock")
with v2:
    render_kpi_card("Retail Valuation (Sell)", format_inr(val_metrics["total_retail_value"], show_decimals=False), "Potential Gross Revenue")
with v3:
    render_kpi_card("Unrealized Margin", format_inr(val_metrics["potential_margin"], show_decimals=False), "Projected Gross Margin")
with v4:
    render_kpi_card("Total Units in Stock", f"{val_metrics['total_units_in_stock']:,}", "Active Units Available")
with v5:
    out_cnt = val_metrics.get("out_of_stock_count", 0)
    render_kpi_card("Out of Stock", f"{out_cnt} SKUs", "Requires Restock" if out_cnt > 0 else "All Stocked")
with v6:
    low_cnt = val_metrics.get("low_stock_count", 0)
    render_kpi_card("Low Stock Alert", f"{low_cnt} SKUs", "Below Safety Stock" if low_cnt > 0 else "Safety Levels Good")

st.markdown("<br/>", unsafe_allow_html=True)

# 5 Dedicated Feature Tabs
inv_tabs = st.tabs([
    "📦 Stock on Hand & Health",
    "📜 Auditable Movement Ledger",
    "⏰ Perishable Expiry Alerts",
    "📥 Receive Inbound Shipment",
    "⚖️ Adjustments & Reconciliation"
])

# -------------------------------------------------------------
# TAB 1: STOCK ON HAND & HEALTH VIEWS
# -------------------------------------------------------------
with inv_tabs[0]:
    st.subheader("Current Available Inventory & Stock Health")
    
    col_f1, col_f2 = st.columns([2, 1])
    with col_f1:
        status_filter = st.radio(
            "Filter by Stock Health:",
            ["All Items", "Low Stock (Below Safety)", "Out of Stock", "Adequate Stock", "Overstocked"],
            horizontal=True
        )
    with col_f2:
        search_query = st.text_input("🔍 Quick Search (Name or SKU):", placeholder="e.g. Kaju, Diya, SKU-SWT")

    prods_df = get_products_with_stock(search=search_query if search_query else None)

    if not prods_df.empty:
        # Apply health status filter
        if status_filter == "Low Stock (Below Safety)":
            df_show = prods_df[prods_df["stock_status"] == "CRITICAL"]
        elif status_filter == "Out of Stock":
            df_show = prods_df[prods_df["stock_status"] == "OUT_OF_STOCK"]
        elif status_filter == "Adequate Stock":
            df_show = prods_df[prods_df["stock_status"] == "ADEQUATE"]
        elif status_filter == "Overstocked":
            df_show = prods_df[prods_df["stock_status"] == "OVERSTOCKED"]
        else:
            df_show = prods_df

        st.caption(f"Showing **{len(df_show)}** matching products out of **{len(prods_df)}** active catalog items.")

        if not df_show.empty:
            df_table = df_show.copy()
            df_table["cost_price_fmt"] = df_table["cost_price"].apply(lambda x: format_inr(x))
            df_table["selling_price_fmt"] = df_table["selling_price"].apply(lambda x: format_inr(x))
            df_table["perishable_fmt"] = df_table["is_perishable"].apply(lambda x: "Yes ⚠️" if x else "No")
            df_table["status_badge"] = df_table["stock_status"].apply(lambda s: {
                "OUT_OF_STOCK": "❌ Out of Stock",
                "CRITICAL": "🚨 Low Stock",
                "ADEQUATE": "✅ Adequate",
                "OVERSTOCKED": "📦 Overstocked"
            }.get(s, s))

            st.dataframe(
                df_table[[
                    "sku", "product_name", "category_name", "current_stock",
                    "unit_of_measure", "min_safety_stock", "status_badge",
                    "cost_price_fmt", "selling_price_fmt", "perishable_fmt"
                ]].rename(columns={
                    "sku": "SKU",
                    "product_name": "Product Name",
                    "category_name": "Category",
                    "current_stock": "Available Stock",
                    "unit_of_measure": "UOM",
                    "min_safety_stock": "Min Safety",
                    "status_badge": "Stock Health",
                    "cost_price_fmt": "Unit Cost",
                    "selling_price_fmt": "Unit Sell",
                    "perishable_fmt": "Perishable"
                }),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info(f"No products match the filter '{status_filter}'.")

        st.divider()
        st.subheader("🔍 Inspect Batches by Product")
        p_map = {f"{r['sku']} — {r['product_name']}": r["product_id"] for _, r in prods_df.iterrows()}
        selected_prod_str = st.selectbox("Select product to view individual lots/batches:", list(p_map.keys()))
        b_pid = p_map[selected_prod_str]
        batches_df = get_batches_for_product(b_pid)

        if not batches_df.empty:
            b_display = batches_df.copy()
            b_display["unit_cost_fmt"] = b_display["unit_cost"].apply(lambda x: format_inr(x))
            b_display["days_to_expiry_fmt"] = b_display["days_to_expiry"].apply(
                lambda x: f"{x} days left" if pd.notnull(x) and x >= 0 else ("❌ EXPIRED" if pd.notnull(x) else "Non-perishable")
            )
            st.dataframe(
                b_display[[
                    "batch_number", "supplier_name", "received_date", "expiry_date",
                    "days_to_expiry_fmt", "quantity_received", "quantity_available", "unit_cost_fmt", "storage_location"
                ]].rename(columns={
                    "batch_number": "Batch No",
                    "supplier_name": "Supplier",
                    "received_date": "Received Date",
                    "expiry_date": "Expiry Date",
                    "days_to_expiry_fmt": "Shelf-Life Status",
                    "quantity_received": "Total Inward",
                    "quantity_available": "Current Available",
                    "unit_cost_fmt": "Batch Cost",
                    "storage_location": "Storage Location"
                }),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No batches found for this product.")
    else:
        st.info("No products found in the catalog.")

# -------------------------------------------------------------
# TAB 2: AUDITABLE STOCK MOVEMENT LEDGER
# -------------------------------------------------------------
with inv_tabs[1]:
    st.subheader("📜 Auditable Stock Movement Ledger")
    st.markdown(
        "Every stock change is transactionally recorded with a timestamp, signed quantity, "
        "movement category, cost impact, and transaction reference. **Silent balance edits are strictly prohibited.**"
    )

    all_prods = get_products_with_stock()
    
    # Ledger Filter Controls
    lf_c1, lf_c2, lf_c3, lf_c4 = st.columns(4)
    with lf_c1:
        prod_filter_opts = {"all": "All Products"}
        if not all_prods.empty:
            for _, r in all_prods.iterrows():
                prod_filter_opts[r["product_id"]] = f"{r['sku']} — {r['product_name']}"
        selected_l_prod = st.selectbox("Product Filter:", options=list(prod_filter_opts.keys()), format_func=lambda x: prod_filter_opts[x])

    with lf_c2:
        m_types_opts = ["ALL"] + sorted(list(VALID_MOVEMENT_TYPES))
        selected_m_type = st.selectbox("Movement Type:", m_types_opts)

    with lf_c3:
        d_from = st.date_input("From Date:", value=date.today() - timedelta(days=30))
    with lf_c4:
        d_to = st.date_input("To Date:", value=date.today() + timedelta(days=1))

    # Fetch ledger data
    p_filter_arg = None if selected_l_prod == "all" else int(selected_l_prod)
    t_filter_arg = None if selected_m_type == "ALL" else selected_m_type
    f_date_str = d_from.strftime("%Y-%m-%d") if d_from else None
    t_date_str = d_to.strftime("%Y-%m-%d") if d_to else None

    ledger_df = get_stock_movement_ledger(
        product_id=p_filter_arg,
        movement_type=t_filter_arg,
        start_date=f_date_str,
        end_date=t_date_str,
        limit=250
    )

    if not ledger_df.empty:
        # Summary Metrics
        tot_movements = len(ledger_df)
        inflow = ledger_df[ledger_df["quantity"] > 0]["quantity"].sum()
        outflow = ledger_df[ledger_df["quantity"] < 0]["quantity"].sum()
        net_flow = inflow + outflow

        sm_c1, sm_c2, sm_c3, sm_c4 = st.columns(4)
        sm_c1.metric("Ledger Records", f"{tot_movements}")
        sm_c2.metric("Total Inward (+)", f"+{inflow:,} units")
        sm_c3.metric("Total Outward (-)", f"{outflow:,} units")
        sm_c4.metric("Net Stock Delta", f"{net_flow:+,} units")

        # Table Display
        display_df = ledger_df.copy()
        display_df["cost_impact_fmt"] = display_df["total_cost_impact"].apply(lambda x: format_inr(x))
        display_df["qty_fmt"] = display_df["quantity"].apply(lambda q: f"+{q}" if q > 0 else f"{q}")
        display_df["unit_cost_fmt"] = display_df["unit_cost"].apply(lambda x: format_inr(x))

        st.dataframe(
            display_df[[
                "created_at", "sku", "product_name", "batch_number",
                "movement_type", "qty_fmt", "unit_cost_fmt", "cost_impact_fmt",
                "reference_type", "reference_id", "reason"
            ]].rename(columns={
                "created_at": "Timestamp",
                "sku": "SKU",
                "product_name": "Product Name",
                "batch_number": "Batch No",
                "movement_type": "Movement Type",
                "qty_fmt": "Quantity",
                "unit_cost_fmt": "Unit Cost",
                "cost_impact_fmt": "Cost Impact (₹)",
                "reference_type": "Ref Type",
                "reference_id": "Ref Transaction",
                "reason": "Audit Reason"
            }),
            use_container_width=True,
            hide_index=True
        )

        # CSV Export
        csv_data = ledger_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            "📥 Export Stock Movement Ledger (CSV)",
            data=csv_data,
            file_name=f"festivepulse_stock_ledger_{date.today().strftime('%Y%m%d')}.csv",
            mime="text/csv"
        )
    else:
        st.info("No stock movements match the specified filter criteria.")

# -------------------------------------------------------------
# TAB 3: PERISHABLE EXPIRY ALERTS
# -------------------------------------------------------------
with inv_tabs[2]:
    st.subheader("⏰ Perishable Shelf-Life Watchlist")
    st.markdown("Identifies batches approaching expiration so you can prioritize sales, assemble gift hampers, or apply clearance discounts.")

    alert_days = st.slider("Lookahead Window (Days):", min_value=5, max_value=60, value=15, step=5)
    expiring_df = get_expiring_batches(within_days=alert_days)

    if not expiring_df.empty:
        st.error(f"⚠️ **{len(expiring_df)} Batch(es)** expiring within the next {alert_days} days!")
        exp_table = expiring_df.copy()
        exp_table["unit_cost_fmt"] = exp_table["unit_cost"].apply(lambda x: format_inr(x))
        exp_table["urgency_fmt"] = exp_table["days_to_expiry"].apply(
            lambda x: f"🚨 {x} Days Left" if x >= 0 else "❌ EXPIRED"
        )
        st.dataframe(
            exp_table[[
                "product_name", "sku", "batch_number", "quantity_available",
                "expiry_date", "urgency_fmt", "unit_cost_fmt", "storage_location"
            ]].rename(columns={
                "product_name": "Product",
                "sku": "SKU",
                "batch_number": "Batch No",
                "quantity_available": "Units at Risk",
                "expiry_date": "Expiry Date",
                "urgency_fmt": "Urgency",
                "unit_cost_fmt": "Unit Cost",
                "storage_location": "Storage Area"
            }),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.success(f"✅ Great news! No inventory batches expiring within the next {alert_days} days.")

# -------------------------------------------------------------
# TAB 4: RECEIVE INBOUND SHIPMENT
# -------------------------------------------------------------
with inv_tabs[3]:
    st.subheader("📥 Receive Inbound Shipment / Purchase Order")
    st.markdown("Record stock received from suppliers. Batch numbers must be unique per product to prevent duplicate receipts.")

    all_prods = get_products_with_stock()
    sups_df = get_suppliers()

    if not all_prods.empty:
        prod_opts = {f"{r['sku']} — {r['product_name']}": r["product_id"] for _, r in all_prods.iterrows()}
        sup_opts = {r["supplier_name"]: r["supplier_id"] for _, r in sups_df.iterrows()} if not sups_df.empty else {}

        with st.form("form_receive_batch", clear_on_submit=False):
            r_col1, r_col2 = st.columns(2)
            with r_col1:
                sel_p = st.selectbox("Select Product to Stock *", list(prod_opts.keys()))
                p_id = prod_opts[sel_p]
                
                # Default batch number suggestion
                sku_code = sel_p.split(" — ")[0].strip()
                suggested_batch = f"BATCH-{sku_code}-{date.today().strftime('%Y%m%d')}"
                batch_num = st.text_input("Batch / Lot Number *", value=suggested_batch)
                qty = st.number_input("Quantity Received *", min_value=1, value=50, step=5)
                
                # Fetch default cost price for convenience
                cur_cost = float(all_prods[all_prods["product_id"] == p_id].iloc[0]["cost_price"])
                cost = st.number_input("Unit Inward Cost (₹) *", min_value=0.0, step=10.0, value=cur_cost)

            with r_col2:
                sel_sup = st.selectbox("Supplier", options=["-- None / Local Vendor --"] + list(sup_opts.keys()))
                sup_id = sup_opts[sel_sup] if sel_sup != "-- None / Local Vendor --" else None
                
                is_p = bool(all_prods[all_prods["product_id"] == p_id].iloc[0]["is_perishable"])
                st.caption(f"Perishable SKU: **{'Yes ⚠️' if is_p else 'No'}**")
                
                exp_date = st.date_input("Expiry Date (Mandatory for perishables)", value=None)
                location = st.text_input("Storage Location", placeholder="e.g. Aisle B3, Cold Room 1")
                receipt_reason = st.text_input("Receipt Note / PO Reference", value=f"Inbound delivery for {sku_code}")

            submit_recv = st.form_submit_button("Record Inbound Stock Receipt", type="primary")

            if submit_recv:
                if not batch_num or not batch_num.strip():
                    st.error("Batch number is required.")
                elif is_p and not exp_date:
                    st.error("Expiry date is strictly required for perishable products.")
                elif qty <= 0:
                    st.error("Received quantity must be greater than zero.")
                else:
                    try:
                        exp_str = exp_date.strftime("%Y-%m-%d") if exp_date else None
                        receive_batch(
                            product_id=p_id,
                            batch_number=batch_num,
                            quantity=qty,
                            unit_cost=cost,
                            supplier_id=sup_id,
                            expiry_date=exp_str,
                            storage_location=location,
                            reason=receipt_reason
                        )
                        st.success(f"✅ Successfully stocked {qty} units into batch '{batch_num.strip().upper()}' and logged in movement ledger!")
                        st.rerun()
                    except DuplicateBatchError as dbe:
                        st.error(f"❌ Duplicate Submission: {str(dbe)}")
                    except Exception as e:
                        st.error(f"❌ Failed to record receipt: {str(e)}")

# -------------------------------------------------------------
# TAB 5: ADJUSTMENTS & RECONCILIATION
# -------------------------------------------------------------
with inv_tabs[4]:
    adj_subtabs = st.tabs(["💥 Record Stock Adjustment / Spoilage", "🔍 Stocktake Reconciliation & Audit"])

    # SUB-TAB A: Manual Adjustments
    with adj_subtabs[0]:
        st.subheader("💥 Record Inventory Damage, Spoilage or Samples")
        st.markdown(
            "Record damaged diyas, expired sweets, festival gift samples, or physical shrinkage. "
            "Stock cannot become negative unless explicitly authorized under managerial override."
        )

        all_prods = get_products_with_stock()
        if not all_prods.empty:
            prod_map = {f"{r['sku']} — {r['product_name']} (Stock: {r['current_stock']})": r["product_id"] for _, r in all_prods.iterrows()}

            with st.form("form_adjustment", clear_on_submit=False):
                adj_p_label = st.selectbox("Select Product *", list(prod_map.keys()))
                adj_pid = prod_map[adj_p_label]

                # Batches for this product
                b_list = get_batches_for_product(adj_pid)
                b_options = {"all": "-- Generic / FIFO Across Available Batches --"}
                if not b_list.empty:
                    for _, b in b_list.iterrows():
                        b_options[b["batch_id"]] = f"Batch {b['batch_number']} (Avail: {b['quantity_available']})"

                col_adj1, col_adj2 = st.columns(2)
                with col_adj1:
                    adj_type = st.selectbox("Adjustment Type *", [
                        "DAMAGE", "EXPIRED", "THEFT_SHRINKAGE", "PROMOTIONAL_SAMPLE", "MANUAL_COUNT_RECONCILIATION"
                    ])
                    adj_batch = st.selectbox("Specific Batch (Optional)", options=list(b_options.keys()), format_func=lambda x: b_options[x])
                    allow_neg = st.checkbox("Emergency Override: Allow Negative Stock (requires Manager PIN)")

                with col_adj2:
                    adj_qty = st.number_input("Quantity Adjustment (Negative to deduct, Positive to add) *", value=-5, step=1)
                    reason = st.text_input("Audit Reason / Note *", placeholder="e.g. Diya broken in transit, Sweets expired")
                    manager_auth = st.text_input("Manager Authorization (Name / Staff ID)", placeholder="Required if emergency override is enabled")

                submit_adj = st.form_submit_button("Record Stock Adjustment", type="primary")

                if submit_adj:
                    if not reason or not reason.strip():
                        st.error("Please provide a mandatory audit reason for the adjustment.")
                    elif adj_qty == 0:
                        st.error("Adjustment quantity cannot be zero.")
                    elif allow_neg and not manager_auth:
                        st.error("Manager authorization name/PIN is required when enabling emergency negative stock override.")
                    else:
                        try:
                            batch_arg = None if adj_batch == "all" else int(adj_batch)
                            record_stock_adjustment(
                                product_id=adj_pid,
                                adjustment_type=adj_type,
                                quantity=adj_qty,
                                reason=reason,
                                batch_id=batch_arg,
                                allow_negative=allow_neg,
                                authorized_by=manager_auth if allow_neg else None
                            )
                            st.success(f"✅ Stock adjustment of {adj_qty} recorded successfully in ledger and inventory balances!")
                            st.rerun()
                        except InsufficientStockError as ise:
                            st.error(f"❌ Stock Deduction Blocked: {str(ise)}")
                        except UnauthorizedNegativeStockError as unse:
                            st.error(f"❌ Authorization Error: {str(unse)}")
                        except Exception as e:
                            st.error(f"❌ Adjustment failed: {str(e)}")

    # SUB-TAB B: Deterministic Reconciliation
    with adj_subtabs[1]:
        st.subheader("🔍 Stocktake Reconciliation & Audit Tool")
        st.markdown(
            "FestivePulse employs a **dual-verified authoritative inventory architecture**. "
            "Batch balances are maintained for real-time POS billing, while an immutable stock movement ledger "
            "tracks every single stock addition and deduction. The reconciliation engine verifies that both layers match exactly."
        )

        all_prods = get_products_with_stock()
        if not all_prods.empty:
            p_recon_map = {f"{r['sku']} — {r['product_name']}": r["product_id"] for _, r in all_prods.iterrows()}
            selected_recon_p = st.selectbox("Select Product to Audit & Reconcile:", list(p_recon_map.keys()))
            recon_pid = p_recon_map[selected_recon_p]

            recon_status = reconcile_product_inventory(recon_pid)

            rc1, rc2, rc3, rc4 = st.columns(4)
            rc1.metric("Batch Balance Stock", f"{recon_status['batch_stock']} units")
            rc2.metric("Ledger Movement Sum", f"{recon_status['ledger_stock']} units")
            
            discrepancy = recon_status["discrepancy"]
            if discrepancy == 0:
                rc3.metric("Discrepancy", "0 units", delta="100% In Sync")
                rc4.success("✅ **Reconciled & In Sync**")
            else:
                rc3.metric("Discrepancy", f"{discrepancy:+} units", delta_color="inverse")
                rc4.error("⚠️ **Discrepancy Detected!**")

            st.markdown("<br/>", unsafe_allow_html=True)
            st.subheader("📝 Authorize Physical Count Reconciliation")
            st.caption("Perform a physical shelf count. If the physical count differs from the system, an authorized reconciliation entry will be recorded.")

            with st.form("form_recon_apply"):
                c_rc1, c_rc2 = st.columns(2)
                with c_rc1:
                    phys_count = st.number_input(
                        "Observed Physical Count on Shelf *",
                        min_value=0,
                        value=recon_status["batch_stock"],
                        step=1
                    )
                    recon_mgr = st.text_input("Audited & Authorized By (Manager Name / ID) *", placeholder="e.g. Ramesh Kumar (Store Mgr)")
                with c_rc2:
                    recon_reason = st.text_input("Reconciliation Audit Reason *", placeholder="e.g. Weekly physical stock audit before Diwali rush")
                    variance = phys_count - recon_status["batch_stock"]
                    st.info(f"Calculated Stock Adjustment Variance: **{variance:+} units**")

                submit_reconcile = st.form_submit_button("Apply Reconciliation Adjustment", type="primary")

                if submit_reconcile:
                    if not recon_mgr or not recon_mgr.strip():
                        st.error("Manager authorization name/ID is strictly required.")
                    elif not recon_reason or not recon_reason.strip():
                        st.error("Reconciliation audit reason is mandatory.")
                    else:
                        try:
                            res = perform_physical_count_reconciliation(
                                product_id=recon_pid,
                                physical_count=phys_count,
                                reason=recon_reason,
                                authorized_by=recon_mgr
                            )
                            st.success(f"✅ Product stock successfully reconciled! New balance: {res['batch_stock']} units (Ledger: {res['ledger_stock']} units).")
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Reconciliation failed: {str(e)}")
