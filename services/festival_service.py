"""
FestivePulse — Festival Management Service
Handles festival calendar, active campaign tracking, countdowns, and regional localization.
"""

from datetime import date, datetime
from typing import Optional, Dict, Any
from database.connection import db_session
from database.queries import get_active_festival_occurrence


def get_current_festival() -> Optional[Dict[str, Any]]:
    """
    Returns the currently active festival occurrence along with countdown metrics.
    """
    fest = get_active_festival_occurrence()
    if not fest:
        return None

    today = date.today()
    fest_date = datetime.strptime(fest["festival_date"], "%Y-%m-%d").date()
    peak_start = datetime.strptime(fest["peak_start_date"], "%Y-%m-%d").date()
    campaign_start = datetime.strptime(fest["campaign_start_date"], "%Y-%m-%d").date()
    campaign_end = datetime.strptime(fest["campaign_end_date"], "%Y-%m-%d").date()

    days_to_peak = (peak_start - today).days
    days_to_festival = (fest_date - today).days
    is_in_campaign = campaign_start <= today <= campaign_end

    if today < campaign_start:
        status_badge = "PREPARATION_PHASE"
        status_text = f"Procurement & Prep (Starts in {(campaign_start - today).days} days)"
    elif today < peak_start:
        status_badge = "CAMPAIGN_ACTIVE"
        status_text = f"Campaign Running ({days_to_peak} days to Peak Footfall)"
    elif today <= fest_date:
        status_badge = "PEAK_SALES_SURGE"
        status_text = f"🔥 PEAK SURGE ACTIVE (Festival Day in {days_to_festival} days)"
    elif today <= campaign_end:
        status_badge = "POST_FESTIVAL_CLEARANCE"
        status_text = f"Clearance & Return Window (Ends in {(campaign_end - today).days} days)"
    else:
        status_badge = "CAMPAIGN_CONCLUDED"
        status_text = "Campaign Concluded"

    fest["days_to_peak"] = days_to_peak
    fest["days_to_festival"] = days_to_festival
    fest["is_in_campaign"] = is_in_campaign
    fest["status_badge"] = status_badge
    fest["status_text"] = status_text
    return fest


def set_active_festival(occurrence_id: int) -> bool:
    """
    Sets the specified festival occurrence as active and deactivates all others.
    """
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE festival_occurrences SET is_current_active = 0")
        cursor.execute("UPDATE festival_occurrences SET is_current_active = 1 WHERE occurrence_id = ?", (occurrence_id,))
    return True


def add_festival_occurrence(
    festival_id: int,
    year: int,
    prep_start_date: str,
    campaign_start_date: str,
    peak_start_date: str,
    festival_date: str,
    campaign_end_date: str,
    notes: str = "",
    make_active: bool = False
) -> int:
    """
    Adds a new yearly occurrence for a festival with sequence validation.
    """
    # Validate chronological ordering
    d_prep = datetime.strptime(prep_start_date, "%Y-%m-%d").date()
    d_camp_start = datetime.strptime(campaign_start_date, "%Y-%m-%d").date()
    d_peak = datetime.strptime(peak_start_date, "%Y-%m-%d").date()
    d_fest = datetime.strptime(festival_date, "%Y-%m-%d").date()
    d_camp_end = datetime.strptime(campaign_end_date, "%Y-%m-%d").date()

    if not (d_prep <= d_camp_start <= d_peak <= d_fest <= d_camp_end):
        raise ValueError("Invalid timeline order: Must be Prep <= Campaign Start <= Peak Start <= Festival Date <= Campaign End.")

    with db_session() as conn:
        cursor = conn.cursor()
        if make_active:
            cursor.execute("UPDATE festival_occurrences SET is_current_active = 0")

        cursor.execute("""
            INSERT INTO festival_occurrences (
                festival_id, year, prep_start_date, campaign_start_date,
                peak_start_date, festival_date, campaign_end_date, notes, is_current_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            festival_id, year, prep_start_date, campaign_start_date,
            peak_start_date, festival_date, campaign_end_date, notes, 1 if make_active else 0
        ))
        return cursor.lastrowid


def update_festival_occurrence(
    occurrence_id: int,
    prep_start_date: str,
    campaign_start_date: str,
    peak_start_date: str,
    festival_date: str,
    campaign_end_date: str,
    notes: str = ""
) -> bool:
    d_prep = datetime.strptime(prep_start_date, "%Y-%m-%d").date()
    d_camp_start = datetime.strptime(campaign_start_date, "%Y-%m-%d").date()
    d_peak = datetime.strptime(peak_start_date, "%Y-%m-%d").date()
    d_fest = datetime.strptime(festival_date, "%Y-%m-%d").date()
    d_camp_end = datetime.strptime(campaign_end_date, "%Y-%m-%d").date()

    if not (d_prep <= d_camp_start <= d_peak <= d_fest <= d_camp_end):
        raise ValueError("Invalid timeline order: Must be Prep <= Campaign Start <= Peak Start <= Festival Date <= Campaign End.")

    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE festival_occurrences
            SET prep_start_date = ?, campaign_start_date = ?,
                peak_start_date = ?, festival_date = ?, campaign_end_date = ?, notes = ?
            WHERE occurrence_id = ?
        """, (prep_start_date, campaign_start_date, peak_start_date, festival_date, campaign_end_date, notes, occurrence_id))
    return True
