"""
FestivePulse — Rapid Point of Sale (POS) Counter Billing, Sales History & Returns
High-speed festival counter billing with Decimal monetary precision,
instant GST calculation, atomic FIFO stock depletion, UPI QR support,
safe cancellation reversals, and item-level returns.
"""

from datetime import date, timedelta
import streamlit as st
import pandas as pd
from database.queries import get_products_with_stock, query_df
from services.sales_service import (
    create_sales_invoice, cancel_sales_invoice, process_sales_return,
    correct_sales_invoice, get_invoice_full_details, get_sales_report_df,
    get_sales_line_items_df, get_sales_returns_df, get_sales_kpis
)
from repositories.sales_repository import (
    DuplicateTransactionError, InsufficientStockError,
    CustomerCreditLimitExceededError
)
from services.pdf_generator import generate_invoice_pdf
from services.currency_utils import format_inr, calculate_monetary_line
from services.ui_components import (
    apply_custom_css,
    render_festival_header,
    render_standard_sidebar,
    render_empty_state
)

st.set_page_config(page_title="Sales & POS — FestivePulse", page_icon="🧾", layout="wide")
apply_custom_css()
render_festival_header()
render_standard_sidebar()

st.title("🧾 Sales, Fast POS Billing & Returns Ledger")

# Initialize Cart in Session State
if "pos_cart" not in st.session_state:
    st.session_state.pos_cart = []

pos_tabs = st.tabs([
    "⚡ Fast Counter POS",
    "📜 Sales History & Search",
    "↩️ Returns & Reversals"
])

# -------------------------------------------------------------
# TAB 1: COUNTER POS BILLING
# -------------------------------------------------------------
with pos_tabs[0]:
    col_left, col_right = st.columns([1.6, 1.2])

    with col_left:
        st.subheader("🛍️ Product Selection")
        prods_df = get_products_with_stock()
        
        # Filter available products with stock > 0
        in_stock_df = prods_df[prods_df["current_stock"] > 0]
        
        if in_stock_df.empty:
            st.error("⚠️ All catalog products are currently out of stock! Receive inventory batches first.")
        else:
            p_options = {
                f"{r['sku']} — {r['product_name']} (₹{r['selling_price']:.2f} | Stock: {r['current_stock']} {r['unit_of_measure']})": r["product_id"]
                for _, r in in_stock_df.iterrows()
            }
            
            selected_label = st.selectbox("Search / Pick Product:", options=list(p_options.keys()))
            chosen_pid = p_options[selected_label]
            chosen_prod = in_stock_df[in_stock_df["product_id"] == chosen_pid].iloc[0]

            c_q1, c_q2, c_q3, c_q4 = st.columns([1.1, 1.1, 1.3, 1.1])
            with c_q1:
                bill_qty = st.number_input("Quantity *", min_value=1, max_value=int(chosen_prod["current_stock"]), value=1, step=1)
            with c_q2:
                bill_rate = st.number_input("Selling Price (₹) *", min_value=0.0, value=float(chosen_prod["selling_price"]), step=10.0)
            with c_q3:
                disc_type = st.selectbox("Disc Mode:", ["Percentage (%)", "Flat Cash (₹)"], key="disc_type_sel")
                if disc_type == "Percentage (%)":
                    bill_disc_pct = st.number_input("Discount %", min_value=0.0, max_value=100.0, value=0.0, step=1.0)
                    bill_disc_amt = 0.0
                else:
                    max_d = float(bill_qty * bill_rate)
                    bill_disc_amt = st.number_input("Discount (₹)", min_value=0.0, max_value=max(0.0, max_d), value=0.0, step=10.0)
                    bill_disc_pct = 0.0
            with c_q4:
                st.write("")
                st.write("")
                if st.button("➕ Add to Bill", type="secondary", use_container_width=True):
                    existing_idx = next((i for i, item in enumerate(st.session_state.pos_cart) if item["product_id"] == chosen_pid), None)
                    if existing_idx is not None:
                        new_q = st.session_state.pos_cart[existing_idx]["quantity"] + bill_qty
                        if new_q > chosen_prod["current_stock"]:
                            st.error(f"Cannot add: total quantity ({new_q}) exceeds available stock of {chosen_prod['current_stock']}.")
                        else:
                            st.session_state.pos_cart[existing_idx]["quantity"] = new_q
                            st.session_state.pos_cart[existing_idx]["selling_price"] = bill_rate
                            st.session_state.pos_cart[existing_idx]["discount_pct"] = bill_disc_pct
                            st.session_state.pos_cart[existing_idx]["discount_amount"] = bill_disc_amt
                            st.success(f"Updated quantity for {chosen_prod['product_name']}")
                            st.rerun()
                    else:
                        st.session_state.pos_cart.append({
                            "product_id": chosen_pid,
                            "sku": chosen_prod["sku"],
                            "product_name": chosen_prod["product_name"],
                            "quantity": bill_qty,
                            "unit_of_measure": chosen_prod["unit_of_measure"],
                            "selling_price": bill_rate,
                            "discount_pct": bill_disc_pct,
                            "discount_amount": bill_disc_amt,
                            "gst_rate": float(chosen_prod["gst_rate"])
                        })
                        st.success(f"Added {bill_qty}x {chosen_prod['product_name']}")
                        st.rerun()

        st.markdown("### 🛒 Active Bill Line Items")
        if st.session_state.pos_cart:
            cart_rows = []
            for idx, item in enumerate(st.session_state.pos_cart):
                calc = calculate_monetary_line(
                    quantity=item["quantity"],
                    unit_price=item["selling_price"],
                    discount_pct=item.get("discount_pct", 0.0),
                    discount_amount=item.get("discount_amount", 0.0),
                    gst_rate=item["gst_rate"]
                )
                disc_str = f"₹{float(calc['discount_amount']):.2f}" if item.get("discount_amount", 0) > 0 else f"{float(calc['discount_percent']):.0f}%"
                cart_rows.append({
                    "#": idx + 1,
                    "SKU": item["sku"],
                    "Item": item["product_name"],
                    "Qty": f"{item['quantity']} {item['unit_of_measure']}",
                    "Rate (₹)": f"{item['selling_price']:.2f}",
                    "Disc": disc_str,
                    "Taxable (₹)": f"{float(calc['taxable_amount']):.2f}",
                    "GST": f"{item['gst_rate']:.0f}%",
                    "Total (₹)": f"{float(calc['line_total']):.2f}"
                })
            
            st.dataframe(pd.DataFrame(cart_rows), use_container_width=True, hide_index=True)

            c_del1, c_del2 = st.columns([2, 1])
            with c_del2:
                if st.button("🗑️ Clear Cart", use_container_width=True):
                    st.session_state.pos_cart = []
                    st.rerun()
        else:
            st.info("The bill is empty. Select products above to add.")

    # Bill Summary & Checkout on Right Column
    with col_right:
        st.subheader("💰 Bill Summary & Payment")

        # Customer selection
        cust_df = query_df("SELECT * FROM customers ORDER BY customer_name ASC")
        cust_options = {0: "Cash / Walk-in Customer"}
        if not cust_df.empty:
            for _, c in cust_df.iterrows():
                khata_str = f" [Khata: ₹{c['outstanding_credit']:,.0f}]" if c['outstanding_credit'] > 0 else ""
                cust_options[c["customer_id"]] = f"{c['customer_name']} ({c['phone']}){khata_str}"

        sel_cust_id = st.selectbox("Customer:", options=list(cust_options.keys()), format_func=lambda x: cust_options[x])

        # Cart Totals Calculation using exact Decimal precision
        subtotal = 0.0
        taxable_total = 0.0
        gst_total = 0.0

        for item in st.session_state.pos_cart:
            c_calc = calculate_monetary_line(
                quantity=item["quantity"],
                unit_price=item["selling_price"],
                discount_pct=item.get("discount_pct", 0.0),
                discount_amount=item.get("discount_amount", 0.0),
                gst_rate=item["gst_rate"]
            )
            subtotal += float(c_calc["gross_amount"])
            taxable_total += float(c_calc["taxable_amount"])
            gst_total += float(c_calc["tax_total"])

        col_disc, col_pay = st.columns(2)
        with col_disc:
            inv_discount = st.number_input("Extra Cash Discount (₹)", min_value=0.0, max_value=max(0.0, taxable_total), value=0.0, step=10.0)
        with col_pay:
            pay_mode = st.selectbox("Payment Mode *", ["UPI", "CASH", "CARD", "CREDIT_KHATA", "SPLIT"])

        col_ref, col_date = st.columns(2)
        with col_ref:
            txn_ref = st.text_input("Transaction Ref (Optional)", placeholder="e.g. UPI UTR, Card Auth, PO #")
        with col_date:
            sale_date_input = st.date_input("Sale Date", value=date.today())

        sale_notes = st.text_input("Invoice Notes (Optional)", placeholder="e.g. Gift packaging requested")

        final_taxable = max(0.0, taxable_total - inv_discount)
        final_bill = final_taxable + gst_total
        rounded_bill = round(final_bill)
        roundoff = round(rounded_bill - final_bill, 2)

        st.markdown(f"""
        <div style="background: rgba(18, 24, 38, 0.85); padding: 1.25rem; border-radius: 10px; border: 1px solid rgba(217, 119, 6, 0.3); margin: 1rem 0;">
            <div style="display: flex; justify-content: space-between; margin-bottom: 0.35rem;">
                <span style="color: #94A3B8;">Gross Items Subtotal:</span>
                <span style="color: #F8FAFC; font-weight: 600;">₹{subtotal:,.2f}</span>
            </div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 0.35rem;">
                <span style="color: #94A3B8;">Total Discounts (Line + Bill):</span>
                <span style="color: #FB7185; font-weight: 600;">- ₹{(subtotal - final_taxable):,.2f}</span>
            </div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 0.35rem;">
                <span style="color: #94A3B8;">Taxable Amount:</span>
                <span style="color: #F8FAFC; font-weight: 600;">₹{final_taxable:,.2f}</span>
            </div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 0.35rem;">
                <span style="color: #94A3B8;">GST Total:</span>
                <span style="color: #FCD34D; font-weight: 600;">₹{gst_total:,.2f}</span>
            </div>
            <div style="display: flex; justify-content: space-between; margin-bottom: 0.35rem;">
                <span style="color: #94A3B8;">Round Off:</span>
                <span style="color: #94A3B8;">₹{roundoff:+.2f}</span>
            </div>
            <hr style="border-color: rgba(217, 119, 6, 0.3); margin: 0.5rem 0;" />
            <div style="display: flex; justify-content: space-between; align-items: baseline;">
                <span style="color: #FFFFFF; font-size: 1.1rem; font-weight: 700;">PAYABLE TOTAL:</span>
                <span style="color: #34D399; font-size: 1.75rem; font-weight: 800;">{format_inr(rounded_bill)}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

        if pay_mode == "UPI":
            st.info("📱 Prompt customer to scan QR code on counter / GPay / PhonePe / Paytm.")
        elif pay_mode == "CREDIT_KHATA" and sel_cust_id == 0:
            st.warning("⚠️ Khata credit sales require selecting a registered customer.")

        can_checkout = len(st.session_state.pos_cart) > 0
        if pay_mode == "CREDIT_KHATA" and sel_cust_id == 0:
            can_checkout = False

        if st.button("✅ COMPLETE SALE & GENERATE RECEIPT", type="primary", use_container_width=True, disabled=not can_checkout):
            try:
                c_id_arg = None if sel_cust_id == 0 else int(sel_cust_id)
                inv_id, inv_num = create_sales_invoice(
                    customer_id=c_id_arg,
                    payment_mode=pay_mode,
                    items=st.session_state.pos_cart,
                    overall_discount=inv_discount,
                    transaction_reference=txn_ref if txn_ref else None,
                    notes=sale_notes if sale_notes else None,
                    sale_date=sale_date_input.strftime("%Y-%m-%d") if sale_date_input else None
                )
                st.session_state.pos_cart = []
                st.session_state.last_invoice_id = inv_id
                st.session_state.last_invoice_num = inv_num
                st.success(f"🎉 Sale Completed! Invoice No: **{inv_num}**")
                st.rerun()
            except DuplicateTransactionError as dte:
                st.error(f"❌ Duplicate Transaction: {str(dte)}")
            except InsufficientStockError as ise:
                st.error(f"❌ Stock Error: {str(ise)}")
            except CustomerCreditLimitExceededError as cle:
                st.error(f"❌ Credit Limit Exceeded: {str(cle)}")
            except Exception as e:
                st.error(f"❌ Sale failed: {str(e)}")

        # Download button for just-completed invoice
        if "last_invoice_id" in st.session_state and st.session_state.last_invoice_id:
            last_id = st.session_state.last_invoice_id
            last_num = st.session_state.last_invoice_num
            try:
                pdf_path = generate_invoice_pdf(last_id)
                with open(pdf_path, "rb") as f:
                    st.download_button(
                        label=f"📥 Download Bill PDF ({last_num})",
                        data=f.read(),
                        file_name=f"{last_num}.pdf",
                        mime="application/pdf",
                        use_container_width=True
                    )
            except Exception as pdf_err:
                st.caption(f"PDF generator ready for invoice {last_num}")

# -------------------------------------------------------------
# TAB 2: SALES HISTORY & SEARCH
# -------------------------------------------------------------
with pos_tabs[1]:
    st.subheader("📜 Sales Invoices History, Filters & Export")

    # KPI Summary Cards
    kpis = get_sales_kpis()
    kp1, kp2, kp3, kp4 = st.columns(4)
    kp1.metric("Completed Sales Revenue", format_inr(kpis["total_revenue"]))
    kp2.metric("Total Invoices", f"{kpis['total_invoices']}")
    kp3.metric("Total Tax Collected", format_inr(kpis["total_tax"]))
    kp4.metric("Cancelled / Returned", f"{kpis['cancelled_count']} / {kpis['returns_count']}")

    st.markdown("<br/>", unsafe_allow_html=True)

    # Search & Filter Controls
    sf_c1, sf_c2, sf_c3, sf_c4 = st.columns(4)
    with sf_c1:
        s_search = st.text_input("🔍 Search (Invoice, Customer, Phone, Ref, Product / SKU):", placeholder="e.g. INV-2026, 98200, Kaju, SKU-DIW")
    with sf_c2:
        s_pay = st.selectbox("Payment Mode:", ["ALL", "UPI", "CASH", "CARD", "CREDIT_KHATA", "SPLIT"])
    with sf_c3:
        s_status = st.selectbox("Status:", ["ALL", "COMPLETED", "CANCELLED", "RETURNED", "PARTIALLY_RETURNED"])
    with sf_c4:
        s_date_range = st.date_input("Date Window:", value=(date.today() - timedelta(days=30), date.today() + timedelta(days=1)))

    start_d_str = None
    end_d_str = None
    if isinstance(s_date_range, tuple) and len(s_date_range) == 2:
        start_d_str = s_date_range[0].strftime("%Y-%m-%d")
        end_d_str = s_date_range[1].strftime("%Y-%m-%d")

    sales_df = get_sales_report_df(
        start_date=start_d_str,
        end_date=end_d_str,
        payment_mode=None if s_pay == "ALL" else s_pay,
        status=None if s_status == "ALL" else s_status,
        search=s_search if s_search else None,
        limit=200
    )

    if not sales_df.empty:
        df_disp = sales_df.copy()
        df_disp["subtotal_fmt"] = df_disp["subtotal_amount"].apply(lambda x: format_inr(x))
        df_disp["total_tax_fmt"] = (df_disp["cgst_amount"] + df_disp["sgst_amount"] + df_disp["igst_amount"]).apply(lambda x: format_inr(x))
        df_disp["net_total_fmt"] = df_disp["net_total_amount"].apply(lambda x: format_inr(x))
        df_disp["status_badge"] = df_disp["status"].apply(lambda s: {
            "COMPLETED": "✅ Completed",
            "CANCELLED": "❌ Cancelled",
            "RETURNED": "↩️ Returned",
            "PARTIALLY_RETURNED": "⚠️ Part-Returned"
        }.get(s, s))

        st.dataframe(
            df_disp[[
                "invoice_number", "invoice_date", "customer_name", "payment_mode",
                "subtotal_fmt", "total_tax_fmt", "net_total_fmt", "status_badge",
                "transaction_reference"
            ]].rename(columns={
                "invoice_number": "Invoice No",
                "invoice_date": "Date",
                "customer_name": "Customer",
                "payment_mode": "Payment",
                "subtotal_fmt": "Subtotal",
                "total_tax_fmt": "Tax",
                "net_total_fmt": "Total Amount",
                "status_badge": "Status",
                "transaction_reference": "Txn Reference"
            }),
            use_container_width=True,
            hide_index=True
        )

        c_exp1, c_exp2 = st.columns(2)
        with c_exp1:
            csv_sales = sales_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                "📥 Export Invoices Summary CSV",
                data=csv_sales,
                file_name=f"festivepulse_sales_{date.today().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                use_container_width=True
            )
        with c_exp2:
            lines_df = get_sales_line_items_df(
                start_date=start_d_str,
                end_date=end_d_str,
                payment_mode=None if s_pay == "ALL" else s_pay,
                status=None if s_status == "ALL" else s_status,
                search=s_search if s_search else None,
                limit=500
            )
            csv_lines = lines_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                "📥 Export Detailed Line Items CSV",
                data=csv_lines,
                file_name=f"festivepulse_sales_lines_{date.today().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                use_container_width=True
            )

        # Inspect specific invoice details
        st.divider()
        st.subheader("🔍 Inspect Invoice Details & Line Items")
        inv_choices = {r["invoice_number"]: r["invoice_id"] for _, r in sales_df.iterrows()}
        selected_inv_num = st.selectbox("Select invoice to inspect:", list(inv_choices.keys()))
        selected_inv_id = inv_choices[selected_inv_num]

        inv_details = get_invoice_full_details(selected_inv_id)
        if inv_details:
            id_c1, id_c2, id_c3, id_c4 = st.columns(4)
            id_c1.write(f"**Customer:** {inv_details.get('customer_name') or 'Cash / Walk-in'}")
            id_c2.write(f"**Phone:** {inv_details.get('customer_phone') or 'N/A'}")
            id_c3.write(f"**Status:** {inv_details.get('status')}")
            id_c4.write(f"**Net Total:** {format_inr(inv_details['net_total_amount'])}")

            if inv_details.get("items"):
                items_table = pd.DataFrame(inv_details["items"])
                items_table["unit_selling_price"] = items_table["unit_selling_price"].apply(lambda x: format_inr(x))
                items_table["taxable_value"] = items_table["taxable_value"].apply(lambda x: format_inr(x))
                items_table["total_item_amount"] = items_table["total_item_amount"].apply(lambda x: format_inr(x))

                st.dataframe(
                    items_table[[
                        "sku", "product_name", "batch_number", "quantity",
                        "unit_selling_price", "discount_percent", "taxable_value", "gst_rate", "total_item_amount"
                    ]].rename(columns={
                        "sku": "SKU",
                        "product_name": "Product",
                        "batch_number": "Batch",
                        "quantity": "Qty",
                        "unit_selling_price": "Rate",
                        "discount_percent": "Disc %",
                        "taxable_value": "Taxable",
                        "gst_rate": "GST %",
                        "total_item_amount": "Line Total"
                    }),
                    use_container_width=True,
                    hide_index=True
                )

            # PDF Download link
            try:
                pdf_p = generate_invoice_pdf(selected_inv_id)
                with open(pdf_p, "rb") as pf:
                    st.download_button(
                        label=f"📥 Download PDF Tax Receipt ({selected_inv_num})",
                        data=pf.read(),
                        file_name=f"{selected_inv_num}.pdf",
                        mime="application/pdf"
                    )
            except Exception:
                pass
    else:
        st.info("No sales records found matching the specified filter criteria.")

# -------------------------------------------------------------
# TAB 3: RETURNS & CANCELLATIONS WORKFLOW
# -------------------------------------------------------------
with pos_tabs[2]:
    st.subheader("↩️ Safe Cancellation Reversals & Item-Level Returns")
    st.markdown(
        "FestivePulse preserves complete accounting audit integrity. "
        "Sales are **never deleted**. Instead, cancellations and returns record reverse stock movements and revenue adjustments."
    )

    ret_tabs = st.tabs([
        "❌ Cancel Entire Order (Void)",
        "✏️ Safe Correction / Reissue",
        "🔄 Process Item-Level Return",
        "📜 Returns History Log"
    ])

    # SUB-TAB 1: Cancel Entire Order
    with ret_tabs[0]:
        st.subheader("❌ Void / Cancel Completed Sales Invoice")
        st.caption("Restores all line item quantities to inventory and reverses customer Khata credit without deleting audit history.")

        comp_invoices_df = get_sales_report_df(status="COMPLETED", limit=100)
        if not comp_invoices_df.empty:
            c_opts = {f"{r['invoice_number']} — ₹{r['net_total_amount']:.2f} ({r['customer_name']})": r["invoice_id"] for _, r in comp_invoices_df.iterrows()}
            sel_cancel_label = st.selectbox("Select completed invoice to cancel:", list(c_opts.keys()))
            sel_cancel_id = c_opts[sel_cancel_label]

            cancel_reason_input = st.text_input("Cancellation / Reversal Reason *", value="Customer requested order cancellation / duplicate order")

            confirm_cancel = st.checkbox(
                f"I confirm that invoice '{sel_cancel_label.split(' — ')[0]}' should be permanently voided and its inventory restored.",
                key=f"chk_void_inv_{sel_cancel_id}"
            )

            if st.button("🚨 Void Order & Reverse Inventory", type="primary", disabled=not confirm_cancel):
                if not cancel_reason_input or not cancel_reason_input.strip():
                    st.error("Please provide a mandatory cancellation reason.")
                else:
                    try:
                        cancel_sales_invoice(sel_cancel_id, reason=cancel_reason_input)
                        st.success("✅ Invoice cancelled successfully! Inventory restored to batches and logged in movement ledger.")
                        st.rerun()
                    except Exception as ce:
                        st.error(f"❌ Cancellation failed: {str(ce)}")
        else:
            render_empty_state("No Completed Invoices", "There are no completed invoices currently eligible for cancellation.")

    # SUB-TAB 2: Safe Correction / Reissue
    with ret_tabs[1]:
        st.subheader("✏️ Safe Invoice Correction & Re-Issuance")
        st.caption(
            "Atomically cancels the original invoice, restores stock, logs reverse SALE_CANCEL movements, "
            "and issues a corrected replacement invoice in a single ACID transaction without deleting audit history."
        )

        corr_invoices_df = get_sales_report_df(status="COMPLETED", limit=100)
        if not corr_invoices_df.empty:
            corr_opts = {
                f"{r['invoice_number']} — ₹{r['net_total_amount']:.2f} ({r['customer_name'] or 'Walk-in'}) [Date: {r['invoice_date']}]": r["invoice_id"]
                for _, r in corr_invoices_df.iterrows()
            }
            sel_corr_label = st.selectbox("Select invoice to correct / re-issue:", list(corr_opts.keys()), key="sel_corr_inv")
            sel_corr_id = corr_opts[sel_corr_label]

            orig_inv = get_invoice_full_details(sel_corr_id)
            if orig_inv:
                orig_col1, orig_col2, orig_col3, orig_col4 = st.columns(4)
                orig_col1.write(f"**Customer:** {orig_inv.get('customer_name') or 'Cash / Walk-in'}")
                orig_col2.write(f"**Current Payment:** {orig_inv.get('payment_mode')}")
                orig_col3.write(f"**Current Net Total:** {format_inr(orig_inv['net_total_amount'])}")
                orig_col4.write(f"**Txn Ref:** {orig_inv.get('transaction_reference') or 'None'}")

                st.markdown("#### 📝 Edit Invoice Items for Re-Issuance")
                st.caption("Adjust quantities, prices, or discounts below. Items with quantity = 0 will be omitted.")

                corr_items_key = f"corr_items_{sel_corr_id}"
                if corr_items_key not in st.session_state:
                    init_items = []
                    for it in orig_inv.get("items", []):
                        init_items.append({
                            "product_id": it["product_id"],
                            "sku": it["sku"],
                            "product_name": it["product_name"],
                            "quantity": int(it["quantity"]),
                            "selling_price": float(it["unit_selling_price"]),
                            "discount_pct": float(it.get("discount_percent") or 0.0),
                            "discount_amount": 0.0,
                            "gst_rate": float(it.get("gst_rate") or 0.0),
                            "unit_of_measure": it.get("unit_of_measure", "units")
                        })
                    st.session_state[corr_items_key] = init_items

                items_to_keep = []
                for i, itm in enumerate(st.session_state[corr_items_key]):
                    with st.expander(f"📦 Item {i+1}: {itm['sku']} — {itm['product_name']}", expanded=True):
                        ec1, ec2, ec3, ec4 = st.columns([1.2, 1.2, 1.2, 1.4])
                        with ec1:
                            new_q = st.number_input(
                                f"Quantity ({itm.get('unit_of_measure', 'units')})",
                                min_value=0,
                                value=int(itm["quantity"]),
                                step=1,
                                key=f"corr_q_{sel_corr_id}_{i}"
                            )
                        with ec2:
                            new_p = st.number_input(
                                "Unit Price (₹)",
                                min_value=0.0,
                                value=float(itm["selling_price"]),
                                step=10.0,
                                key=f"corr_p_{sel_corr_id}_{i}"
                            )
                        with ec3:
                            new_d_mode = st.selectbox(
                                "Disc Mode",
                                ["Percentage (%)", "Flat Cash (₹)"],
                                index=0 if itm.get("discount_amount", 0) == 0 else 1,
                                key=f"corr_dm_{sel_corr_id}_{i}"
                            )
                        with ec4:
                            if new_d_mode == "Percentage (%)":
                                new_dp = st.number_input("Disc %", min_value=0.0, max_value=100.0, value=float(itm.get("discount_pct", 0.0)), step=1.0, key=f"corr_dp_{sel_corr_id}_{i}")
                                new_da = 0.0
                            else:
                                max_da = float(new_q * new_p)
                                new_da = st.number_input("Disc (₹)", min_value=0.0, max_value=max(0.0, max_da), value=float(itm.get("discount_amount", 0.0)), step=10.0, key=f"corr_da_{sel_corr_id}_{i}")
                                new_dp = 0.0

                        if new_q > 0:
                            m_calc = calculate_monetary_line(
                                quantity=new_q,
                                unit_price=new_p,
                                discount_pct=new_dp,
                                discount_amount=new_da,
                                gst_rate=itm["gst_rate"]
                            )
                            st.caption(f"Line Subtotal: **₹{float(m_calc['gross_amount']):.2f}** | Taxable: **₹{float(m_calc['taxable_amount']):.2f}** | GST: **₹{float(m_calc['tax_total']):.2f}** | Total: **₹{float(m_calc['line_total']):.2f}**")
                            items_to_keep.append({
                                "product_id": itm["product_id"],
                                "sku": itm["sku"],
                                "product_name": itm["product_name"],
                                "quantity": new_q,
                                "unit_of_measure": itm.get("unit_of_measure", "units"),
                                "selling_price": new_p,
                                "discount_pct": new_dp,
                                "discount_amount": new_da,
                                "gst_rate": itm["gst_rate"]
                            })

                with st.expander("➕ Add Another Product to Corrected Invoice"):
                    catalog_df = get_products_with_stock()
                    if not catalog_df.empty:
                        cat_opts = {
                            f"{r['sku']} — {r['product_name']} (₹{r['selling_price']:.2f})": r["product_id"]
                            for _, r in catalog_df.iterrows()
                        }
                        add_pid_label = st.selectbox("Select product to add:", list(cat_opts.keys()), key=f"add_cat_prod_{sel_corr_id}")
                        add_pid = cat_opts[add_pid_label]
                        add_p_row = catalog_df[catalog_df["product_id"] == add_pid].iloc[0]

                        ap_c1, ap_c2, ap_c3 = st.columns(3)
                        with ap_c1:
                            add_q = st.number_input("Add Quantity", min_value=1, value=1, step=1, key=f"add_q_{sel_corr_id}")
                        with ap_c2:
                            add_rate = st.number_input("Rate (₹)", min_value=0.0, value=float(add_p_row["selling_price"]), step=10.0, key=f"add_r_{sel_corr_id}")
                        with ap_c3:
                            add_dp = st.number_input("Disc %", min_value=0.0, max_value=100.0, value=0.0, step=1.0, key=f"add_dp_{sel_corr_id}")

                        if st.button("➕ Add Item to Correction List", key=f"btn_add_item_{sel_corr_id}"):
                            st.session_state[corr_items_key].append({
                                "product_id": add_pid,
                                "sku": add_p_row["sku"],
                                "product_name": add_p_row["product_name"],
                                "quantity": add_q,
                                "unit_of_measure": add_p_row["unit_of_measure"],
                                "selling_price": add_rate,
                                "discount_pct": add_dp,
                                "discount_amount": 0.0,
                                "gst_rate": float(add_p_row["gst_rate"])
                            })
                            st.success(f"Added {add_p_row['product_name']} to correction list!")
                            st.rerun()

                st.markdown("#### ⚙️ Re-Issuance Metadata")
                cm_c1, cm_c2, cm_c3 = st.columns(3)
                with cm_c1:
                    pay_modes = ["UPI", "CASH", "CARD", "CREDIT_KHATA", "SPLIT"]
                    orig_pm = orig_inv.get("payment_mode", "CASH")
                    pm_idx = pay_modes.index(orig_pm) if orig_pm in pay_modes else 0
                    corr_pay_mode = st.selectbox("Updated Payment Mode *", pay_modes, index=pm_idx, key=f"corr_pm_{sel_corr_id}")
                with cm_c2:
                    corr_txn_ref = st.text_input("Updated Txn Ref (Optional)", value=orig_inv.get("transaction_reference") or "", key=f"corr_ref_{sel_corr_id}")
                with cm_c3:
                    corr_overall_disc = st.number_input("Bill-level Cash Discount (₹)", min_value=0.0, value=float(orig_inv.get("overall_discount") or 0.0), step=10.0, key=f"corr_disc_{sel_corr_id}")

                corr_reason = st.text_input(
                    "Mandatory Correction Reason *",
                    value="Rate adjustment / quantity correction requested by customer",
                    key=f"corr_reason_{sel_corr_id}"
                )

                if items_to_keep:
                    proj_subtotal = 0.0
                    proj_taxable = 0.0
                    proj_tax = 0.0
                    for kitm in items_to_keep:
                        kc = calculate_monetary_line(
                            quantity=kitm["quantity"],
                            unit_price=kitm["selling_price"],
                            discount_pct=kitm.get("discount_pct", 0.0),
                            discount_amount=kitm.get("discount_amount", 0.0),
                            gst_rate=kitm["gst_rate"]
                        )
                        proj_subtotal += float(kc["gross_amount"])
                        proj_taxable += float(kc["taxable_amount"])
                        proj_tax += float(kc["tax_total"])

                    proj_final_taxable = max(0.0, proj_taxable - corr_overall_disc)
                    proj_final = round(proj_final_taxable + proj_tax)

                    st.info(f"Projected Corrected Net Total: **{format_inr(proj_final)}** (Original: **{format_inr(orig_inv['net_total_amount'])}**)")

                if st.button("🚀 Execute Safe Correction & Re-Issue Invoice", type="primary", key=f"btn_corr_{sel_corr_id}"):
                    if not corr_reason or not corr_reason.strip():
                        st.error("Please provide a mandatory correction reason.")
                    elif not items_to_keep:
                        st.error("Corrected invoice must contain at least one valid item with quantity > 0.")
                    else:
                        try:
                            new_inv_id, new_inv_num = correct_sales_invoice(
                                original_invoice_id=sel_corr_id,
                                new_items=items_to_keep,
                                payment_mode=corr_pay_mode,
                                customer_id=orig_inv.get("customer_id"),
                                overall_discount=corr_overall_disc,
                                occurrence_id=orig_inv.get("occurrence_id"),
                                transaction_reference=corr_txn_ref.strip() if corr_txn_ref else None,
                                reason=corr_reason.strip(),
                                sale_date=orig_inv.get("sale_date")
                            )
                            if corr_items_key in st.session_state:
                                del st.session_state[corr_items_key]

                            st.session_state.last_invoice_id = new_inv_id
                            st.session_state.last_invoice_num = new_inv_num
                            st.success(
                                f"✅ Invoice safely corrected and re-issued! Original {orig_inv['invoice_number']} cancelled with audit reversal. "
                                f"New Invoice: **{new_inv_num}**."
                            )
                            st.rerun()
                        except InsufficientStockError as ise:
                            st.error(f"❌ Stock Error: {str(ise)}")
                        except DuplicateTransactionError as dte:
                            st.error(f"❌ Duplicate Reference Error: {str(dte)}")
                        except CustomerCreditLimitExceededError as cle:
                            st.error(f"❌ Khata Limit Exceeded: {str(cle)}")
                        except Exception as ce:
                            st.error(f"❌ Correction failed: {str(ce)}")
        else:
            st.info("No completed invoices available to correct.")

    # SUB-TAB 3: Process Item-Level Return
    with ret_tabs[2]:
        st.subheader("🔄 Process Item-Level Customer Return")
        st.markdown("Return individual items for exchange or refund with prorated GST adjustments.")

        eligible_df = get_sales_report_df(limit=100)
        # Filter for COMPLETED or PARTIALLY_RETURNED
        eligible_df = eligible_df[eligible_df["status"].isin(["COMPLETED", "PARTIALLY_RETURNED"])]

        if not eligible_df.empty:
            ret_inv_opts = {f"{r['invoice_number']} — ₹{r['net_total_amount']:.2f} ({r['customer_name']})": r["invoice_id"] for _, r in eligible_df.iterrows()}
            chosen_ret_inv_label = st.selectbox("Select invoice for item return:", list(ret_inv_opts.keys()))
            chosen_ret_inv_id = ret_inv_opts[chosen_ret_inv_label]

            inv_for_ret = get_invoice_full_details(chosen_ret_inv_id)
            if inv_for_ret and inv_for_ret.get("items"):
                st.write(f"**Customer:** {inv_for_ret.get('customer_name')} | **Payment:** {inv_for_ret.get('payment_mode')}")
                
                # Line item selector
                item_choices = {
                    f"{it['sku']} — {it['product_name']} (Sold Qty: {it['quantity']}, Rate: ₹{it['unit_selling_price']:.2f})": it["item_id"]
                    for it in inv_for_ret["items"]
                }
                sel_item_label = st.selectbox("Select line item to return:", list(item_choices.keys()))
                sel_item_id = item_choices[sel_item_label]
                sel_item = next(it for it in inv_for_ret["items"] if it["item_id"] == sel_item_id)

                col_rq1, col_rq2, col_rq3 = st.columns(3)
                with col_rq1:
                    ret_qty = st.number_input("Return Quantity *", min_value=1, max_value=int(sel_item["quantity"]), value=1, step=1)
                with col_rq2:
                    restock_flag = st.checkbox("Restock to Warehouse Inventory?", value=True, help="Uncheck if goods are damaged/expired.")
                with col_rq3:
                    ret_date_input = st.date_input("Return Date", value=date.today())

                ret_reason = st.text_input("Return Reason *", value="Customer returned item / wrong size / defective packaging")

                # Calculate estimated refund
                unit_refund = sel_item["total_item_amount"] / sel_item["quantity"]
                est_refund = round(unit_refund * ret_qty, 2)
                st.info(f"Calculated Refund Amount: **{format_inr(est_refund)}** (Including GST)")

                if st.button("Process Sales Return & Issue Credit / Refund", type="primary"):
                    if not ret_reason or not ret_reason.strip():
                        st.error("Please provide a return reason.")
                    else:
                        try:
                            ret_payload = [{
                                "item_id": sel_item_id,
                                "quantity": ret_qty,
                                "reason": ret_reason,
                                "restock": restock_flag
                            }]
                            r_id, r_num, ref_amt = process_sales_return(
                                invoice_id=chosen_ret_inv_id,
                                returned_items=ret_payload,
                                return_date=ret_date_input.strftime("%Y-%m-%d") if ret_date_input else None
                            )
                            st.success(f"✅ Return processed successfully! Return No: **{r_num}**, Refund Amount: **{format_inr(ref_amt)}**.")
                            st.rerun()
                        except Exception as re_err:
                            st.error(f"❌ Return processing failed: {str(re_err)}")
        else:
            st.info("No eligible invoices available for returns.")

    # SUB-TAB 4: Returns History Log
    with ret_tabs[3]:
        st.subheader("📜 Sales Returns & Refunds History")
        returns_df = get_sales_returns_df(limit=100)
        if not returns_df.empty:
            disp_ret = returns_df.copy()
            disp_ret["refund_fmt"] = disp_ret["refund_amount"].apply(lambda x: format_inr(x))
            disp_ret["restock_fmt"] = disp_ret["restock_to_inventory"].apply(lambda x: "Yes (Restocked)" if x else "No (Damaged Write-Off)")

            st.dataframe(
                disp_ret[[
                    "return_number", "invoice_number", "return_date", "sku",
                    "product_name", "quantity", "refund_fmt", "restock_fmt", "reason"
                ]].rename(columns={
                    "return_number": "Return No",
                    "invoice_number": "Invoice No",
                    "return_date": "Date",
                    "sku": "SKU",
                    "product_name": "Product",
                    "quantity": "Qty Returned",
                    "refund_fmt": "Refund Amount",
                    "restock_fmt": "Restocked",
                    "reason": "Return Reason"
                }),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("No sales returns recorded yet.")
