"""
FestivePulse — Festival Expenses, Costing & Net Operating Profit (P&L)
Exact accounting of gross revenue, discounts, returns, immutable snapshot COGS,
operating expenses (rent, transport, packaging, wages, marketing, other),
and net operating profit with auditable corrections and labeled exclusions.
"""

import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import date
from database.queries import get_all_festival_occurrences, query_df
from services.currency_utils import format_inr
from services.expense_service import (
    record_expense,
    edit_expense,
    cancel_expense,
    get_expense_audit_trail,
    get_financial_pnl_statement,
    STANDARD_CATEGORIES,
    normalize_category
)
from services.ui_components import (
    apply_custom_css,
    render_festival_header,
    render_kpi_card,
    get_festive_plotly_layout,
    render_standard_sidebar,
    clean_html
)

st.set_page_config(page_title="Expenses & Profit (P&L) — FestivePulse", page_icon="💰", layout="wide")
apply_custom_css()
render_festival_header()
render_standard_sidebar()

st.title("💰 Expense Management & Profit/Loss (P&L)")
st.markdown(
    "**Deterministic Accounting & Auditable P&L:** Integrates actual recorded transaction prices, "
    "immutable product cost snapshots, sales returns, and operating expenses (Rent, Transport, Packaging, Wages, Marketing, Other). "
    "Calculates net operating profit strictly from relevant included expenses, with explicit labeled exclusions. "
    "**100% Non-AI. Zero estimated guesswork.**"
)

# Standard Operating Expense Categories
CAT_CHOICES = [
    ("RENT", "Rent (Store, Stall, Warehouse)"),
    ("TRANSPORT", "Transport & Freight (Logistics, Delivery)"),
    ("PACKAGING", "Packaging (Boxes, Pouches, Bags, Foils)"),
    ("WAGES", "Wages & Bonuses (Staff Overtime, Temporary Labor)"),
    ("MARKETING", "Marketing & Promotion (Ads, Banners, Social Campaigns)"),
    ("OTHER", "Other Costs (Utilities, Incidental Overheads)")
]

# 1. Festival & Scope Selection
occ_df = get_all_festival_occurrences()

col_filt1, col_filt2, col_filt3 = st.columns([1.5, 1.2, 1.3])

with col_filt1:
    scope_options = {"ALL": "🌐 Entire Store (All Periods & General Overheads)"}
    if not occ_df.empty:
        for _, r in occ_df.iterrows():
            scope_options[r["occurrence_id"]] = f"🎉 {r['festival_name']} {r['year']} ({r['campaign_start_date']} to {r['campaign_end_date']})"

    selected_scope = st.selectbox(
        "Financial Scope & Campaign Filter:",
        options=list(scope_options.keys()),
        format_func=lambda x: scope_options[x]
    )

occ_id_filter = None if selected_scope == "ALL" else int(selected_scope)

with col_filt2:
    exp_cats = [("ALL", "All Categories")] + CAT_CHOICES
    selected_cat_filter = st.selectbox("Expense Category Filter:", options=[c[0] for c in exp_cats], format_func=lambda x: dict(exp_cats)[x])
    cat_arg = None if selected_cat_filter == "ALL" else selected_cat_filter

with col_filt3:
    include_general = st.checkbox(
        "Include General Non-Festival Overheads",
        value=(selected_scope == "ALL"),
        help="When enabled, general store rent and utilities not tagged to a specific festival are included."
    )

# Compute Financial P&L Statement
pnl = get_financial_pnl_statement(
    occurrence_id=occ_id_filter,
    category_filter=cat_arg,
    include_general_overheads=include_general
)

# Top Financial KPIs
st.markdown("### 📊 Financial Performance Overview")
p1, p2, p3, p4 = st.columns(4)

with p1:
    render_kpi_card(
        "Net Sales Revenue",
        format_inr(pnl["net_sales_revenue"], show_decimals=False),
        f"Gross: {format_inr(pnl['gross_billed'], show_decimals=False)} (Discounts: -{format_inr(pnl['total_discounts'], show_decimals=False)})"
    )

with p2:
    render_kpi_card(
        "Cost of Goods (COGS)",
        format_inr(pnl["net_cogs"], show_decimals=False),
        f"Historical Snapshot Cost ({pnl['total_units_sold']} Units Net)"
    )

with p3:
    render_kpi_card(
        "Included Expenses",
        format_inr(pnl["total_included_expenses"], show_decimals=False),
        f"{len(pnl['included_expenses'])} items included" + (f" ({len(pnl['labeled_exclusions'])} excluded)" if pnl['has_exclusions'] else "")
    )

with p4:
    net_prof = pnl["net_operating_profit"]
    render_kpi_card(
        "Net Operating Profit",
        format_inr(net_prof, show_decimals=False),
        f"Margin: {pnl['net_margin_pct']:.1f}% | ROI: {pnl['festival_roi_pct']:.1f}%",
        is_good=net_prof >= 0
    )

st.markdown("<br/>", unsafe_allow_html=True)

ep_tabs = st.tabs([
    "📑 Profit & Loss Statement",
    "➕ Record Expense",
    "📋 Expense Audit Ledger",
    "✏️ Edit & Correction Studio",
    "📖 Documented Formulas"
])

# -------------------------------------------------------------
# TAB 1: P&L Statement
# -------------------------------------------------------------
with ep_tabs[0]:
    col_pnl1, col_pnl2 = st.columns([1.4, 1.0])

    with col_pnl1:
        st.subheader("📑 Statement of Profit & Loss")
        st.markdown(clean_html(f"""
        <div style="background: rgba(18, 24, 38, 0.7); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 10px; padding: 1.5rem;">
            <div style="display: flex; justify-content: space-between; padding: 0.4rem 0; border-bottom: 1px solid rgba(255, 255, 255, 0.06);">
                <span style="color: #F8FAFC; font-weight: 600;">1. Gross Billed Sales:</span>
                <span style="color: #F8FAFC; font-weight: 600;">{format_inr(pnl['gross_billed'])}</span>
            </div>
            <div style="display: flex; justify-content: space-between; padding: 0.4rem 0; border-bottom: 1px solid rgba(255, 255, 255, 0.06);">
                <span style="color: #94A3B8;">&nbsp;&nbsp;&nbsp;&nbsp;Less: Customer & Trade Discounts:</span>
                <span style="color: #FB7185;">- {format_inr(pnl['total_discounts'])}</span>
            </div>
            <div style="display: flex; justify-content: space-between; padding: 0.4rem 0; border-bottom: 1px solid rgba(255, 255, 255, 0.06);">
                <span style="color: #94A3B8;">&nbsp;&nbsp;&nbsp;&nbsp;Less: Customer Sales Returns & Tax Refunds:</span>
                <span style="color: #FB7185;">- {format_inr(pnl['returns']['net_taxable_returns'])} ({pnl['returns']['returned_units_count']} units)</span>
            </div>
            <div style="display: flex; justify-content: space-between; padding: 0.5rem 0; background: rgba(255, 255, 255, 0.03); border-bottom: 1px solid rgba(255, 255, 255, 0.06);">
                <span style="color: #FCD34D; font-weight: 700;">2. Net Sales Revenue:</span>
                <span style="color: #FCD34D; font-weight: 700;">{format_inr(pnl['net_sales_revenue'])}</span>
            </div>
            <div style="display: flex; justify-content: space-between; padding: 0.4rem 0; border-bottom: 1px solid rgba(255, 255, 255, 0.06);">
                <span style="color: #94A3B8;">&nbsp;&nbsp;&nbsp;&nbsp;Less: Cost of Goods Sold (COGS - Cost Snapshots):</span>
                <span style="color: #FB7185;">- {format_inr(pnl['net_cogs'])}</span>
            </div>
            <div style="display: flex; justify-content: space-between; padding: 0.5rem 0; background: rgba(5, 150, 105, 0.1); border-bottom: 1px solid rgba(255, 255, 255, 0.06);">
                <span style="color: #34D399; font-weight: 700;">3. Gross Profit:</span>
                <span style="color: #34D399; font-weight: 700;">{format_inr(pnl['gross_profit'])} ({pnl['gross_margin_pct']:.1f}% Margin)</span>
            </div>
            <div style="display: flex; justify-content: space-between; padding: 0.4rem 0; border-bottom: 1px solid rgba(255, 255, 255, 0.06);">
                <span style="color: #94A3B8;">&nbsp;&nbsp;&nbsp;&nbsp;Less: Included Operating Expenses:</span>
                <span style="color: #FB7185;">- {format_inr(pnl['total_included_expenses'])}</span>
            </div>
            <div style="display: flex; justify-content: space-between; padding: 0.4rem 0; border-bottom: 1px solid rgba(255, 255, 255, 0.06);">
                <span style="color: #94A3B8;">&nbsp;&nbsp;&nbsp;&nbsp;Less: Damaged & Expired Stock Losses:</span>
                <span style="color: #FB7185;">- {format_inr(pnl['spoilage_loss'])}</span>
            </div>
            <hr style="border-color: rgba(217, 119, 6, 0.4); margin: 0.6rem 0;" />
            <div style="display: flex; justify-content: space-between; align-items: baseline; padding: 0.5rem 0;">
                <span style="color: #FFFFFF; font-size: 1.2rem; font-weight: 800;">4. NET OPERATING PROFIT:</span>
                <span style="color: {'#34D399' if pnl['net_operating_profit'] >= 0 else '#FB7185'}; font-size: 1.6rem; font-weight: 800;">{format_inr(pnl['net_operating_profit'])}</span>
            </div>
            <div style="display: flex; justify-content: space-between; padding-top: 0.3rem;">
                <span style="color: #94A3B8; font-size: 0.85rem;">Net Operating Margin:</span>
                <span style="color: #FCD34D; font-weight: 700; font-size: 0.95rem;">{pnl['net_margin_pct']:.1f}% | ROI: {pnl['festival_roi_pct']:.1f}%</span>
            </div>
        </div>
        """), unsafe_allow_html=True)

        # Labeled Exclusions Banner
        if pnl["has_exclusions"]:
            st.markdown("#### ⚠️ Labeled Exclusions from Net Operating Profit")
            st.caption(
                "In compliance with accounting standards, the following expenses are explicitly excluded "
                "from this campaign's net operating profit calculation:"
            )
            excl_df = pd.DataFrame(pnl["labeled_exclusions"])
            excl_df["amount"] = excl_df["amount"].apply(format_inr)
            st.dataframe(
                excl_df[["category", "description", "amount", "reason"]].rename(columns={
                    "category": "Category",
                    "description": "Description",
                    "amount": "Excluded Amount",
                    "reason": "Exclusion Reason"
                }),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.success("✅ All eligible operating expenses in this period are included with zero exclusions.")

    with col_pnl2:
        st.subheader("🥧 Operating Expense Allocation")
        exp_list = pnl.get("expense_breakdown", [])
        if exp_list:
            df_exp = pd.DataFrame(exp_list)
            df_exp["category_label"] = df_exp["expense_category"].apply(lambda c: STANDARD_CATEGORIES.get(c, c))
            fig_exp = px.pie(
                df_exp,
                names="category_label",
                values="category_total",
                hole=0.45,
                color_discrete_sequence=["#D97706", "#2563EB", "#059669", "#7C3AED", "#E11D48", "#0891B2"]
            )
            fig_exp.update_layout(get_festive_plotly_layout())
            st.plotly_chart(fig_exp, use_container_width=True)
        else:
            st.info("No operating expenses recorded for this selection.")

# -------------------------------------------------------------
# TAB 2: Record Expense
# -------------------------------------------------------------
with ep_tabs[1]:
    st.subheader("➕ Record Operating Expense")
    st.caption("Record Rent, Transport, Packaging, Wages, Marketing or Other operational expenses with optional festival linking.")

    with st.form("form_add_expense_v2", clear_on_submit=True):
        col_x1, col_x2 = st.columns(2)
        with col_x1:
            chosen_cat = st.selectbox("Expense Category *", options=[c[0] for c in CAT_CHOICES], format_func=lambda x: dict(CAT_CHOICES)[x])
            exp_amount = st.number_input("Amount (₹) *", min_value=1.0, max_value=5000000.0, step=500.0, value=5000.0)
            exp_date = st.date_input("Date Incurred *", value=date.today())
            exp_desc = st.text_input("Description *", placeholder="e.g. October Store Rent or 500 Gift Boxes")

        with col_x2:
            # Festival reference selection
            fest_ref_opts = {0: "General Store Overhead (No Festival Link)"}
            if not occ_df.empty:
                for _, r in occ_df.iterrows():
                    fest_ref_opts[r["occurrence_id"]] = f"{r['festival_name']} {r['year']} ({r['festival_date']})"

            chosen_occ = st.selectbox("Optional Festival Campaign Reference:", options=list(fest_ref_opts.keys()), format_func=lambda x: fest_ref_opts[x])
            exp_occ_id = None if chosen_occ == 0 else chosen_occ

            exp_pay_mode = st.selectbox("Payment Mode *", ["UPI", "CASH", "BANK_TRANSFER", "CARD", "OTHER"])
            vendor = st.text_input("Vendor / Payee Name", placeholder="e.g. Landlord, PrintPack Dadar, Delhivery Logistics")
            receipt_no = st.text_input("Receipt / Invoice / Reference No", placeholder="e.g. REC-2026-901")

        save_exp = st.form_submit_button("💾 Save Operating Expense", type="primary")

        if save_exp:
            try:
                new_id = record_expense(
                    amount=exp_amount,
                    expense_date=exp_date.strftime("%Y-%m-%d"),
                    category=chosen_cat,
                    description=exp_desc,
                    occurrence_id=exp_occ_id,
                    payment_mode=exp_pay_mode,
                    vendor_name=vendor if vendor else None,
                    invoice_receipt_no=receipt_no if receipt_no else None
                )
                st.success(f"✅ Expense #{new_id} recorded successfully with audit logging!")
                st.rerun()
            except Exception as e:
                st.error(f"Error saving expense: {str(e)}")

# -------------------------------------------------------------
# TAB 3: Expense Ledger
# -------------------------------------------------------------
with ep_tabs[2]:
    st.subheader("📋 Auditable Operating Expense Ledger")
    
    # Query expenses matching current scope
    ledger_sql = """
        SELECT e.expense_id, e.expense_date, e.expense_category, e.description, e.amount,
               e.payment_mode, e.status, e.vendor_name, e.invoice_receipt_no,
               f.festival_name, o.year
        FROM expenses e
        LEFT JOIN festival_occurrences o ON e.occurrence_id = o.occurrence_id
        LEFT JOIN festivals f ON o.festival_id = f.festival_id
        WHERE 1=1
    """
    params = []
    if occ_id_filter:
        ledger_sql += " AND e.occurrence_id = ?"
        params.append(occ_id_filter)
    if cat_arg:
        ledger_sql += " AND e.expense_category = ?"
        params.append(cat_arg)
    ledger_sql += " ORDER BY e.expense_date DESC, e.expense_id DESC"

    exp_ledger_df = query_df(ledger_sql, tuple(params))

    if not exp_ledger_df.empty:
        disp_ledger = exp_ledger_df.copy()
        disp_ledger["formatted_amount"] = disp_ledger["amount"].apply(format_inr)
        disp_ledger["festival_ref"] = disp_ledger.apply(
            lambda r: f"{r['festival_name']} {r['year']}" if pd.notnull(r["festival_name"]) else "General Overhead", axis=1
        )
        disp_ledger["status_badge"] = disp_ledger["status"].apply(
            lambda s: "✅ ACTIVE" if s == "ACTIVE" else ("✏️ CORRECTED" if s == "CORRECTED" else "❌ CANCELLED")
        )

        st.dataframe(
            disp_ledger[[
                "status_badge", "expense_id", "expense_date", "expense_category",
                "description", "formatted_amount", "festival_ref", "payment_mode",
                "vendor_name", "invoice_receipt_no"
            ]].rename(columns={
                "status_badge": "Status",
                "expense_id": "ID",
                "expense_date": "Date",
                "expense_category": "Category",
                "description": "Description",
                "formatted_amount": "Amount (₹)",
                "festival_ref": "Festival Reference",
                "payment_mode": "Payment",
                "vendor_name": "Vendor",
                "invoice_receipt_no": "Receipt #"
            }),
            use_container_width=True,
            hide_index=True
        )

        # Download Ledger CSV
        csv_bytes = exp_ledger_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Download Expense Ledger (CSV)",
            data=csv_bytes,
            file_name="FestivePulse_Expense_Ledger.csv",
            mime="text/csv"
        )
    else:
        st.info("No expenses found matching the selected scope.")

# -------------------------------------------------------------
# TAB 4: Edit & Correction Studio
# -------------------------------------------------------------
with ep_tabs[3]:
    st.subheader("✏️ Expense Edit, Correction & Audit Studio")
    st.markdown("All edits, corrections, and cancellations are tracked in the immutable `expense_audit_logs` table.")

    all_exp_df = query_df("SELECT expense_id, expense_date, expense_category, description, amount, status FROM expenses ORDER BY expense_id DESC LIMIT 100")
    if not all_exp_df.empty:
        exp_select_map = {
            r["expense_id"]: f"#{r['expense_id']} | {r['expense_date']} | {r['expense_category']} | {format_inr(r['amount'])} ({r['status']}) - {r['description']}"
            for _, r in all_exp_df.iterrows()
        }
        chosen_edit_id = st.selectbox(
            "Select Expense to Inspect, Edit or Cancel:",
            options=list(exp_select_map.keys()),
            format_func=lambda x: exp_select_map[x]
        )

        curr_exp_df = query_df("SELECT * FROM expenses WHERE expense_id = ?", (chosen_edit_id,))
        if curr_exp_df.empty:
            st.warning(f"Expense #{chosen_edit_id} record not found.")
            st.stop()
        curr_exp = curr_exp_df.iloc[0]

        col_ed1, col_ed2 = st.columns([1.2, 1.0])

        with col_ed1:
            st.markdown(f"#### 🛠️ Edit / Correct Expense #{chosen_edit_id}")
            with st.form(f"form_edit_exp_{chosen_edit_id}"):
                e_amt = st.number_input("Amount (₹) *", min_value=1.0, value=float(curr_exp["amount"]), step=500.0)
                parsed_e_date = pd.to_datetime(curr_exp["expense_date"], errors="coerce")
                default_e_date = parsed_e_date.date() if pd.notnull(parsed_e_date) else date.today()
                e_date = st.date_input("Date Incurred *", value=default_e_date)
                
                cat_keys = [c[0] for c in CAT_CHOICES]
                norm_c = normalize_category(curr_exp.get("expense_category", "OTHER"))
                cat_idx = cat_keys.index(norm_c) if norm_c in cat_keys else cat_keys.index("OTHER")
                e_cat = st.selectbox(
                    "Category *",
                    options=cat_keys,
                    index=cat_idx,
                    format_func=lambda x: dict(CAT_CHOICES)[x]
                )
                e_desc = st.text_input("Description *", value=str(curr_exp.get("description") or curr_exp.get("notes") or ""))
                e_vendor = st.text_input("Vendor / Payee Name", value=str(curr_exp["vendor_name"] or ""))
                e_receipt = st.text_input("Receipt / Bill No", value=str(curr_exp["invoice_receipt_no"] or ""))
                
                e_reason = st.text_area(
                    "Documented Audit Reason for Correction *",
                    placeholder="Mandatory: e.g. Transporter updated freight bill due to fuel surcharge revision"
                )

                submit_edit = st.form_submit_button("💾 Save Correction & Audit Trail", type="primary")

                if submit_edit:
                    if not e_reason.strip():
                        st.error("Audit reason is mandatory for modifying financial expense records.")
                    else:
                        try:
                            edit_expense(
                                expense_id=chosen_edit_id,
                                reason=e_reason,
                                amount=e_amt,
                                expense_date=e_date.strftime("%Y-%m-%d"),
                                category=e_cat,
                                description=e_desc,
                                vendor_name=e_vendor if e_vendor else None,
                                invoice_receipt_no=e_receipt if e_receipt else None
                            )
                            st.success(f"Expense #{chosen_edit_id} corrected and audit trail logged!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error updating expense: {str(e)}")

            # Cancellation Section
            if curr_exp["status"] != "CANCELLED":
                with st.expander("❌ Cancel / Void This Expense"):
                    st.warning("⚠️ Cancelling will mark the expense as CANCELLED and exclude it from P&L statements, while preserving historical audit logs.")
                    cancel_reason = st.text_input("Reason for Cancellation *", key=f"cancel_reason_{chosen_edit_id}", placeholder="e.g. Duplicate voucher entry or order cancelled")
                    confirm_cancel_exp = st.checkbox("I confirm that this expense voucher should be permanently cancelled", key=f"chk_canc_exp_{chosen_edit_id}")
                    if st.button("Confirm Cancellation", type="secondary", key=f"btn_cancel_{chosen_edit_id}", disabled=not confirm_cancel_exp):
                        if not cancel_reason.strip():
                            st.error("Cancellation reason is mandatory.")
                        else:
                            cancel_expense(chosen_edit_id, cancel_reason)
                            st.success(f"Expense #{chosen_edit_id} cancelled.")
                            st.rerun()

        with col_ed2:
            st.markdown(f"#### 📜 Audit Revision History (#{chosen_edit_id})")
            trail = get_expense_audit_trail(chosen_edit_id)
            if trail:
                for entry in trail:
                    with st.expander(f"📌 {entry['action']} on {entry['changed_at']} by {entry['changed_by']}", expanded=True):
                        st.markdown(f"**Reason:** *{entry['reason']}*")
                        if entry["previous_values"]:
                            st.markdown(f"**Previous Amount:** {format_inr(entry['previous_values'].get('amount', 0))} | **Category:** {entry['previous_values'].get('expense_category', 'N/A')}")
                        if entry["new_values"]:
                            st.markdown(f"**New Amount:** {format_inr(entry['new_values'].get('amount', 0))} | **Category:** {entry['new_values'].get('category', 'N/A')}")
            else:
                st.info("No prior revisions recorded for this expense.")
    else:
        st.info("No expenses available to edit.")

# -------------------------------------------------------------
# TAB 5: Documented Formulas
# -------------------------------------------------------------
with ep_tabs[4]:
    st.subheader("📖 Visible Mathematical Formulas & Accounting Standards")
    st.markdown(r"""
    FestivePulse adheres to deterministic retail accounting standards. Every metric is computed strictly from recorded transaction prices and cost snapshots:

    #### 1. Net Sales Revenue
    $$\text{Gross Taxable Sales} = \sum (\text{invoice.subtotal\_amount} - \text{invoice.discount\_amount})$$
    $$\text{Returns Refund Taxable} = \sum (\text{sales\_returns.refund\_amount} - \text{sales\_returns.tax\_refund\_amount})$$
    $$\text{Net Sales Revenue} = \text{Gross Taxable Sales} - \text{Returns Refund Taxable}$$

    ---

    #### 2. Cost of Goods Sold (COGS) & Cost Snapshot Insulation
    $$\text{Gross COGS} = \sum (\text{sales\_items.unit\_cost\_price} \times \text{sales\_items.quantity})$$
    $$\text{Returned COGS} = \sum (\text{sales\_items.unit\_cost\_price} \times \text{sales\_returns.quantity})$$
    $$\text{Net COGS} = \text{Gross COGS} - \text{Returned COGS}$$

    > **Historical Cost Snapshot Integrity:** `sales_items.unit_cost_price` captures the exact cost at the time of sale. If a supplier later raises prices in the catalog (`products.cost_price`), historical transaction COGS and Gross Profit remain completely unchanged.

    ---

    #### 3. Gross Profit & Gross Margin
    $$\text{Gross Profit} = \text{Net Sales Revenue} - \text{Net COGS}$$
    $$\text{Gross Margin \%} = \left(\frac{\text{Gross Profit}}{\text{Net Sales Revenue}}\right) \times 100$$

    ---

    #### 4. Operating Expenses & Net Operating Profit
    $$\text{Included Operating Expenses} = \sum \text{expenses.amount} \quad \text{where status} \neq \text{'CANCELLED' and matches scope}$$
    $$\text{Net Operating Profit} = \text{Gross Profit} - \text{Included Operating Expenses} - \text{Stock Spoilage Losses}$$
    $$\text{Net Operating Margin \%} = \left(\frac{\text{Net Operating Profit}}{\text{Net Sales Revenue}}\right) \times 100$$
    $$\text{Return on Investment (ROI \%)} = \left(\frac{\text{Net Operating Profit}}{\text{Net COGS} + \text{Included Operating Expenses}}\right) \times 100$$

    ---

    #### 5. Labeled Exclusions Standard
    When evaluating Net Operating Profit for a specific festival campaign or under category filters, all excluded expenses (cancelled entries, non-festival general overheads, or off-category costs) are explicitly itemized in the **Labeled Exclusions** ledger.
    """)
