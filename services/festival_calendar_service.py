"""
FestivePulse — Configurable Festival Calendar Service
Business logic, boundary validations, regional filtering, upcoming festival timelines,
and overlapping planning periods analysis without external APIs or AI.
"""

from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional, Union, Tuple
import pandas as pd
from repositories.festival_calendar_repository import (
    FestivalCalendarRepository,
    SAMPLE_FESTIVAL_ENTRIES
)


def parse_iso_date(val: Union[str, date, datetime]) -> date:
    """Parses an ISO format date string or date object into a datetime.date."""
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    if not isinstance(val, str) or not val.strip():
        raise ValueError("Invalid date value: date cannot be empty.")
    try:
        return datetime.strptime(val.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"Invalid date format '{val}'. Expected YYYY-MM-DD.")


def validate_festival_dates(
    start_date: Union[str, date],
    end_date: Union[str, date],
    planning_window_days: Optional[int] = None,
    planning_start_date: Optional[Union[str, date]] = None
) -> Dict[str, Any]:
    """
    Validates festival date boundaries:
    1. start_date <= end_date (raises ValueError if start > end).
    2. planning_window_days >= 0 (raises ValueError if negative).
    3. planning_start_date <= start_date (raises ValueError if planning start > festival start).
    Returns reconciled dates and planning window duration.
    """
    d_start = parse_iso_date(start_date)
    d_end = parse_iso_date(end_date)

    if d_start > d_end:
        raise ValueError(
            f"Festival start date ({d_start.strftime('%Y-%m-%d')}) "
            f"cannot be after end date ({d_end.strftime('%Y-%m-%d')})."
        )

    # Reconcile planning start date and planning window days
    if planning_start_date is not None and str(planning_start_date).strip():
        d_p_start = parse_iso_date(planning_start_date)
        if d_p_start > d_start:
            raise ValueError(
                f"Planning start date ({d_p_start.strftime('%Y-%m-%d')}) "
                f"cannot be after festival start date ({d_start.strftime('%Y-%m-%d')})."
            )
        p_days = (d_start - d_p_start).days
    elif planning_window_days is not None:
        p_days = int(planning_window_days)
        if p_days < 0:
            raise ValueError("Planning window days cannot be negative.")
        d_p_start = d_start - timedelta(days=p_days)
    else:
        p_days = 30  # Default 30-day preparation window
        d_p_start = d_start - timedelta(days=p_days)

    return {
        "start_date": d_start.strftime("%Y-%m-%d"),
        "end_date": d_end.strftime("%Y-%m-%d"),
        "planning_start_date": d_p_start.strftime("%Y-%m-%d"),
        "planning_window_days": p_days,
        "celebration_days": (d_end - d_start).days + 1,
        "total_campaign_days": (d_end - d_p_start).days + 1,
        "year": d_start.year
    }


def validate_festival_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validates all mandatory fields and date boundaries for festival calendar entries.
    """
    name = str(data.get("festival_name", "") or "").strip()
    if not name:
        raise ValueError("Festival name is required and cannot be empty.")

    region = str(data.get("region", "") or "").strip()
    if not region:
        raise ValueError("Region is required and cannot be empty.")

    category = str(data.get("category", "") or "").strip()
    if not category:
        raise ValueError("Festival category is required and cannot be empty.")

    date_validation = validate_festival_dates(
        start_date=data.get("start_date"),
        end_date=data.get("end_date"),
        planning_window_days=data.get("planning_window_days"),
        planning_start_date=data.get("planning_start_date")
    )

    clean_data = dict(data)
    clean_data["festival_name"] = name
    clean_data["region"] = region
    clean_data["category"] = category
    clean_data["start_date"] = date_validation["start_date"]
    clean_data["end_date"] = date_validation["end_date"]
    clean_data["planning_start_date"] = date_validation["planning_start_date"]
    clean_data["planning_window_days"] = date_validation["planning_window_days"]
    clean_data["year"] = int(data.get("year", date_validation["year"]))
    clean_data["notes"] = str(data.get("notes", "") or "").strip()

    return clean_data


def filter_festivals_by_region(
    festivals: List[Dict[str, Any]],
    region: Optional[str] = None,
    include_pan_india: bool = True
) -> List[Dict[str, Any]]:
    """
    Filters a list of festival records by geographic region:
    - If region is None, 'All', or 'All Regions', returns all records.
    - If include_pan_india is True, includes 'Pan-India' festivals alongside regional ones.
    - Supports case-insensitive matching.
    """
    if not region or not region.strip():
        return list(festivals)

    clean_r = region.strip().lower()
    if clean_r in ("all", "all regions"):
        return list(festivals)

    filtered = []
    for f in festivals:
        f_reg = str(f.get("region", "")).strip().lower()
        if f_reg == clean_r:
            filtered.append(f)
        elif include_pan_india and f_reg == "pan-india":
            filtered.append(f)
        elif clean_r in f_reg:
            filtered.append(f)

    return filtered


def get_upcoming_festivals(
    reference_date: Optional[Union[str, date]] = None,
    region: Optional[str] = None,
    year: Optional[int] = None,
    category: Optional[str] = None,
    include_pan_india: bool = True
) -> List[Dict[str, Any]]:
    """
    Retrieves upcoming festivals relative to the reference date (defaults to today).
    Filters out festivals that have already concluded (end_date < reference_date).
    Computes countdowns, current operational phase, and days remaining.
    """
    ref_d = parse_iso_date(reference_date) if reference_date else date.today()
    all_festivals = FestivalCalendarRepository.get_all_entries(
        region=region,
        year=year,
        category=category,
        include_pan_india=include_pan_india
    )

    upcoming = []
    for f in all_festivals:
        s_date = parse_iso_date(f["start_date"])
        e_date = parse_iso_date(f["end_date"])
        p_date = parse_iso_date(f["planning_start_date"])

        if e_date < ref_d:
            continue  # Concluded festival

        days_to_fest = (s_date - ref_d).days
        days_to_plan = (p_date - ref_d).days
        dur_fest = (e_date - s_date).days + 1
        dur_plan = (s_date - p_date).days

        # Determine active operational phase
        if ref_d < p_date:
            phase = "PRE_PLANNING"
            phase_badge = "📅 UPCOMING"
            phase_desc = f"Planning starts in {days_to_plan} days (Festival in {days_to_fest} days)"
            days_in_phase = days_to_plan
        elif p_date <= ref_d < s_date:
            phase = "IN_PLANNING_WINDOW"
            phase_badge = "🛒 IN PLANNING WINDOW"
            phase_desc = f"Procurement & Inventory Prep Active ({days_to_fest} days until celebration)"
            days_in_phase = days_to_fest
        elif s_date <= ref_d <= e_date:
            day_number = (ref_d - s_date).days + 1
            phase = "ACTIVE_CELEBRATION"
            phase_badge = "🎉 ACTIVE CELEBRATION"
            phase_desc = f"Day {day_number} of {dur_fest} (Ends in {(e_date - ref_d).days} days)"
            days_in_phase = (e_date - ref_d).days
        else:
            phase = "CONCLUDED"
            phase_badge = "✅ CONCLUDED"
            phase_desc = "Festival celebration has concluded"
            days_in_phase = 0

        enriched = dict(f)
        enriched["days_until_festival"] = days_to_fest
        enriched["days_until_planning"] = days_to_plan
        enriched["phase"] = phase
        enriched["phase_badge"] = phase_badge
        enriched["phase_desc"] = phase_desc
        enriched["days_remaining_in_phase"] = days_in_phase
        enriched["celebration_duration_days"] = dur_fest
        enriched["planning_window_days"] = dur_plan
        upcoming.append(enriched)

    # Sort chronologically by start date, then planning start
    upcoming.sort(key=lambda x: (x["start_date"], x["planning_start_date"]))
    return upcoming


def detect_overlapping_festivals(
    festivals: Optional[List[Dict[str, Any]]] = None,
    region: Optional[str] = None,
    year: Optional[int] = None,
    include_pan_india: bool = True
) -> List[Dict[str, Any]]:
    """
    Identifies all pairs of festivals that have overlapping planning windows or celebration periods.
    Two festivals overlap if max(Start_A, Start_B) <= min(End_A, End_B).
    Returns detailed overlap metadata including dates, durations, and operational impact.
    """
    if festivals is None:
        festivals = FestivalCalendarRepository.get_all_entries(
            region=region,
            year=year,
            include_pan_india=include_pan_india
        )

    overlaps = []
    n = len(festivals)

    for i in range(n):
        for j in range(i + 1, n):
            f1 = festivals[i]
            f2 = festivals[j]

            # Full operational campaign window from planning start to festival end
            p1_start = parse_iso_date(f1["planning_start_date"])
            f1_start = parse_iso_date(f1["start_date"])
            f1_end = parse_iso_date(f1["end_date"])

            p2_start = parse_iso_date(f2["planning_start_date"])
            f2_start = parse_iso_date(f2["start_date"])
            f2_end = parse_iso_date(f2["end_date"])

            # Check campaign overlap (from planning start to celebration end)
            camp_overlap_start = max(p1_start, p2_start)
            camp_overlap_end = min(f1_end, f2_end)

            if camp_overlap_start <= camp_overlap_end:
                camp_overlap_days = (camp_overlap_end - camp_overlap_start).days + 1

                # Check if pre-festival planning windows specifically overlap
                plan_overlap_start = max(p1_start, p2_start)
                plan_overlap_end = min(f1_start, f2_start)
                is_planning_overlap = plan_overlap_start <= plan_overlap_end
                plan_overlap_days = (plan_overlap_end - plan_overlap_start).days + 1 if is_planning_overlap else 0

                # Check if celebration dates specifically overlap
                celeb_overlap_start = max(f1_start, f2_start)
                celeb_overlap_end = min(f1_end, f2_end)
                is_celeb_overlap = celeb_overlap_start <= celeb_overlap_end
                celeb_overlap_days = (celeb_overlap_end - celeb_overlap_start).days + 1 if is_celeb_overlap else 0

                if is_celeb_overlap:
                    o_type = "CONCURRENT_CELEBRATION"
                    desc = f"Main celebration dates overlap from {celeb_overlap_start} to {celeb_overlap_end} ({celeb_overlap_days} days)."
                elif is_planning_overlap:
                    o_type = "CONCURRENT_PLANNING"
                    desc = f"Pre-festival procurement planning windows overlap from {plan_overlap_start} to {plan_overlap_end} ({plan_overlap_days} days)."
                else:
                    o_type = "PLANNING_DURING_FESTIVAL"
                    desc = f"One festival's planning period runs concurrently during another's celebration window ({camp_overlap_days} days overlap)."

                overlaps.append({
                    "festival_a_id": f1.get("calendar_id"),
                    "festival_a_name": f1["festival_name"],
                    "festival_a_region": f1["region"],
                    "festival_a_dates": f"{f1['start_date']} to {f1['end_date']}",
                    "festival_a_planning": f"{f1['planning_start_date']} to {f1['start_date']}",
                    "festival_b_id": f2.get("calendar_id"),
                    "festival_b_name": f2["festival_name"],
                    "festival_b_region": f2["region"],
                    "festival_b_dates": f"{f2['start_date']} to {f2['end_date']}",
                    "festival_b_planning": f"{f2['planning_start_date']} to {f2['start_date']}",
                    "overlap_start_date": camp_overlap_start.strftime("%Y-%m-%d"),
                    "overlap_end_date": camp_overlap_end.strftime("%Y-%m-%d"),
                    "overlap_days": camp_overlap_days,
                    "planning_overlap_days": plan_overlap_days,
                    "celebration_overlap_days": celeb_overlap_days,
                    "overlap_type": o_type,
                    "description": desc
                })

    # Sort overlaps by start date of overlap
    overlaps.sort(key=lambda x: x["overlap_start_date"])
    return overlaps


def create_calendar_festival(data: Dict[str, Any]) -> int:
    """
    Validates inputs and persists a new festival calendar entry.
    """
    clean_data = validate_festival_data(data)
    return FestivalCalendarRepository.create_entry(clean_data)


def update_calendar_festival(calendar_id: int, data: Dict[str, Any]) -> bool:
    """
    Validates inputs and updates an existing festival calendar entry.
    """
    clean_data = validate_festival_data(data)
    return FestivalCalendarRepository.update_entry(calendar_id, clean_data)


def delete_calendar_festival(calendar_id: int) -> bool:
    """Deletes a festival calendar entry by ID."""
    return FestivalCalendarRepository.delete_entry(calendar_id)


def verify_festival_sample_dates(calendar_id: int, is_verified: bool = True) -> bool:
    """Marks a sample festival date as verified and confirmed by user."""
    return FestivalCalendarRepository.verify_sample_date(calendar_id, is_verified)


def get_calendar_festival_by_id(calendar_id: int) -> Optional[Dict[str, Any]]:
    """Retrieves a single calendar entry by ID."""
    return FestivalCalendarRepository.get_entry_by_id(calendar_id)


def get_calendar_festivals(
    region: Optional[str] = None,
    year: Optional[int] = None,
    category: Optional[str] = None,
    is_verified: Optional[bool] = None,
    search: Optional[str] = None,
    include_pan_india: bool = True
) -> List[Dict[str, Any]]:
    """Retrieves calendar entries matching query filters."""
    return FestivalCalendarRepository.get_all_entries(
        region=region,
        year=year,
        category=category,
        is_verified=is_verified,
        search=search,
        include_pan_india=include_pan_india
    )


def get_calendar_df(
    region: Optional[str] = None,
    year: Optional[int] = None,
    category: Optional[str] = None,
    is_verified: Optional[bool] = None,
    search: Optional[str] = None,
    include_pan_india: bool = True
) -> pd.DataFrame:
    """
    Returns a Pandas DataFrame of festival calendar entries with formatted status badges.
    """
    entries = get_calendar_festivals(
        region=region,
        year=year,
        category=category,
        is_verified=is_verified,
        search=search,
        include_pan_india=include_pan_india
    )
    if not entries:
        return pd.DataFrame()

    df = pd.DataFrame(entries)
    df["verification_status"] = df.apply(
        lambda r: "✅ Verified" if r.get("is_verified") else "⚠️ Sample (Needs Check)",
        axis=1
    )
    return df


def get_calendar_summary_metrics(
    region: Optional[str] = None,
    year: Optional[int] = None,
    reference_date: Optional[Union[str, date]] = None
) -> Dict[str, Any]:
    """
    Computes key calendar indicators: total festivals, upcoming count,
    sample dates pending verification, and active overlapping planning windows.
    """
    ref_d = parse_iso_date(reference_date) if reference_date else date.today()
    all_entries = get_calendar_festivals(region=region, year=year, include_pan_india=True)
    upcoming_entries = get_upcoming_festivals(reference_date=ref_d, region=region, year=year)
    overlaps = detect_overlapping_festivals(festivals=all_entries)

    unverified = [f for f in all_entries if not f.get("is_verified")]
    active_now = [f for f in upcoming_entries if f.get("phase") == "ACTIVE_CELEBRATION"]
    planning_now = [f for f in upcoming_entries if f.get("phase") == "IN_PLANNING_WINDOW"]

    return {
        "total_festivals": len(all_entries),
        "upcoming_count": len(upcoming_entries),
        "unverified_sample_count": len(unverified),
        "active_now_count": len(active_now),
        "in_planning_count": len(planning_now),
        "overlapping_windows_count": len(overlaps),
        "overlaps": overlaps
    }


def populate_future_festivals(start_year: int, end_year: int) -> int:
    """Populates all Indian festivals across a span of years (up to 200 years into the future)."""
    return FestivalCalendarRepository.populate_engine_festivals_range(start_year, end_year, skip_existing=True)


def project_festivals_for_year(year: int) -> List[Dict[str, Any]]:
    """Calculates all Indian festivals for any given year up to 200 years into the future."""
    from services.indian_calendar_engine import generate_all_indian_festivals_for_year
    return generate_all_indian_festivals_for_year(year)

