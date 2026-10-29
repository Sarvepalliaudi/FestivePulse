"""
FestivePulse — Configurable Festival Calendar & Campaign Management
Enables multi-region, multi-year festival date configuration, editable sample entries,
date boundary validation, upcoming timelines, and overlapping planning period detection.
"""

from datetime import date
import streamlit as st
import pandas as pd

from database.connection import query_df, db_session
from database.queries import get_all_festival_occurrences, get_categories
from services.festival_service import set_active_festival, add_festival_occurrence
from services.festival_calendar_service import (
    get_calendar_festivals,
    get_calendar_df,
    get_calendar_summary_metrics,
    get_upcoming_festivals,
    detect_overlapping_festivals,
    create_calendar_festival,
    update_calendar_festival,
    delete_calendar_festival,
    verify_festival_sample_dates,
    get_calendar_festival_by_id,
    parse_iso_date,
    populate_future_festivals,
    project_festivals_for_year
)
from repositories.festival_calendar_repository import FestivalCalendarRepository
from services.currency_utils import format_inr
from services.ui_components import (
    apply_custom_css,
    render_festival_header,
    render_standard_sidebar
)
from config import REGIONS

st.set_page_config(page_title="Festival Calendar — FestivePulse", page_icon="🎉", layout="wide")
apply_custom_css()
render_festival_header()
render_standard_sidebar()

st.title("🎉 Configurable Festival Calendar & Campaign Manager")
st.caption("Plan inventory, configure regional lunar/solar dates, track overlapping procurement periods, and benchmark retail campaigns.")

fest_tabs = st.tabs([
    "📅 Festival Calendar & Timeline",
    "✏️ Create & Edit Festival",
    "⚡ Active Campaign Manager",
    "🎯 Sales Targets & Budgets"
])

# -----------------------------------------------------------------------------
# TAB 1: Configurable Festival Calendar & Timeline
# -----------------------------------------------------------------------------
with fest_tabs[0]:
    st.subheader("📅 Indian Retail Festival Calendar")
    st.markdown(
        "Manage festival timelines across diverse Indian regions and years. "
        "Review sample dates, verify regional variations, and prepare for overlapping procurement windows."
    )

    # Summary Metrics
    summary = get_calendar_summary_metrics()
    m_col1, m_col2, m_col3, m_col4 = st.columns(4)
    with m_col1:
        st.metric("Total Configured", summary["total_festivals"])
    with m_col2:
        st.metric("Upcoming / Active", summary["upcoming_count"])
    with m_col3:
        unver_count = summary["unverified_sample_count"]
        st.metric(
            "Sample Dates (Check)",
            unver_count,
            delta="Needs verification" if unver_count > 0 else "All verified",
            delta_color="inverse" if unver_count > 0 else "normal"
        )
    with m_col4:
        st.metric("Overlapping Windows", summary["overlapping_windows_count"])

    st.markdown("---")

    # Filters Toolbar
    distinct_regions = ["All Regions", "Pan-India"] + [r for r in REGIONS if r != "Pan-India"]
    distinct_years = ["All Years"] + [str(y) for y in FestivalCalendarRepository.get_distinct_years()]
    distinct_cats = ["All Categories"] + FestivalCalendarRepository.get_distinct_categories()

    f_col1, f_col2, f_col3, f_col4 = st.columns([1.5, 1, 1, 1])
    with f_col1:
        search_kw = st.text_input("🔍 Search festival or notes", placeholder="e.g. Diwali, sweets, puja...")
    with f_col2:
        selected_region = st.selectbox("Region Filter", options=distinct_regions, index=0)
    with f_col3:
        selected_year_str = st.selectbox("Year", options=distinct_years, index=0)
        selected_year = None if selected_year_str == "All Years" else int(selected_year_str)
    with f_col4:
        selected_cat = st.selectbox("Category", options=distinct_cats, index=0)

    filter_region = None if selected_region == "All Regions" else selected_region
    filter_cat = None if selected_cat == "All Categories" else selected_cat

    # Fetch filtered calendar data
    filtered_festivals = get_calendar_festivals(
        region=filter_region,
        year=selected_year,
        category=filter_cat,
        search=search_kw if search_kw else None,
        include_pan_india=True
    )

    # 200-YEAR ASTRONOMICAL & LUNISOLAR CALENDAR ENGINE
    with st.expander("🔮 200-Year Indian Festival Calendar Engine (2024 to 2230+)", expanded=False):
        st.markdown(
            "FestivePulse includes a built-in mathematical and astronomical calendar projection engine "
            "that calculates all future festival dates for the next 200 years across **all calendars of India** "
            "(Hindu lunisolar Panchang, Islamic Tabular Hijri, Christian Gregorian Computus, Sikh, Jain, Buddhist, and Solar Harvest traditions). "
            "Dates are computed with verified lunisolar algorithms without any external APIs."
        )
        p_col1, p_col2 = st.columns([2, 1])
        with p_col1:
            target_proj_year = st.slider("Select Target Projection Year (Next 200 Years):", min_value=2024, max_value=2230, value=2027)
        with p_col2:
            st.write("")
            st.write("")
            if st.button(f"📥 Populate All Festivals for Year {target_proj_year}", type="primary"):
                count = FestivalCalendarRepository.populate_engine_festivals(target_proj_year, skip_existing=True)
                st.success(f"Added {count} Indian festivals for {target_proj_year} to store calendar!")
                st.rerun()

        st.markdown("##### 🚀 Multi-Year Batch Population")
        b_c1, b_c2, b_c3 = st.columns([1.5, 1.5, 1])
        with b_c1:
            start_batch = st.number_input("From Year", min_value=2024, max_value=2230, value=2026)
        with b_c2:
            end_batch = st.number_input("To Year", min_value=2024, max_value=2230, value=2030)
        with b_c3:
            st.write("")
            st.write("")
            if st.button("📥 Generate Range", type="secondary"):
                if start_batch > end_batch:
                    st.error("Start year must be <= End year.")
                else:
                    total_added = populate_future_festivals(int(start_batch), int(end_batch))
                    st.success(f"Populated {total_added} festivals across {start_batch} to {end_batch}!")
                    st.rerun()

        # Preview calculated festivals
        preview_list = project_festivals_for_year(target_proj_year)
        st.markdown(f"**Preview of Calculated Festivals for {target_proj_year} ({len(preview_list)} Festivals):**")
        preview_df = pd.DataFrame(preview_list)[["festival_name", "region", "category", "start_date", "end_date", "planning_window_days", "notes"]]
        st.dataframe(preview_df.rename(columns={
            "festival_name": "Festival",
            "region": "Region",
            "category": "Category",
            "start_date": "Start Date",
            "end_date": "End Date",
            "planning_window_days": "Planning Days",
            "notes": "Astronomical & Retail Notes"
        }), use_container_width=True)

    # 1. SAMPLE DATES AWAITING VERIFICATION SECTION
    unverified_samples = [f for f in filtered_festivals if f.get("is_sample_date") and not f.get("is_verified")]
    if unverified_samples:
        st.warning(
            f"⚠️ **{len(unverified_samples)} Pre-Configured Sample Festival Dates Pending Verification**\n\n"
            "Sample dates are pre-populated for Diwali, Christmas, Pongal, Onam, Bakrid/Eid al-Adha, "
            "Eid al-Fitr, Durga Puja, and Ganesh Chaturthi. Because regional traditions, state holidays, "
            "and lunar/solar calendars differ across India, please verify or customize these dates for your store's operating region."
        )

        with st.expander("🔍 Review & Verify Sample Festival Dates", expanded=True):
            for sample in unverified_samples:
                c_id = sample["calendar_id"]
                s_col1, s_col2, s_col3, s_col4 = st.columns([2.5, 2.5, 1.2, 1.2])
                with s_col1:
                    st.markdown(f"**{sample['festival_name']}** (`{sample['region']}`)")
                    st.caption(f"Category: {sample['category']} | Notes: {sample.get('notes') or 'N/A'}")
                with s_col2:
                    st.markdown(f"🗓️ **{sample['start_date']}** to **{sample['end_date']}**")
                    st.caption(f"🛒 Planning starts: {sample['planning_start_date']} ({sample['planning_window_days']} days prior)")
                with s_col3:
                    if st.button("✅ Confirm Date", key=f"verify_{c_id}", help="Mark date as verified for your retail store"):
                        verify_festival_sample_dates(c_id, is_verified=True)
                        st.success(f"Verified {sample['festival_name']}!")
                        st.rerun()
                with s_col4:
                    if st.button("✏️ Edit Dates", key=f"edit_btn_{c_id}", help="Modify dates, region, or planning window"):
                        st.session_state["edit_festival_id"] = c_id
                        st.info(f"Loaded {sample['festival_name']} into Tab 2 ('Create & Edit Festival').")

    # 2. OVERLAPPING PLANNING PERIODS DETECTOR
    overlaps = detect_overlapping_festivals(festivals=filtered_festivals)
    if overlaps:
        with st.expander(f"🔄 **Overlapping Planning & Festival Windows ({len(overlaps)} Detected)**", expanded=False):
            st.info(
                "💡 **Retail Insight:** Overlapping planning windows require coordinated inventory staging, "
                "earlier supplier orders, and split warehouse storage to avoid stockout bottlenecks."
            )
            overlap_rows = []
            for o in overlaps:
                overlap_rows.append({
                    "Festival Pair": f"{o['festival_a_name']} ({o['festival_a_region']}) ⟷ {o['festival_b_name']} ({o['festival_b_region']})",
                    "Overlap Type": o["overlap_type"],
                    "Overlap Date Range": f"{o['overlap_start_date']} to {o['overlap_end_date']}",
                    "Overlap Days": f"{o['overlap_days']} days",
                    "Planning Overlap": f"{o['planning_overlap_days']} days" if o['planning_overlap_days'] > 0 else "—",
                    "Description": o["description"]
                })
            st.dataframe(pd.DataFrame(overlap_rows), use_container_width=True)

    # 3. UPCOMING FESTIVALS & COUNTDOWN VIEW
    st.markdown("### 🕒 Upcoming Festivals & Timeline")
    upcoming_list = get_upcoming_festivals(
        region=filter_region,
        year=selected_year,
        category=filter_cat,
        include_pan_india=True
    )

    if upcoming_list:
        up_cols = st.columns(min(len(upcoming_list), 3))
        for idx, fest in enumerate(upcoming_list[:6]):
            col_target = up_cols[idx % 3]
            with col_target:
                with st.container(border=True):
                    # Badge
                    st.markdown(f"**{fest['phase_badge']}**")
                    st.markdown(f"### {fest['festival_name']}")
                    st.caption(f"📍 Region: **{fest['region']}** | Category: **{fest['category']}**")
                    st.markdown(f"🗓️ **{fest['start_date']}** to **{fest['end_date']}** ({fest['celebration_duration_days']} days)")
                    st.markdown(f"🛒 **Planning Window:** {fest['planning_window_days']} days (Starts {fest['planning_start_date']})")
                    st.info(fest["phase_desc"])
                    if fest.get("is_sample_date") and not fest.get("is_verified"):
                        st.warning("⚠️ Unverified Sample Date")
                    else:
                        st.caption("✅ Verified Store Date")
    else:
        st.info("No upcoming festivals found matching current filters.")

    # 4. MASTER CALENDAR TABLE
    st.markdown("### 📋 Complete Festival Calendar")
    calendar_df = get_calendar_df(
        region=filter_region,
        year=selected_year,
        category=filter_cat,
        search=search_kw if search_kw else None,
        include_pan_india=True
    )

    if not calendar_df.empty:
        disp_df = calendar_df[[
            "verification_status", "festival_name", "region", "year",
            "start_date", "end_date", "category", "planning_window_days",
            "planning_start_date", "notes"
        ]].rename(columns={
            "verification_status": "Status",
            "festival_name": "Festival Name",
            "region": "Region",
            "year": "Year",
            "start_date": "Start Date",
            "end_date": "End Date",
            "category": "Category",
            "planning_window_days": "Prep Days",
            "planning_start_date": "Planning Start",
            "notes": "Notes"
        })
        st.dataframe(disp_df, use_container_width=True)

        csv_data = calendar_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Export Festival Calendar (CSV)",
            data=csv_data,
            file_name=f"festivepulse_calendar_{selected_region or 'all'}_{date.today().strftime('%Y%m%d')}.csv",
            mime="text/csv"
        )
    else:
        st.info("No festivals found matching the selected filters.")

# -----------------------------------------------------------------------------
# TAB 2: Create & Edit Festival
# -----------------------------------------------------------------------------
with fest_tabs[1]:
    st.subheader("✏️ Configure Festival Entries")
    st.markdown(
        "Add a new festival entry or edit an existing one. "
        "Configure custom start/end dates, target regions, planning windows, and operational notes. "
        "Strict date validation ensures start date precedes end date and planning windows remain intact."
    )

    all_festivals_list = FestivalCalendarRepository.get_all_entries()
    mode = st.radio(
        "Select Operation:",
        options=["✏️ Edit Existing Festival", "➕ Add New Festival Entry"],
        horizontal=True
    )

    if mode == "✏️ Edit Existing Festival":
        if not all_festivals_list:
            st.info("No festivals available to edit. Add a new festival below.")
        else:
            fest_options = {
                f["calendar_id"]: f"{f['festival_name']} ({f['region']}, {f['year']}) {'[⚠️ Sample]' if f.get('is_sample_date') and not f.get('is_verified') else '[✅ Verified]'}"
                for f in all_festivals_list
            }

            # Check if an edit was requested from Tab 1
            default_index = 0
            if "edit_festival_id" in st.session_state:
                matched_id = st.session_state["edit_festival_id"]
                keys_list = list(fest_options.keys())
                if matched_id in keys_list:
                    default_index = keys_list.index(matched_id)

            chosen_id = st.selectbox(
                "Select Festival to Edit *",
                options=list(fest_options.keys()),
                index=default_index,
                format_func=lambda x: fest_options[x]
            )

            current_entry = get_calendar_festival_by_id(chosen_id)
            if current_entry:
                if current_entry.get("is_sample_date") and not current_entry.get("is_verified"):
                    st.warning("⚠️ This entry contains sample dates. Review dates carefully and check 'Mark as Verified' once confirmed.")

                with st.form("form_edit_festival"):
                    c1, c2 = st.columns(2)
                    with c1:
                        e_name = st.text_input("Festival Name *", value=current_entry["festival_name"])
                        # Region selection
                        all_regions_options = ["Pan-India"] + REGIONS
                        cur_reg = current_entry["region"]
                        reg_idx = all_regions_options.index(cur_reg) if cur_reg in all_regions_options else 0
                        e_region = st.selectbox("Region *", options=all_regions_options, index=reg_idx)

                        all_categories = [
                            "Major Religious", "Harvest", "Cultural & National",
                            "Regional & Folk", "New Year & Seasonal", "Clearance / Promotional"
                        ]
                        cur_cat = current_entry.get("category", "Major Religious")
                        cat_idx = all_categories.index(cur_cat) if cur_cat in all_categories else 0
                        e_category = st.selectbox("Category *", options=all_categories, index=cat_idx)

                    with c2:
                        s_dt = parse_iso_date(current_entry["start_date"])
                        e_dt = parse_iso_date(current_entry["end_date"])
                        e_start_date = st.date_input("Start Date *", value=s_dt)
                        e_end_date = st.date_input("End Date *", value=e_dt)
                        e_planning_days = st.number_input(
                            "Planning Window (Days before celebration) *",
                            min_value=0,
                            max_value=180,
                            value=int(current_entry.get("planning_window_days", 30))
                        )

                    e_notes = st.text_area(
                        "Operational & Regional Notes",
                        value=current_entry.get("notes") or "",
                        placeholder="e.g. Traditional sweets demand peaks 3 days prior; bulk procurement begins 4 weeks ahead."
                    )

                    e_verified = st.checkbox(
                        "Mark as Verified (Confirm this festival date is verified for your store)",
                        value=bool(current_entry.get("is_verified", False))
                    )

                    btn_save = st.form_submit_button("💾 Save Changes", type="primary")

                    if btn_save:
                        try:
                            # Strict validation check
                            update_data = {
                                "festival_name": e_name,
                                "region": e_region,
                                "category": e_category,
                                "start_date": e_start_date.strftime("%Y-%m-%d"),
                                "end_date": e_end_date.strftime("%Y-%m-%d"),
                                "planning_window_days": int(e_planning_days),
                                "notes": e_notes,
                                "is_verified": 1 if e_verified else 0,
                                "is_sample_date": 0 if e_verified else current_entry.get("is_sample_date", 1)
                            }
                            update_calendar_festival(chosen_id, update_data)
                            st.success(f"Festival '{e_name}' updated successfully!")
                            if "edit_festival_id" in st.session_state:
                                del st.session_state["edit_festival_id"]
                            st.rerun()
                        except ValueError as val_err:
                            st.error(f"Validation Error: {str(val_err)}")
                        except Exception as e:
                            st.error(f"Error saving festival: {str(e)}")

                st.markdown("---")
                col_del1, col_del2 = st.columns([3, 1])
                with col_del1:
                    confirm_del = st.checkbox(f"I want to permanently delete '{current_entry['festival_name']}'")
                with col_del2:
                    if st.button("🗑️ Delete Festival", type="secondary", disabled=not confirm_del):
                        delete_calendar_festival(chosen_id)
                        st.success(f"Festival entry deleted successfully.")
                        if "edit_festival_id" in st.session_state:
                            del st.session_state["edit_festival_id"]
                        st.rerun()

    else:
        # Add New Festival Entry
        st.markdown("#### ➕ Add New Festival to Calendar")
        with st.form("form_create_festival", clear_on_submit=True):
            n_col1, n_col2 = st.columns(2)
            with n_col1:
                new_name = st.text_input("Festival Name *", placeholder="e.g. Chhath Puja, Bihu, Ugadi, Karwa Chauth")
                new_region = st.selectbox("Region *", options=["Pan-India"] + REGIONS)
                new_category = st.selectbox(
                    "Category *",
                    options=[
                        "Major Religious", "Harvest", "Cultural & National",
                        "Regional & Folk", "New Year & Seasonal", "Clearance / Promotional"
                    ]
                )

            with n_col2:
                new_start_date = st.date_input("Start Date *", value=date.today())
                new_end_date = st.date_input("End Date *", value=date.today())
                new_planning_days = st.number_input("Planning Window (Days prior) *", min_value=0, max_value=180, value=30)

            new_notes = st.text_area(
                "Operational Notes",
                placeholder="Key items, procurement schedule, surge expectations, or local rituals."
            )

            submit_new = st.form_submit_button("➕ Create Festival Entry", type="primary")

            if submit_new:
                try:
                    create_data = {
                        "festival_name": new_name,
                        "region": new_region,
                        "category": new_category,
                        "start_date": new_start_date.strftime("%Y-%m-%d"),
                        "end_date": new_end_date.strftime("%Y-%m-%d"),
                        "planning_window_days": int(new_planning_days),
                        "notes": new_notes,
                        "is_sample_date": 0,
                        "is_verified": 1
                    }
                    new_id = create_calendar_festival(create_data)
                    st.success(f"Festival '{new_name}' created successfully with ID #{new_id}!")
                    st.rerun()
                except ValueError as val_err:
                    st.error(f"Validation Error: {str(val_err)}")
                except Exception as e:
                    st.error(f"Error creating festival: {str(e)}")

# -----------------------------------------------------------------------------
# TAB 3: Active Campaign Manager
# -----------------------------------------------------------------------------
with fest_tabs[2]:
    st.subheader("⚡ Manage Active Festival Campaign")
    st.markdown("Select which festival campaign is currently active to orient dashboard analytics, reorder advisor, and P&L metrics.")

    occ_df = get_all_festival_occurrences()
    if not occ_df.empty:
        disp_occ = occ_df.copy()
        disp_occ["is_current_active"] = disp_occ["is_current_active"].apply(lambda x: "🔥 ACTIVE" if x else "Inactive")
        st.dataframe(
            disp_occ[[
                "is_current_active", "festival_name", "year", "prep_start_date",
                "campaign_start_date", "peak_start_date", "festival_date", "campaign_end_date", "notes"
            ]].rename(columns={
                "is_current_active": "Status",
                "festival_name": "Festival",
                "year": "Year",
                "prep_start_date": "Procurement Start",
                "campaign_start_date": "Campaign Start",
                "peak_start_date": "Peak Start",
                "festival_date": "Festival Date",
                "campaign_end_date": "Clearance End",
                "notes": "Notes"
            }),
            use_container_width=True
        )

        st.markdown("#### ⚡ Set Active Festival Campaign")
        col_act1, col_act2 = st.columns([2, 1])
        with col_act1:
            active_options = {
                r["occurrence_id"]: f"{r['festival_name']} {r['year']} ({r['festival_date']})"
                for _, r in occ_df.iterrows()
            }
            selected_act = st.selectbox(
                "Select festival to set as active:",
                options=list(active_options.keys()),
                format_func=lambda x: active_options[x]
            )
        with col_act2:
            st.write("")
            st.write("")
            if st.button("Set as Active Campaign", type="primary"):
                set_active_festival(selected_act)
                st.success(f"Active campaign updated to {active_options[selected_act]}!")
                st.rerun()

        st.divider()
        st.subheader("➕ Schedule New Year Festival Occurrence")
        fest_master = query_df("SELECT * FROM festivals WHERE is_active = 1 ORDER BY festival_name ASC")
        fest_master_opts = {r["festival_id"]: r["festival_name"] for _, r in fest_master.iterrows()}

        with st.form("form_add_occurrence", clear_on_submit=True):
            col_o1, col_o2 = st.columns(2)
            with col_o1:
                sel_f_id = st.selectbox("Festival *", options=list(fest_master_opts.keys()), format_func=lambda x: fest_master_opts[x])
                target_year = st.number_input("Year *", min_value=2024, max_value=2035, value=2026)
                d_prep = st.date_input("Procurement / Prep Start Date *", value=date.today())
                d_camp_start = st.date_input("Campaign Start Date *", value=date.today())

            with col_o2:
                d_peak = st.date_input("Peak Footfall Start Date *", value=date.today())
                d_main = st.date_input("Main Festival Celebration Date *", value=date.today())
                d_camp_end = st.date_input("Campaign Clearance End Date *", value=date.today())
                occ_notes = st.text_input("Notes", placeholder="e.g. 10-day utsav, special stall at city center")

            submit_occ = st.form_submit_button("Add Festival Calendar Occurrence", type="secondary")

            if submit_occ:
                try:
                    add_festival_occurrence(
                        festival_id=sel_f_id,
                        year=int(target_year),
                        prep_start_date=d_prep.strftime("%Y-%m-%d"),
                        campaign_start_date=d_camp_start.strftime("%Y-%m-%d"),
                        peak_start_date=d_peak.strftime("%Y-%m-%d"),
                        festival_date=d_main.strftime("%Y-%m-%d"),
                        campaign_end_date=d_camp_end.strftime("%Y-%m-%d"),
                        notes=occ_notes
                    )
                    st.success("New festival occurrence added successfully!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error adding occurrence: {str(e)}")

# -----------------------------------------------------------------------------
# TAB 4: Sales Targets & Budgets
# -----------------------------------------------------------------------------
with fest_tabs[3]:
    st.subheader("🎯 Set Festival Revenue, Profit & Expense Targets")
    st.markdown("Set financial benchmarks for your festival campaign to track real-time pacing.")

    occ_list = query_df("""
        SELECT o.occurrence_id, f.festival_name, o.year
        FROM festival_occurrences o
        JOIN festivals f ON o.festival_id = f.festival_id
        ORDER BY o.year DESC, o.festival_date ASC
    """)

    if not occ_list.empty:
        occ_target_opts = {r["occurrence_id"]: f"{r['festival_name']} {r['year']}" for _, r in occ_list.iterrows()}
        chosen_occ_target = st.selectbox(
            "Select Festival Campaign:",
            options=list(occ_target_opts.keys()),
            format_func=lambda x: occ_target_opts[x]
        )

        existing_targets = query_df("""
            SELECT t.target_id, c.category_name, t.target_revenue, t.target_profit, t.budgeted_expenses
            FROM festival_sales_targets t
            JOIN product_categories c ON t.category_id = c.category_id
            WHERE t.occurrence_id = ?
        """, (chosen_occ_target,))

        if not existing_targets.empty:
            st.write("Current Configured Category Targets:")
            disp_t = existing_targets.copy()
            disp_t["target_revenue"] = disp_t["target_revenue"].apply(lambda x: format_inr(x))
            disp_t["target_profit"] = disp_t["target_profit"].apply(lambda x: format_inr(x))
            disp_t["budgeted_expenses"] = disp_t["budgeted_expenses"].apply(lambda x: format_inr(x))
            st.dataframe(disp_t[["category_name", "target_revenue", "target_profit", "budgeted_expenses"]].rename(columns={
                "category_name": "Category",
                "target_revenue": "Revenue Target",
                "target_profit": "Target Profit",
                "budgeted_expenses": "Budgeted Overheads"
            }), use_container_width=True)

        st.markdown("#### 📝 Add or Update Category Target")
        cats = get_categories()
        cat_map = {r["category_id"]: r["category_name"] for _, r in cats.iterrows()}

        with st.form("form_target"):
            t_col1, t_col2 = st.columns(2)
            with t_col1:
                t_cat_id = st.selectbox("Product Category *", options=list(cat_map.keys()), format_func=lambda x: cat_map[x])
                t_rev = st.number_input("Target Revenue (₹) *", min_value=1000.0, step=50000.0, value=500000.0)
            with t_col2:
                t_prof = st.number_input("Target Net Profit (₹)", min_value=0.0, step=25000.0, value=150000.0)
                t_exp = st.number_input("Budgeted Expenses (₹)", min_value=0.0, step=10000.0, value=40000.0)

            save_t_btn = st.form_submit_button("Save Campaign Target", type="primary")
            if save_t_btn:
                with db_session() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO festival_sales_targets (occurrence_id, category_id, target_revenue, target_profit, budgeted_expenses)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(occurrence_id, category_id) DO UPDATE SET
                            target_revenue = excluded.target_revenue,
                            target_profit = excluded.target_profit,
                            budgeted_expenses = excluded.budgeted_expenses
                    """, (chosen_occ_target, t_cat_id, t_rev, t_prof, t_exp))
                st.success("Target saved successfully!")
                st.rerun()
