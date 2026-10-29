"""
FestivePulse — Data Import, Export & SQLite Database Management
Reliable CSV ingestion, downloadable templates, required-column documentation,
pre-import preview staging, duplicate detection, atomic rollback, safe error reporting,
filtered exports, and complete database backup/restore.
"""

from datetime import date
import streamlit as st
import pandas as pd

from database.connection import query_df
from config import DATABASE_PATH, EXPENSE_CATEGORIES
from services.ui_components import (
    apply_custom_css,
    render_festival_header,
    render_standard_sidebar
)
from services.import_export_service import (
    SCHEMAS,
    get_template_csv,
    get_column_documentation,
    preview_import,
    execute_import,
    export_products_to_csv,
    export_sales_to_csv,
    export_expenses_to_csv,
    export_stock_to_csv
)

st.set_page_config(page_title="Import & Export — FestivePulse", page_icon="📁", layout="wide")
apply_custom_css()
render_festival_header()
render_standard_sidebar()

st.title("📁 Data Import, Export & System Management")
st.caption("Reliable local-first CSV data operations with validation, preview staging, audit integrity, and filtered exports.")

io_tabs = st.tabs([
    "📥 Reliable CSV Import Studio",
    "📤 Filtered Data Export Studio",
    "💾 SQLite Database Backup & Restore"
])


# ==============================================================================
# TAB 1: Reliable CSV Import Studio
# ==============================================================================
with io_tabs[0]:
    st.subheader("📥 Reliable CSV Import Studio")
    st.markdown(
        "Import catalog products, sales bills, operating expenses, or inbound stock batches. "
        "Every file is validated before writing to ensure data integrity, stock availability, and duplicate prevention."
    )

    col_ent, col_mode = st.columns([1.5, 1.0])

    with col_ent:
        entity_choice = st.selectbox(
            "Select Data Entity to Import:",
            options=["products", "sales", "expenses", "stock"],
            format_func=lambda x: {
                "products": "🛍️ Products Catalog",
                "sales": "🧾 Sales Transactions & Invoices",
                "expenses": "💰 Operating Expenses & Overheads",
                "stock": "📦 Inbound Stock Batches (Movement Ledger Enforced)"
            }[x]
        )

    with col_mode:
        import_mode = st.radio(
            "Transaction & Error Handling Mode:",
            options=["atomic", "safe_row_by_row"],
            format_func=lambda x: "🛡️ Atomic (All-or-Nothing, Rollback on any Error)" if x == "atomic" else "⚡ Safe Row-by-Row (Import valid, report rejected)",
            help="Atomic mode rolls back all changes if any single row is invalid or duplicate. Safe Row-by-Row mode imports all valid rows and outputs a detailed rejected report."
        )

    st.markdown("---")

    # Template download and column documentation
    col_temp, col_doc = st.columns([1.2, 1.8])

    with col_temp:
        st.markdown(f"#### 📄 Download {SCHEMAS[entity_choice]['title']} Template")
        st.caption("Use our standard CSV template with pre-filled headers and realistic sample rows:")
        template_csv = get_template_csv(entity_choice)
        st.download_button(
            label=f"⬇️ Download {entity_choice.capitalize()} Template CSV",
            data=template_csv.encode("utf-8-sig"),
            file_name=f"festivepulse_{entity_choice}_template.csv",
            mime="text/csv",
            use_container_width=True
        )

    with col_doc:
        st.markdown("#### 📖 Required Columns & Specifications")
        with st.expander(f"View Column Specifications for {SCHEMAS[entity_choice]['title']}", expanded=False):
            doc_data = get_column_documentation(entity_choice)
            doc_df = pd.DataFrame(doc_data).rename(columns={
                "name": "Column Name",
                "required": "Mandatory?",
                "type": "Data Type",
                "format": "Allowed Format",
                "description": "Rules & Description"
            })
            doc_df["Mandatory?"] = doc_df["Mandatory?"].apply(lambda x: "✅ Required" if x else "⚪ Optional")
            st.dataframe(doc_df, use_container_width=True, hide_index=True)

    st.markdown("<br/>", unsafe_allow_html=True)

    # File uploader
    uploaded_file = st.file_uploader(
        f"Upload {SCHEMAS[entity_choice]['title']} CSV File:",
        type=["csv"],
        help="Upload standard UTF-8 or Excel CSV file."
    )

    if uploaded_file is not None:
        file_bytes = uploaded_file.getvalue()

        # Run Live Preview & Validation
        with st.spinner("Analyzing CSV structure and validating business rules..."):
            preview_res = preview_import(file_bytes, entity_choice)

        if not preview_res["success"]:
            st.error(f"❌ CSV Validation Error: {preview_res['error']}")
            if preview_res.get("missing_columns"):
                st.warning(f"Missing required columns: **{', '.join(preview_res['missing_columns'])}**")
        else:
            total_r = preview_res["total_rows"]
            valid_r = preview_res["valid_rows_count"]
            invalid_r = preview_res["invalid_rows_count"]

            # Visual summary chips
            st.markdown("### 🔍 Pre-Import Validation Report")
            k1, k2, k3, k4 = st.columns(4)
            with k1:
                st.metric("Total Rows in File", total_r)
            with k2:
                st.metric("✅ Valid Rows", valid_r)
            with k3:
                st.metric("❌ Invalid Rows", invalid_r)
            with k4:
                can_atomic = preview_res["can_import_atomic"]
                st.metric("Atomic Import Ready?", "Yes ✅" if can_atomic else "No (Errors Present) ⚠️")

            # Show preview table
            st.markdown("#### Preview of Rows to Import:")
            preview_df = pd.DataFrame(preview_res["preview_data"])

            # Highlight status column nicely
            def color_status(val):
                if val == "VALID":
                    return "background-color: rgba(34, 197, 94, 0.2); color: #86EFAC; font-weight: bold;"
                elif val == "INVALID":
                    return "background-color: rgba(239, 68, 68, 0.2); color: #FCA5A5; font-weight: bold;"
                return ""

            styled_df = preview_df.style.applymap(color_status, subset=["_status"])
            st.dataframe(styled_df, use_container_width=True, hide_index=True)

            if invalid_r > 0:
                st.warning(
                    f"⚠️ **{invalid_r} row(s) failed validation.** "
                    + ("In Atomic Mode, you must correct these rows before proceeding. In Safe Row-by-Row Mode, only the valid rows will be imported."
                       if import_mode == "atomic" else "Safe Row-by-Row Mode will import valid rows and isolate rejected rows.")
                )

            # Import Trigger Button
            button_label = (
                f"🚀 Execute Atomic Import ({valid_r} Rows)"
                if import_mode == "atomic"
                else f"⚡ Execute Safe Import ({valid_r} Valid / {invalid_r} Rejected)"
            )

            is_btn_disabled = (import_mode == "atomic" and invalid_r > 0) or (valid_r == 0)

            if st.button(button_label, type="primary", disabled=is_btn_disabled):
                with st.spinner("Executing safe database import..."):
                    exec_res = execute_import(file_bytes, entity_choice, atomic=(import_mode == "atomic"))

                if exec_res["success"]:
                    st.success(
                        f"🎉 Import Completed! Successfully accepted and recorded **{exec_res['accepted_count']}** rows."
                    )
                    if exec_res["rejected_count"] > 0:
                        st.error(
                            f"⚠️ **{exec_res['rejected_count']} rows were rejected** and not imported. See details below:"
                        )

                    # Show Accepted Rows
                    if exec_res["accepted_rows"]:
                        with st.expander(f"✅ View Accepted Rows ({exec_res['accepted_count']})", expanded=True):
                            acc_df = pd.DataFrame(exec_res["accepted_rows"]).rename(columns={
                                "row_num": "CSV Row #",
                                "identifier": "Record Identifier",
                                "detail": "Action Detail"
                            })
                            st.dataframe(acc_df, use_container_width=True, hide_index=True)

                    # Show Rejected Rows
                    if exec_res["rejected_rows"]:
                        with st.expander(f"❌ View Rejected Rows & Error Reasons ({exec_res['rejected_count']})", expanded=True):
                            rej_df = pd.DataFrame(exec_res["rejected_rows"])
                            st.dataframe(rej_df[["row_num", "reason"]].rename(columns={
                                "row_num": "CSV Row #",
                                "reason": "Failure Reason"
                            }), use_container_width=True, hide_index=True)

                else:
                    st.error(f"❌ Import Failed: {exec_res['error']}")
                    if exec_res.get("rejected_rows"):
                        rej_df = pd.DataFrame(exec_res["rejected_rows"])
                        st.dataframe(rej_df[["row_num", "reason"]].rename(columns={
                            "row_num": "CSV Row #",
                            "reason": "Failure Reason"
                        }), use_container_width=True, hide_index=True)


# ==============================================================================
# TAB 2: Filtered Data Export Studio
# ==============================================================================
with io_tabs[1]:
    st.subheader("📤 Filtered Data Export Studio")
    st.markdown("Export accurate, UTF-8 formatted CSV spreadsheets with customized date, category, status, and location filters.")

    exp_tabs = st.tabs([
        "🛍️ Products Catalog",
        "🧾 Sales Ledger",
        "💰 Expenses Ledger",
        "📦 Inventory & Stock Batches"
    ])

    # 1. Products Export
    with exp_tabs[0]:
        st.markdown("#### Export Products Master Catalog")
        col_p1, col_p2, col_p3 = st.columns(3)

        categories_df = query_df("SELECT category_id, category_name FROM product_categories ORDER BY category_name ASC")
        cat_opts = [("ALL", "All Product Categories")] + [(r["category_id"], r["category_name"]) for _, r in categories_df.iterrows()]

        with col_p1:
            sel_cat = st.selectbox("Category Filter:", options=[c[0] for c in cat_opts], format_func=lambda x: dict(cat_opts)[x], key="exp_p_cat")
            cat_filter = None if sel_cat == "ALL" else int(sel_cat)

        with col_p2:
            sel_active = st.selectbox("Status Filter:", ["ALL", "Active Only", "Inactive Only"], key="exp_p_act")
            act_filter = None if sel_active == "ALL" else (1 if sel_active == "Active Only" else 0)

        with col_p3:
            sel_perish = st.selectbox("Perishability:", ["ALL", "Perishable Items Only", "Non-Perishable Only"], key="exp_p_per")
            per_filter = None if sel_perish == "ALL" else (1 if sel_perish == "Perishable Items Only" else 0)

        p_search = st.text_input("Search Name / SKU / Barcode:", placeholder="e.g. Kaju, Diya, SKU-101", key="exp_p_search")

        prods_csv = export_products_to_csv(category_id=cat_filter, is_active=act_filter, is_perishable=per_filter, search=p_search)
        prods_count = max(0, len(prods_csv.strip().split("\n")) - 1)

        st.caption(f"Ready to export **{prods_count}** matching product records.")
        st.download_button(
            label=f"⬇️ Download Products CSV ({prods_count} records)",
            data=prods_csv.encode("utf-8-sig"),
            file_name="FestivePulse_Products_Export.csv",
            mime="text/csv",
            type="primary"
        )

    # 2. Sales Export
    with exp_tabs[1]:
        st.markdown("#### Export Sales & Invoicing Ledger")
        col_s1, col_s2, col_s3, col_s4 = st.columns(4)

        with col_s1:
            s_start = st.date_input("From Date:", value=date(2026, 1, 1), key="exp_s_start")
        with col_s2:
            s_end = st.date_input("To Date:", value=date.today(), key="exp_s_end")

        fests_df = query_df("""
            SELECT fo.occurrence_id, f.festival_name, fo.year
            FROM festival_occurrences fo
            JOIN festivals f ON fo.festival_id = f.festival_id
            ORDER BY fo.year DESC, f.festival_name ASC
        """)
        fest_opts = [("ALL", "All Festivals / Non-festival")] + [(r["occurrence_id"], f"{r['festival_name']} {r['year']}") for _, r in fests_df.iterrows()]

        with col_s3:
            sel_occ = st.selectbox("Festival Campaign:", options=[c[0] for c in fest_opts], format_func=lambda x: dict(fest_opts)[x], key="exp_s_occ")
            occ_filter = None if sel_occ == "ALL" else int(sel_occ)

        with col_s4:
            sel_pm = st.selectbox("Payment Mode:", ["ALL", "UPI", "CASH", "CARD", "CREDIT_KHATA"], key="exp_s_pm")

        sales_csv = export_sales_to_csv(
            start_date=str(s_start),
            end_date=str(s_end),
            occurrence_id=occ_filter,
            payment_mode=sel_pm
        )
        sales_count = max(0, len(sales_csv.strip().split("\n")) - 1)

        st.caption(f"Ready to export **{sales_count}** sales invoice line records.")
        st.download_button(
            label=f"⬇️ Download Sales Ledger CSV ({sales_count} lines)",
            data=sales_csv.encode("utf-8-sig"),
            file_name="FestivePulse_Sales_Ledger_Export.csv",
            mime="text/csv",
            type="primary"
        )

    # 3. Expenses Export
    with exp_tabs[2]:
        st.markdown("#### Export Operating Expenses Ledger")
        col_e1, col_e2, col_e3, col_e4 = st.columns(4)

        with col_e1:
            e_start = st.date_input("From Date:", value=date(2026, 1, 1), key="exp_e_start")
        with col_e2:
            e_end = st.date_input("To Date:", value=date.today(), key="exp_e_end")

        with col_e3:
            e_cats = [("ALL", "All Categories")] + [(c, c) for c in EXPENSE_CATEGORIES]
            sel_ecat = st.selectbox("Expense Category:", options=[c[0] for c in e_cats], key="exp_e_cat")

        with col_e4:
            sel_estat = st.selectbox("Audit Status:", ["ALL", "ACTIVE", "CORRECTED", "CANCELLED"], key="exp_e_stat")

        expenses_csv = export_expenses_to_csv(
            start_date=str(e_start),
            end_date=str(e_end),
            category=sel_ecat,
            status=sel_estat
        )
        exp_count = max(0, len(expenses_csv.strip().split("\n")) - 1)

        st.caption(f"Ready to export **{exp_count}** expense records.")
        st.download_button(
            label=f"⬇️ Download Expenses CSV ({exp_count} records)",
            data=expenses_csv.encode("utf-8-sig"),
            file_name="FestivePulse_Expenses_Export.csv",
            mime="text/csv",
            type="primary"
        )

    # 4. Stock Export
    with exp_tabs[3]:
        st.markdown("#### Export Inventory Stock Batches")
        col_k1, col_k2, col_k3 = st.columns(3)

        with col_k1:
            sel_stk_cat = st.selectbox("Category Filter:", options=[c[0] for c in cat_opts], format_func=lambda x: dict(cat_opts)[x], key="exp_stk_cat")
            stk_cat_arg = None if sel_stk_cat == "ALL" else int(sel_stk_cat)

        with col_k2:
            low_stk_toggle = st.checkbox("Show Low Stock Items Only", value=False, key="exp_stk_low")

        with col_k3:
            days_exp = st.slider("Expiring Within Days:", min_value=0, max_value=60, value=0, help="0 means show all batches regardless of expiry")
            exp_days_arg = days_exp if days_exp > 0 else None

        stock_csv = export_stock_to_csv(
            category_id=stk_cat_arg,
            low_stock_only=low_stk_toggle,
            expiring_soon_days=exp_days_arg
        )
        stock_count = max(0, len(stock_csv.strip().split("\n")) - 1)

        st.caption(f"Ready to export **{stock_count}** stock batch records.")
        st.download_button(
            label=f"⬇️ Download Stock Batches CSV ({stock_count} batches)",
            data=stock_csv.encode("utf-8-sig"),
            file_name="FestivePulse_Stock_Batches_Export.csv",
            mime="text/csv",
            type="primary"
        )


# ==============================================================================
# TAB 3: Database Backup & Restore
# ==============================================================================
with io_tabs[2]:
    st.subheader("💾 SQLite Database Backup & Restore")
    st.markdown("FestivePulse operates strictly on local-first ACID SQLite storage. You have full ownership of your data file.")

    col_bk1, col_bk2 = st.columns(2)

    with col_bk1:
        st.markdown("#### 📥 Instant Offline Backup")
        st.markdown("Download an instant snapshot of your entire business database (`festivepulse.db`).")
        if DATABASE_PATH.exists():
            with open(DATABASE_PATH, "rb") as f:
                st.download_button(
                    label="Download SQLite Database Snapshot (.db)",
                    data=f.read(),
                    file_name=f"festivepulse_backup_{date.today().strftime('%Y%m%d')}.db",
                    mime="application/x-sqlite3",
                    type="primary",
                    use_container_width=True
                )
        else:
            st.info("Database file not yet created.")

    with col_bk2:
        st.markdown("#### 📤 Restore Database from File")
        st.warning("⚠️ Warning: Restoring a database file will overwrite all local records. Create a backup first!")
        restore_file = st.file_uploader("Upload backup .db file:", type=["db", "sqlite"])
        if restore_file:
            if st.button("Confirm & Overwrite Current Database", type="secondary"):
                with open(DATABASE_PATH, "wb") as f:
                    f.write(restore_file.read())
                st.success("Database restored successfully! Please refresh the page.")
                st.rerun()
