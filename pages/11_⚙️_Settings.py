"""
FestivePulse — System Settings, Threat Model & Database Disaster Recovery Center
Provides configuration for:
1. Legal Store Profile, GSTIN, and Regional Localization
2. Currency Display, Timezone, and Report Settings
3. Local Deployment Threat Model & Operating Boundaries
4. Low-Level Database Integrity Verification (PRAGMA integrity_check)
5. Atomic Online Backups with SHA-256 Checksums
6. Disaster Recovery Restore with Confirmation & Automated Emergency Rollback
"""

from datetime import datetime
import streamlit as st
import pandas as pd

from database.connection import query_df, init_db
from database.queries import get_business_settings, update_business_settings
from config import INDIAN_STATES, REGIONS
from services.ui_components import (
    apply_custom_css,
    render_festival_header,
    render_standard_sidebar
)
from services.security_service import (
    check_database_integrity,
    create_database_backup,
    verify_backup_file,
    restore_database_backup,
    list_backups,
    validate_business_settings_input,
    validate_uploaded_file,
    BACKUP_DIR
)

st.set_page_config(page_title="Settings & Security — FestivePulse", page_icon="⚙️", layout="wide")
apply_custom_css()
render_festival_header()
render_standard_sidebar()

st.title("⚙️ Business Settings & Disaster Recovery Center")
st.caption(
    "Manage store configuration, regional localization, reporting preferences, "
    "low-level SQLite database integrity, and atomic disaster-recovery backups."
)

settings = get_business_settings()

set_tabs = st.tabs([
    "🏪 Store & Regional Localization",
    "🛡️ Local Deployment & Threat Model",
    "💾 Backup & Disaster Recovery",
    "🛠️ Factory Reset & Diagnostics"
])


# ==============================================================================
# TAB 1: STORE & REGIONAL LOCALIZATION
# ==============================================================================
with set_tabs[0]:
    st.subheader("🏪 Store Profile, Currency & Reporting Localization")
    st.markdown("These legal and regional details configure report headers, printed invoices, and analytical dashboards.")

    with st.form("form_store_settings"):
        col_s1, col_s2 = st.columns(2)

        with col_s1:
            st.markdown("##### 🏢 Business Legal Identity")
            b_name = st.text_input("Legal Business Name *", value=settings.get("business_name", "FestivePulse Retail Command"))
            t_name = st.text_input("Trade Name / Brand Name", value=settings.get("trade_name", ""))
            phone = st.text_input("Contact Phone Number *", value=settings.get("phone", "9876543210"))
            email = st.text_input("Email Address", value=settings.get("email", "store@festivepulse.local"))

            gstin = st.text_input("GSTIN (15 Digits)", value=settings.get("gstin", "")).strip().upper()
            st.caption("Standard 15-character GSTIN (e.g. 27AAACR1234M1Z5)")

            st.markdown("##### 📍 Store Location & State")
            addr1 = st.text_input("Address Line 1 *", value=settings.get("address_line1", "Shop 12, Market Road"))
            addr2 = st.text_input("Address Line 2 / Locality", value=settings.get("address_line2", ""))
            city = st.text_input("City *", value=settings.get("city", "Mumbai"))
            pincode = st.text_input("Pincode *", value=settings.get("pincode", "400001"))

            curr_state = settings.get("state", "Maharashtra")
            state_names = list(INDIAN_STATES.values())
            state_idx = state_names.index(curr_state) if curr_state in state_names else 0
            sel_state = st.selectbox("Operating State *", options=state_names, index=state_idx)
            matching_code = next((code for code, name in INDIAN_STATES.items() if name == sel_state), "27")
            st.write(f"State GST Code: **{matching_code}**")

        with col_s2:
            st.markdown("##### 🌐 Regional Focus & Timezone")
            curr_reg = settings.get("primary_region", "West")
            reg_idx = REGIONS.index(curr_reg) if curr_reg in REGIONS else 0
            sel_region = st.selectbox("Primary Operating Region *", options=REGIONS, index=reg_idx, help="Tailors festival calendars and default product tags.")

            timezones = [
                "Asia/Kolkata", "UTC", "Asia/Dubai", "Asia/Singapore", "Europe/London", "America/New_York"
            ]
            curr_tz = settings.get("timezone", "Asia/Kolkata")
            tz_idx = timezones.index(curr_tz) if curr_tz in timezones else 0
            sel_tz = st.selectbox("Operational Timezone *", options=timezones, index=tz_idx, help="Default for audit log timestamps and report generation dates.")

            st.markdown("##### 💵 Currency Display Format")
            currency_options = [
                "INR (₹)", "₹ (Rupee Symbol)", "INR Lakhs (₹ L)", "INR Standard"
            ]
            curr_cur_fmt = settings.get("currency_display", "INR (₹)")
            cur_idx = currency_options.index(curr_cur_fmt) if curr_cur_fmt in currency_options else 0
            sel_cur_fmt = st.selectbox("Currency Display Standard *", options=currency_options, index=cur_idx)

            st.markdown("##### 📑 Report Engine Settings")
            curr_orient = settings.get("report_page_orientation", "landscape")
            sel_orient = st.selectbox(
                "Default PDF Page Orientation",
                options=["landscape", "portrait"],
                index=0 if curr_orient == "landscape" else 1,
                format_func=lambda x: x.title()
            )

            curr_footer = settings.get("report_footer_notes", "FestivePulse AI — Local SQLite Database System Record")
            sel_footer = st.text_input("Default Report Footer Notice", value=curr_footer)

            curr_up_mb = int(settings.get("max_upload_size_mb", 10))
            sel_up_mb = st.slider("Maximum File Upload Limit (MB)", min_value=1, max_value=50, value=curr_up_mb, step=1)

        save_settings = st.form_submit_button("Save Store & Localization Configuration", type="primary")

        if save_settings:
            val_data = {
                "business_name": b_name,
                "phone": phone,
                "email": email,
                "gstin": gstin,
                "primary_region": sel_region,
                "timezone": sel_tz,
                "max_upload_size_mb": sel_up_mb
            }
            is_valid, err_list = validate_business_settings_input(val_data)
            if not is_valid:
                for err in err_list:
                    st.error(f"❌ {err}")
            else:
                success = update_business_settings(
                    business_name=b_name,
                    trade_name=t_name,
                    phone=phone,
                    email=email,
                    gstin=gstin,
                    address_line1=addr1,
                    address_line2=addr2,
                    city=city,
                    state=sel_state,
                    state_code=matching_code,
                    pincode=pincode,
                    primary_region=sel_region,
                    timezone=sel_tz,
                    currency_display=sel_cur_fmt,
                    report_footer_notes=sel_footer,
                    report_page_orientation=sel_orient,
                    max_upload_size_mb=sel_up_mb
                )
                if success:
                    st.success("✅ Configuration saved successfully!")
                    st.rerun()
                else:
                    st.error("Failed to update database settings.")


# ==============================================================================
# TAB 2: LOCAL DEPLOYMENT & THREAT MODEL
# ==============================================================================
with set_tabs[1]:
    st.subheader("🛡️ Local Deployment Architecture & Security Threat Model")

    st.info(
        "**Local Deployment Notice:** FestivePulse is designed specifically for **local small-business retail use** "
        "on a single trusted workstation or controlled local area network (LAN). It is **not** an automatically hardened, "
        "internet-facing multi-tenant cloud service. Please review the security boundaries below."
    )

    col_t1, col_t2 = st.columns(2)

    with col_t1:
        st.markdown("""
        ### 🔍 Operating Architecture & Trust Boundaries
        - **Local-First SQLite Engine**: Database transactions execute directly against a local file (`festivepulse.db`) using Write-Ahead Logging (WAL).
        - **Single-Operator Context**: FestivePulse operates under a trusted operator model. It does not provide per-user login credentials, role-based access control (RBAC), or multi-tenant database isolation.
        - **No Database At-Rest Encryption**: SQLite files are stored unencrypted on the local drive. Operating-system full-disk encryption (such as Windows BitLocker or Linux LUKS) must be enabled on the host computer to protect stored data from physical theft.
        - **No Public Internet Exposure**: FestivePulse must **never** be bound directly to a public IP address or open internet port without an external reverse proxy and firewall.
        """)

    with col_t2:
        st.markdown("""
        ### 🔒 Security Safeguards Implemented
        - **100% Parameterized SQL**: All queries use strict parameter substitution (`?`), eliminating SQL injection vulnerabilities.
        - **CSV Formula Injection (DDE) Neutralization**: All spreadsheet exports inspect cell content and escape leading triggers (`=`, `+`, `-`, `@`, `\t`, `\r`, `|`) with single quotes to prevent malicious command execution in Microsoft Excel and LibreOffice.
        - **Path Traversal Protection**: File operations enforce strict canonical directory containment (`is_relative_to`), preventing directory traversal attacks (`../`, `..\\`).
        - **Upload Size & Type Limits**: Uploaded files are capped (10 MB default) and screened against executable extensions (`.exe`, `.bat`, `.sh`, `.py`, `.js`).
        - **Non-Execution Invariant**: Uploaded content is parsed strictly as data (CSV text or SQLite binaries) and never passed to `eval()`, `exec()`, or system shells.
        """)

    st.divider()

    st.markdown("### 🏪 Recommended Local Retail Deployment Topologies")

    c_top1, c_top2 = st.columns(2)
    with c_top1:
        st.markdown("""
        **Scenario A: Single Billing Counter (Recommended)**
        - **Setup**: Run FestivePulse locally on the cashier PC (`localhost:8501`).
        - **Security**: Controlled physical access, Windows BitLocker enabled, local offline USB backups taken daily.
        - **Risk Level**: Minimal (Isolated to the physical store machine).
        """)
    with c_top2:
        st.markdown("""
        **Scenario B: Multi-Device LAN (Counter + Back-Office Tablet)**
        - **Setup**: Run on store server; access via trusted store Wi-Fi (e.g. `192.168.1.100:8501`).
        - **Security**: Store Wi-Fi secured with WPA3/WPA2-Enterprise; do **not** use guest Wi-Fi. If accessed across networks, put behind an **Nginx reverse proxy** with TLS (HTTPS) and HTTP Basic Authentication.
        - **Risk Level**: Moderate (Requires secure local network configuration).
        """)


# ==============================================================================
# TAB 3: BACKUP & DISASTER RECOVERY
# ==============================================================================
with set_tabs[2]:
    st.subheader("💾 Database Backup, Integrity Checks & Disaster Recovery")
    st.markdown("Create atomic snapshots of live data, verify file integrity, and restore safely with automatic emergency rollback protection.")

    # Section 1: Live Database Integrity Health
    diag = check_database_integrity()
    is_healthy = diag["is_healthy"]

    with st.container(border=True):
        h_col1, h_col2, h_col3, h_col4 = st.columns(4)
        with h_col1:
            st.metric("Database Health", "✅ HEALTHY" if is_healthy else "⚠️ ISSUES DETECTED")
        with h_col2:
            st.metric("Integrity Check", diag["integrity_status"].upper())
        with h_col3:
            st.metric("Foreign Key Violations", diag["foreign_key_violations_count"])
        with h_col4:
            st.metric("Database File Size", f"{diag['file_size_kb']} KB")

        if not is_healthy:
            st.error(f"⚠️ Database integrity warning: {diag['integrity_status']}. Foreign key issues: {diag['foreign_key_violations']}")
        else:
            st.caption(f"Last low-level PRAGMA verification: {diag['checked_at']} | Total Pages: {diag['page_count']} (Freelist: {diag['freelist_pages']})")

    st.divider()

    # Section 2: Create Instant Backup
    st.markdown("#### 📦 Create Instant Database Backup Snapshot")
    st.caption("Creates an atomic, consistent snapshot using SQLite's online backup API without interrupting active cashier billing.")

    b_col1, b_col2 = st.columns([3, 1])
    with b_col1:
        backup_notes = st.text_input("Optional Snapshot Notes:", placeholder="e.g. Pre-Diwali campaign freeze, End-of-month audit")
    with b_col2:
        st.write("")
        st.write("")
        create_btn = st.button("Create Atomic Backup", type="primary", use_container_width=True)

    if create_btn:
        with st.spinner("Executing atomic SQLite backup and verifying SHA-256 checksum..."):
            try:
                b_meta = create_database_backup(notes=backup_notes)
                st.success(
                    f"✅ Backup created and verified successfully! File: `{b_meta['filename']}` ({b_meta['file_size_bytes']:,} bytes) | "
                    f"SHA-256: `{b_meta['sha256'][:16]}...`"
                )
                st.rerun()
            except Exception as e:
                st.error(f"❌ Backup failed: {str(e)}")

    st.divider()

    # Section 3: Available Backups Ledger
    st.markdown("#### 📂 Available Verified Backups")
    existing_backups = list_backups()

    if existing_backups:
        b_df = pd.DataFrame(existing_backups)
        st.dataframe(
            b_df[["filename", "created_at", "file_size_kb", "sha256", "notes"]].rename(columns={
                "filename": "Backup Filename",
                "created_at": "Timestamp",
                "file_size_kb": "Size (KB)",
                "sha256": "SHA-256 Checksum",
                "notes": "Snapshot Notes"
            }),
            use_container_width=True,
            height=220
        )
    else:
        st.info("ℹ️ No backups currently stored in `data/backups/`. Create your first snapshot above.")

    st.divider()

    # Section 4: Disaster Recovery Restore
    st.markdown("#### 🔄 Restore Database from Verified Backup")
    st.warning(
        "⚠️ **Caution: Destructive Action.** Restoring a backup replaces current database records with the snapshot's records. "
        "FestivePulse automatically creates a safety rollback snapshot before overwriting live data."
    )

    restore_method = st.radio("Restore Source:", options=["Select from existing backup snapshots", "Upload a backup file (.db / .bak)"], horizontal=True)
    target_backup_path = None

    if restore_method == "Select from existing backup snapshots":
        if existing_backups:
            backup_names = [b["filename"] for b in existing_backups]
            chosen_backup = st.selectbox("Select Backup to Restore:", options=backup_names)
            target_backup_path = BACKUP_DIR / chosen_backup
        else:
            st.info("No stored backups available to select.")
    else:
        uploaded_backup = st.file_uploader("Upload SQLite Database Backup (.db, .sqlite, .bak):", type=["db", "sqlite", "sqlite3", "bak"])
        if uploaded_backup:
            up_bytes = uploaded_backup.read()
            v_ok, v_msg = validate_uploaded_file(uploaded_backup.name, up_bytes, allowed_extensions=(".db", ".sqlite", ".sqlite3", ".bak"))
            if not v_ok:
                st.error(v_msg)
            else:
                # Save temporarily to BACKUP_DIR for inspection
                temp_restore_file = BACKUP_DIR / f"temp_upload_{int(datetime.now().timestamp())}.db"
                with open(temp_restore_file, "wb") as f:
                    f.write(up_bytes)
                target_backup_path = temp_restore_file

    if target_backup_path and target_backup_path.exists():
        # Inspect target backup
        is_valid, v_msg, v_details = verify_backup_file(target_backup_path)
        if not is_valid:
            st.error(f"❌ Backup verification failed: {v_msg}")
        else:
            st.success(f"✅ Target backup is verified and valid ({v_details.get('file_size_bytes', 0):,} bytes).")
            counts_str = ", ".join([f"{k}: {v}" for k, v in v_details.get("record_counts", {}).items()])
            st.caption(f"Contained Records — {counts_str}")

            # Confirmation Checkbox (Safety requirement)
            confirm_restore = st.checkbox(
                "I understand this is a destructive action and confirm replacing live database records with this backup.",
                key="chk_confirm_restore"
            )

            if st.button("Execute Safe Database Restoration", type="primary", disabled=not confirm_restore):
                with st.spinner("Creating emergency rollback snapshot and restoring database..."):
                    success, res_msg = restore_database_backup(target_backup_path, confirm=True)
                    if success:
                        st.success(f"✅ {res_msg}")
                        st.balloons()
                        st.rerun()
                    else:
                        st.error(f"❌ {res_msg}")


# ==============================================================================
# TAB 4: FACTORY RESET & DIAGNOSTICS
# ==============================================================================
with set_tabs[3]:
    st.subheader("🛠️ Database Metrics & Factory Re-Seed")

    # Table Counts
    p_cnt = len(query_df("SELECT product_id FROM products"))
    b_cnt = len(query_df("SELECT batch_id FROM inventory_batches"))
    inv_cnt = len(query_df("SELECT invoice_id FROM sales_invoices"))
    exp_cnt = len(query_df("SELECT expense_id FROM expenses"))
    fest_cnt = len(query_df("SELECT occurrence_id FROM festival_occurrences"))

    d1, d2, d3, d4, d5 = st.columns(5)
    with d1:
        st.metric("Total Products", p_cnt)
    with d2:
        st.metric("Stock Batches", b_cnt)
    with d3:
        st.metric("Sales Invoices", inv_cnt)
    with d4:
        st.metric("Expense Vouchers", exp_cnt)
    with d5:
        st.metric("Scheduled Festivals", fest_cnt)

    st.divider()
    st.subheader("⚠️ Factory Reset & Demonstration Re-Seed")
    st.warning("This action drops all custom user entries and restores the clean demonstration seed baseline.")

    confirm_reset = st.checkbox("I understand that this will erase recent custom transactions and restore baseline demo records.", key="chk_factory_reset")
    if st.button("Reset Database to Demonstration State", type="primary", disabled=not confirm_reset):
        # Create an automatic backup before resetting
        try:
            create_database_backup(notes="Pre-Factory Reset Automatic Safety Snapshot")
        except Exception:
            pass

        init_db(force_recreate=True)
        st.success("Database restored to demonstration baseline successfully!")
        st.rerun()
