"""
FestivePulse — Festival Calendar Repository
Persistence, retrieval, regional filtering, and verification of configurable festival calendar entries.
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from database.connection import get_db_connection, db_session


SAMPLE_FESTIVAL_ENTRIES = [
    {
        "festival_name": "Diwali & Dhanteras",
        "festival_code": "DIWALI",
        "region": "Pan-India",
        "start_date": "2026-11-08",
        "end_date": "2026-11-12",
        "category": "Traditional & Religious",
        "planning_window_days": 35,
        "planning_start_date": "2026-10-04",
        "notes": "[Sample / Indicative Date] Five-day Deepavali celebration (Dhanteras to Bhai Dooj). Main Lakshmi Puja on Nov 8. Please verify with local Panchang.",
        "is_sample_date": 1,
        "is_verified": 0,
        "year": 2026,
        "is_active_campaign": 1
    },
    {
        "festival_name": "Christmas",
        "festival_code": "CHRISTMAS",
        "region": "Pan-India",
        "start_date": "2026-12-24",
        "end_date": "2026-12-26",
        "category": "Cultural & National",
        "planning_window_days": 25,
        "planning_start_date": "2026-11-29",
        "notes": "[Sample / Indicative Date] Christmas Eve and Christmas Day peak sales. Please verify extended year-end sale window.",
        "is_sample_date": 1,
        "is_verified": 0,
        "year": 2026,
        "is_active_campaign": 0
    },
    {
        "festival_name": "Pongal",
        "festival_code": "PONGAL",
        "region": "South",
        "start_date": "2026-01-14",
        "end_date": "2026-01-17",
        "category": "Harvest & Agrarian",
        "planning_window_days": 25,
        "planning_start_date": "2025-12-20",
        "notes": "[Sample / Indicative Date] Thai Pongal, Mattu Pongal and Kaanum Pongal. Please verify with Tamil calendar.",
        "is_sample_date": 1,
        "is_verified": 0,
        "year": 2026,
        "is_active_campaign": 0
    },
    {
        "festival_name": "Onam",
        "festival_code": "ONAM",
        "region": "South",
        "start_date": "2026-08-25",
        "end_date": "2026-08-28",
        "category": "Harvest & Agrarian",
        "planning_window_days": 25,
        "planning_start_date": "2026-07-31",
        "notes": "[Sample / Indicative Date] Thiruvonam grand festival celebration. Please verify Chingam month dates with regional Malayalam calendar.",
        "is_sample_date": 1,
        "is_verified": 0,
        "year": 2026,
        "is_active_campaign": 0
    },
    {
        "festival_name": "Bakrid / Eid al-Adha",
        "festival_code": "BAKRID",
        "region": "Pan-India",
        "start_date": "2026-05-26",
        "end_date": "2026-05-28",
        "category": "Traditional & Religious",
        "planning_window_days": 20,
        "planning_start_date": "2026-05-06",
        "notes": "[Sample / Indicative Date] Feast of the Sacrifice. Subject to regional crescent moon sighting.",
        "is_sample_date": 1,
        "is_verified": 0,
        "year": 2026,
        "is_active_campaign": 0
    },
    {
        "festival_name": "Eid al-Fitr",
        "festival_code": "EID_FITR",
        "region": "Pan-India",
        "start_date": "2026-03-20",
        "end_date": "2026-03-22",
        "category": "Traditional & Religious",
        "planning_window_days": 25,
        "planning_start_date": "2026-02-23",
        "notes": "[Sample / Indicative Date] Concludes month of Ramadan. Subject to regional Shawwal crescent moon sighting.",
        "is_sample_date": 1,
        "is_verified": 0,
        "year": 2026,
        "is_active_campaign": 0
    },
    {
        "festival_name": "Durga Puja",
        "festival_code": "DURGA_PUJA",
        "region": "East",
        "start_date": "2026-10-16",
        "end_date": "2026-10-21",
        "category": "Traditional & Religious",
        "planning_window_days": 30,
        "planning_start_date": "2026-09-16",
        "notes": "[Sample / Indicative Date] Maha Sasthi to Bijoya Dashami. Please verify tithi timings with Bengali Panjika.",
        "is_sample_date": 1,
        "is_verified": 0,
        "year": 2026,
        "is_active_campaign": 0
    },
    {
        "festival_name": "Ganesh Chaturthi",
        "festival_code": "GANESH_CHATURTHI",
        "region": "West",
        "start_date": "2026-09-14",
        "end_date": "2026-09-24",
        "category": "Traditional & Regional",
        "planning_window_days": 25,
        "planning_start_date": "2026-08-20",
        "notes": "[Sample / Indicative Date] 10-day celebration concluding on Anant Chaturdashi. Please verify Bhadrapada Shukla Chaturthi date.",
        "is_sample_date": 1,
        "is_verified": 0,
        "year": 2026,
        "is_active_campaign": 0
    }
]


class FestivalCalendarRepository:

    @staticmethod
    def ensure_table_exists() -> None:
        """Ensures the festival_calendar table and indices exist in the database."""
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS festival_calendar (
                    calendar_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    festival_name TEXT NOT NULL,
                    festival_code TEXT,
                    region TEXT NOT NULL DEFAULT 'Pan-India',
                    start_date DATE NOT NULL,
                    end_date DATE NOT NULL,
                    category TEXT NOT NULL DEFAULT 'Traditional & Religious',
                    planning_window_days INTEGER NOT NULL DEFAULT 30,
                    planning_start_date DATE NOT NULL,
                    notes TEXT,
                    is_sample_date INTEGER DEFAULT 1 CHECK (is_sample_date IN (0, 1)),
                    is_verified INTEGER DEFAULT 0 CHECK (is_verified IN (0, 1)),
                    year INTEGER NOT NULL,
                    is_active_campaign INTEGER DEFAULT 0 CHECK (is_active_campaign IN (0, 1)),
                    occurrence_id INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (occurrence_id) REFERENCES festival_occurrences(occurrence_id) ON DELETE SET NULL
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_festival_calendar_dates ON festival_calendar(start_date, end_date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_festival_calendar_region ON festival_calendar(region)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_festival_calendar_planning ON festival_calendar(planning_start_date)")

    @staticmethod
    def seed_sample_festivals(force: bool = False) -> int:
        """
        Seeds standard editable sample entries for Diwali, Christmas, Pongal, Onam,
        Bakrid/Eid al-Adha, Eid al-Fitr, Durga Puja, and Ganesh Chaturthi.
        All sample dates are clearly marked with is_sample_date=1, is_verified=0.
        """
        FestivalCalendarRepository.ensure_table_exists()
        with db_session() as conn:
            cursor = conn.cursor()
            if not force:
                cursor.execute("SELECT COUNT(*) FROM festival_calendar")
                if cursor.fetchone()[0] > 0:
                    return 0

            inserted = 0
            for entry in SAMPLE_FESTIVAL_ENTRIES:
                cursor.execute("""
                    INSERT INTO festival_calendar (
                        festival_name, festival_code, region, start_date, end_date,
                        category, planning_window_days, planning_start_date, notes,
                        is_sample_date, is_verified, year, is_active_campaign
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    entry["festival_name"],
                    entry["festival_code"],
                    entry["region"],
                    entry["start_date"],
                    entry["end_date"],
                    entry["category"],
                    entry["planning_window_days"],
                    entry["planning_start_date"],
                    entry["notes"],
                    entry["is_sample_date"],
                    entry["is_verified"],
                    entry["year"],
                    entry.get("is_active_campaign", 0)
                ))
                inserted += 1
            return inserted

    @staticmethod
    def create_entry(data: Dict[str, Any]) -> int:
        """
        Creates a new festival calendar entry.
        """
        FestivalCalendarRepository.ensure_table_exists()
        s_date_str = str(data["start_date"]).strip()
        e_date_str = str(data["end_date"]).strip()
        s_date = datetime.strptime(s_date_str, "%Y-%m-%d").date()
        e_date = datetime.strptime(e_date_str, "%Y-%m-%d").date()

        # Handle planning window and start date
        if "planning_start_date" in data and data["planning_start_date"]:
            p_start_str = str(data["planning_start_date"]).strip()
            p_start = datetime.strptime(p_start_str, "%Y-%m-%d").date()
            p_days = (s_date - p_start).days
        else:
            p_days = int(data.get("planning_window_days", 30))
            p_start = s_date - timedelta(days=p_days)
            p_start_str = p_start.strftime("%Y-%m-%d")

        year_val = int(data.get("year", s_date.year))
        is_sample = 1 if data.get("is_sample_date", False) else 0
        is_verif = 1 if data.get("is_verified", False) else 0

        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO festival_calendar (
                    festival_name, festival_code, region, start_date, end_date,
                    category, planning_window_days, planning_start_date, notes,
                    is_sample_date, is_verified, year, is_active_campaign, occurrence_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(data["festival_name"]).strip(),
                data.get("festival_code", "").strip().upper() or None,
                str(data.get("region", "Pan-India")).strip(),
                s_date_str,
                e_date_str,
                str(data.get("category", "Traditional & Religious")).strip(),
                p_days,
                p_start_str,
                str(data.get("notes", "") or "").strip(),
                is_sample,
                is_verif,
                year_val,
                1 if data.get("is_active_campaign") else 0,
                data.get("occurrence_id")
            ))
            return cursor.lastrowid

    @staticmethod
    def update_entry(calendar_id: int, data: Dict[str, Any]) -> bool:
        """
        Updates an existing festival calendar entry.
        """
        FestivalCalendarRepository.ensure_table_exists()
        current = FestivalCalendarRepository.get_entry_by_id(calendar_id)
        if not current:
            raise ValueError(f"Festival calendar entry with ID {calendar_id} not found.")

        # Re-derive dates
        s_date_str = str(data.get("start_date", current["start_date"])).strip()
        e_date_str = str(data.get("end_date", current["end_date"])).strip()
        s_date = datetime.strptime(s_date_str, "%Y-%m-%d").date()

        if "planning_start_date" in data and data["planning_start_date"]:
            p_start_str = str(data["planning_start_date"]).strip()
            p_start = datetime.strptime(p_start_str, "%Y-%m-%d").date()
            p_days = (s_date - p_start).days
        elif "planning_window_days" in data:
            p_days = int(data["planning_window_days"])
            p_start_str = (s_date - timedelta(days=p_days)).strftime("%Y-%m-%d")
        else:
            p_days = current["planning_window_days"]
            p_start_str = current["planning_start_date"]

        year_val = int(data.get("year", s_date.year))
        is_sample = 1 if data.get("is_sample_date", current["is_sample_date"]) else 0
        is_verif = 1 if data.get("is_verified", current["is_verified"]) else 0

        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE festival_calendar
                SET festival_name = ?, festival_code = ?, region = ?,
                    start_date = ?, end_date = ?, category = ?,
                    planning_window_days = ?, planning_start_date = ?,
                    notes = ?, is_sample_date = ?, is_verified = ?,
                    year = ?, updated_at = CURRENT_TIMESTAMP
                WHERE calendar_id = ?
            """, (
                str(data.get("festival_name", current["festival_name"])).strip(),
                data.get("festival_code", current["festival_code"]),
                str(data.get("region", current["region"])).strip(),
                s_date_str,
                e_date_str,
                str(data.get("category", current["category"])).strip(),
                p_days,
                p_start_str,
                str(data.get("notes", current["notes"]) or "").strip(),
                is_sample,
                is_verif,
                year_val,
                calendar_id
            ))
            return cursor.rowcount > 0

    @staticmethod
    def delete_entry(calendar_id: int) -> bool:
        """Deletes a calendar festival entry."""
        FestivalCalendarRepository.ensure_table_exists()
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM festival_calendar WHERE calendar_id = ?", (calendar_id,))
            return cursor.rowcount > 0

    @staticmethod
    def get_entry_by_id(calendar_id: int) -> Optional[Dict[str, Any]]:
        """Retrieves a single calendar festival entry by ID."""
        FestivalCalendarRepository.ensure_table_exists()
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM festival_calendar WHERE calendar_id = ?", (calendar_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def get_all_entries(
        region: Optional[str] = None,
        year: Optional[int] = None,
        category: Optional[str] = None,
        is_verified: Optional[bool] = None,
        search: Optional[str] = None,
        include_pan_india: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Retrieves all festival calendar entries matching the specified filters.
        """
        FestivalCalendarRepository.ensure_table_exists()
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            sql = "SELECT * FROM festival_calendar WHERE 1=1"
            params: List[Any] = []

            if region and region.strip() and region.strip() != "All" and region.strip() != "All Regions":
                clean_region = region.strip()
                if include_pan_india and clean_region.lower() != "pan-india":
                    sql += " AND (LOWER(region) = LOWER(?) OR LOWER(region) = 'pan-india')"
                    params.append(clean_region)
                else:
                    sql += " AND LOWER(region) = LOWER(?)"
                    params.append(clean_region)

            if year:
                sql += " AND year = ?"
                params.append(int(year))

            if category and category.strip() and category.strip() != "All" and category.strip() != "All Categories":
                sql += " AND LOWER(category) = LOWER(?)"
                params.append(category.strip())

            if is_verified is not None:
                sql += " AND is_verified = ?"
                params.append(1 if is_verified else 0)

            if search and search.strip():
                term = f"%{search.strip()}%"
                sql += " AND (festival_name LIKE ? OR festival_code LIKE ? OR notes LIKE ? OR region LIKE ?)"
                params.extend([term, term, term, term])

            sql += " ORDER BY start_date ASC, planning_start_date ASC"
            cursor.execute(sql, tuple(params))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def verify_sample_date(calendar_id: int, is_verified: bool = True) -> bool:
        """
        Marks a festival's sample date as verified and confirmed by the user.
        """
        FestivalCalendarRepository.ensure_table_exists()
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE festival_calendar
                SET is_verified = ?, is_sample_date = ?, updated_at = CURRENT_TIMESTAMP
                WHERE calendar_id = ?
            """, (1 if is_verified else 0, 0 if is_verified else 1, calendar_id))
            return cursor.rowcount > 0

    @staticmethod
    def set_active_campaign(calendar_id: int) -> bool:
        """
        Sets a specific calendar festival as the active store campaign.
        """
        FestivalCalendarRepository.ensure_table_exists()
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE festival_calendar SET is_active_campaign = 0")
            cursor.execute("UPDATE festival_calendar SET is_active_campaign = 1 WHERE calendar_id = ?", (calendar_id,))
            return cursor.rowcount > 0

    @staticmethod
    def get_distinct_regions() -> List[str]:
        """Returns sorted list of all unique regions configured in the calendar."""
        FestivalCalendarRepository.ensure_table_exists()
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT region FROM festival_calendar WHERE region IS NOT NULL ORDER BY region ASC")
            return [row[0] for row in cursor.fetchall() if row[0]]
        finally:
            conn.close()

    @staticmethod
    def get_distinct_categories() -> List[str]:
        """Returns sorted list of all unique categories configured in the calendar."""
        FestivalCalendarRepository.ensure_table_exists()
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT category FROM festival_calendar WHERE category IS NOT NULL ORDER BY category ASC")
            return [row[0] for row in cursor.fetchall() if row[0]]
        finally:
            conn.close()

    @staticmethod
    def get_distinct_years() -> List[int]:
        """Returns sorted list of all unique years configured in the calendar."""
        FestivalCalendarRepository.ensure_table_exists()
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT year FROM festival_calendar ORDER BY year ASC")
            return [int(row[0]) for row in cursor.fetchall() if row[0]]
        finally:
            conn.close()
