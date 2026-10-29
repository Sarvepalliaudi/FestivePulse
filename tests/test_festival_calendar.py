"""
FestivePulse — Festival Calendar Unit Tests
Tests date boundaries, multi-region and multi-year support, overlapping planning periods,
editable sample entries (Diwali, Christmas, Pongal, Onam, Bakrid, Eid al-Fitr, Durga Puja, Ganesh Chaturthi),
verification workflows, and the 200-year astronomical Indian calendar engine.
"""

import unittest
from datetime import date, timedelta
from database.connection import init_db, db_session, get_db_connection
from repositories.festival_calendar_repository import (
    FestivalCalendarRepository,
    SAMPLE_FESTIVAL_ENTRIES
)
from services.festival_calendar_service import (
    parse_iso_date,
    validate_festival_dates,
    validate_festival_data,
    filter_festivals_by_region,
    get_upcoming_festivals,
    detect_overlapping_festivals,
    create_calendar_festival,
    update_calendar_festival,
    delete_calendar_festival,
    verify_festival_sample_dates,
    get_calendar_festival_by_id,
    get_calendar_festivals,
    get_calendar_summary_metrics
)
from services.indian_calendar_engine import (
    get_year_moon_phases,
    hijri_to_gregorian,
    gregorian_to_hijri,
    compute_easter,
    generate_all_indian_festivals_for_year,
    generate_festivals_for_range
)


class TestFestivalCalendar(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db()
        FestivalCalendarRepository.ensure_table_exists()
        FestivalCalendarRepository.seed_sample_festivals(force=True)

    def setUp(self):
        # Clean test entries that start with TEST_
        with db_session() as conn:
            conn.execute("DELETE FROM festival_calendar WHERE festival_name LIKE 'TEST_%'")

    def tearDown(self):
        with db_session() as conn:
            conn.execute("DELETE FROM festival_calendar WHERE festival_name LIKE 'TEST_%'")

    # -------------------------------------------------------------------------
    # 1. DATE BOUNDARIES & VALIDATION TESTS
    # -------------------------------------------------------------------------
    def test_date_boundary_start_after_end_raises_error(self):
        """Festival start date cannot be after end date."""
        with self.assertRaises(ValueError) as ctx:
            validate_festival_dates("2026-11-15", "2026-11-10")
        self.assertIn("cannot be after end date", str(ctx.exception))

    def test_date_boundary_planning_start_after_festival_start_raises_error(self):
        """Planning start date cannot be after festival start date."""
        with self.assertRaises(ValueError) as ctx:
            validate_festival_dates("2026-11-10", "2026-11-15", planning_start_date="2026-11-12")
        self.assertIn("cannot be after festival start date", str(ctx.exception))

    def test_date_boundary_negative_planning_window_raises_error(self):
        """Planning window days cannot be negative."""
        with self.assertRaises(ValueError) as ctx:
            validate_festival_dates("2026-11-10", "2026-11-15", planning_window_days=-5)
        self.assertIn("cannot be negative", str(ctx.exception))

    def test_date_boundary_single_day_festival_valid(self):
        """A single-day festival (start == end) is perfectly valid."""
        res = validate_festival_dates("2026-08-15", "2026-08-15", planning_window_days=10)
        self.assertEqual(res["start_date"], "2026-08-15")
        self.assertEqual(res["end_date"], "2026-08-15")
        self.assertEqual(res["celebration_days"], 1)
        self.assertEqual(res["planning_start_date"], "2026-08-05")
        self.assertEqual(res["planning_window_days"], 10)

    def test_validate_festival_data_mandatory_fields(self):
        """Name, region, and category must not be empty."""
        with self.assertRaises(ValueError) as ctx:
            validate_festival_data({
                "festival_name": "",
                "region": "North",
                "category": "Major Religious",
                "start_date": "2026-10-01",
                "end_date": "2026-10-02"
            })
        self.assertIn("Festival name is required", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            validate_festival_data({
                "festival_name": "TEST_Diwali",
                "region": "  ",
                "category": "Major Religious",
                "start_date": "2026-10-01",
                "end_date": "2026-10-02"
            })
        self.assertIn("Region is required", str(ctx.exception))

        with self.assertRaises(ValueError) as ctx:
            validate_festival_data({
                "festival_name": "TEST_Diwali",
                "region": "North",
                "category": "",
                "start_date": "2026-10-01",
                "end_date": "2026-10-02"
            })
        self.assertIn("Festival category is required", str(ctx.exception))

    def test_parse_iso_date_invalid(self):
        """Invalid date strings raise ValueError."""
        with self.assertRaises(ValueError):
            parse_iso_date("invalid-date")
        with self.assertRaises(ValueError):
            parse_iso_date("")

    # -------------------------------------------------------------------------
    # 2. REQUIRED 8 SAMPLE FESTIVALS TESTS
    # -------------------------------------------------------------------------
    def test_all_8_required_festivals_exist_in_samples(self):
        """
        Verify all 8 user-mandated sample festivals exist:
        Diwali, Christmas, Pongal, Onam, Bakrid/Eid al-Adha, Eid al-Fitr, Durga Puja, Ganesh Chaturthi.
        """
        all_entries = FestivalCalendarRepository.get_all_entries()
        names = [f["festival_name"] for f in all_entries]

        required_festivals = [
            "Diwali",
            "Christmas",
            "Pongal",
            "Onam",
            "Bakrid",
            "Eid al-Fitr",
            "Durga Puja",
            "Ganesh Chaturthi"
        ]

        for req in required_festivals:
            found = any(req.lower() in name.lower() for name in names)
            self.assertTrue(found, f"Required sample festival '{req}' not found in calendar entries: {names}")

    def test_sample_dates_are_initially_unverified_and_editable(self):
        """
        Sample entries must be marked with is_sample_date=1, is_verified=0,
        and allow users to verify or edit them.
        """
        all_entries = FestivalCalendarRepository.get_all_entries()
        diwali_entry = next(f for f in all_entries if "diwali" in f["festival_name"].lower())

        # Must be marked as sample and unverified initially
        self.assertEqual(diwali_entry["is_sample_date"], 1)
        self.assertEqual(diwali_entry["is_verified"], 0)

        # 1-click verify workflow
        cal_id = diwali_entry["calendar_id"]
        success = verify_festival_sample_dates(cal_id, is_verified=True)
        self.assertTrue(success)

        updated = get_calendar_festival_by_id(cal_id)
        self.assertEqual(updated["is_verified"], 1)
        self.assertEqual(updated["is_sample_date"], 0)

        # Edit dates and planning window
        edit_success = update_calendar_festival(cal_id, {
            "festival_name": "Diwali & Dhanteras (Verified)",
            "region": "Pan-India",
            "category": "Major Religious",
            "start_date": "2026-11-09",
            "end_date": "2026-11-13",
            "planning_window_days": 40,
            "notes": "Verified local calendar date with 40-day advance inventory staging.",
            "is_verified": 1,
            "is_sample_date": 0
        })
        self.assertTrue(edit_success)

        reloaded = get_calendar_festival_by_id(cal_id)
        self.assertEqual(reloaded["start_date"], "2026-11-09")
        self.assertEqual(reloaded["end_date"], "2026-11-13")
        self.assertEqual(reloaded["planning_window_days"], 40)
        self.assertEqual(reloaded["planning_start_date"], "2026-09-30")

    # -------------------------------------------------------------------------
    # 3. MULTI-REGION & MULTI-YEAR FLEXIBILITY TESTS
    # -------------------------------------------------------------------------
    def test_no_single_date_assumed_multiple_regional_dates_for_same_festival(self):
        """
        Users can configure different dates for the same festival in different regions
        (e.g. Diwali celebration in North vs Tamil Deepavali in South).
        """
        id1 = create_calendar_festival({
            "festival_name": "TEST_Deepavali South",
            "region": "South",
            "category": "Major Religious",
            "start_date": "2026-11-07",
            "end_date": "2026-11-08",
            "planning_window_days": 20,
            "notes": "Tamil Nadu & Karnataka Deepavali morning ritual",
            "year": 2026
        })

        id2 = create_calendar_festival({
            "festival_name": "TEST_Diwali North",
            "region": "North",
            "category": "Major Religious",
            "start_date": "2026-11-08",
            "end_date": "2026-11-10",
            "planning_window_days": 30,
            "notes": "North Indian Lakshmi Puja & Govardhan Puja",
            "year": 2026
        })

        self.assertIsNotNone(id1)
        self.assertIsNotNone(id2)
        self.assertNotEqual(id1, id2)

        south_fest = get_calendar_festival_by_id(id1)
        north_fest = get_calendar_festival_by_id(id2)
        self.assertEqual(south_fest["start_date"], "2026-11-07")
        self.assertEqual(north_fest["start_date"], "2026-11-08")

    def test_regional_filtering(self):
        """
        Regional filters return festivals for that region plus Pan-India (when requested),
        or purely regional when include_pan_india is False.
        """
        test_festivals = [
            {"festival_name": "TEST_North Fest", "region": "North"},
            {"festival_name": "TEST_South Fest", "region": "South"},
            {"festival_name": "TEST_Pan Fest", "region": "Pan-India"}
        ]

        filtered_south = filter_festivals_by_region(test_festivals, "South", include_pan_india=True)
        names_south = [f["festival_name"] for f in filtered_south]
        self.assertIn("TEST_South Fest", names_south)
        self.assertIn("TEST_Pan Fest", names_south)
        self.assertNotIn("TEST_North Fest", names_south)

        filtered_south_only = filter_festivals_by_region(test_festivals, "South", include_pan_india=False)
        names_south_only = [f["festival_name"] for f in filtered_south_only]
        self.assertIn("TEST_South Fest", names_south_only)
        self.assertNotIn("TEST_Pan Fest", names_south_only)

    # -------------------------------------------------------------------------
    # 4. OVERLAPPING PLANNING PERIODS TESTS
    # -------------------------------------------------------------------------
    def test_overlapping_planning_periods_detected(self):
        """
        Detects overlapping pre-festival planning windows between festivals.
        Example: Fest A planning (Aug 1 to Aug 25) overlaps with Fest B planning (Aug 15 to Sept 10).
        """
        fest_a = {
            "calendar_id": 991,
            "festival_name": "TEST_Ganesh Chaturthi",
            "region": "West",
            "start_date": "2026-09-01",
            "end_date": "2026-09-10",
            "planning_start_date": "2026-08-10",
            "planning_window_days": 22
        }

        fest_b = {
            "calendar_id": 992,
            "festival_name": "TEST_Onam",
            "region": "South",
            "start_date": "2026-08-25",
            "end_date": "2026-08-28",
            "planning_start_date": "2026-08-01",
            "planning_window_days": 24
        }

        overlaps = detect_overlapping_festivals(festivals=[fest_a, fest_b])
        self.assertEqual(len(overlaps), 1)
        ov = overlaps[0]
        self.assertEqual(ov["festival_a_name"], "TEST_Ganesh Chaturthi")
        self.assertEqual(ov["festival_b_name"], "TEST_Onam")
        self.assertGreater(ov["overlap_days"], 0)
        self.assertTrue(ov["overlap_start_date"] <= ov["overlap_end_date"])

    def test_non_overlapping_festivals_have_zero_overlaps(self):
        """Festivals with disjoint campaign windows have zero overlaps."""
        fest_jan = {
            "calendar_id": 993,
            "festival_name": "TEST_Pongal",
            "region": "South",
            "start_date": "2026-01-14",
            "end_date": "2026-01-17",
            "planning_start_date": "2025-12-25",
            "planning_window_days": 20
        }
        fest_nov = {
            "calendar_id": 994,
            "festival_name": "TEST_Diwali",
            "region": "North",
            "start_date": "2026-11-08",
            "end_date": "2026-11-12",
            "planning_start_date": "2026-10-05",
            "planning_window_days": 34
        }
        overlaps = detect_overlapping_festivals(festivals=[fest_jan, fest_nov])
        self.assertEqual(len(overlaps), 0)

    # -------------------------------------------------------------------------
    # 5. UPCOMING FESTIVALS VIEW & COUNTDOWN TESTS
    # -------------------------------------------------------------------------
    def test_upcoming_festivals_phase_calculation(self):
        """
        Validates phase detection (PRE_PLANNING, IN_PLANNING_WINDOW, ACTIVE_CELEBRATION)
        and countdown days relative to reference date.
        """
        # Scenario: Reference date is 2026-10-15
        ref_d = date(2026, 10, 15)

        # Create festival with planning starting 2026-10-01, celebration 2026-11-01 to 2026-11-05
        f_id = create_calendar_festival({
            "festival_name": "TEST_Upcoming Diwali",
            "region": "Pan-India",
            "category": "Major Religious",
            "start_date": "2026-11-01",
            "end_date": "2026-11-05",
            "planning_window_days": 31,
            "notes": "Test upcoming phase",
            "year": 2026
        })

        upcoming = get_upcoming_festivals(reference_date=ref_d)
        test_item = next((f for f in upcoming if f["festival_name"] == "TEST_Upcoming Diwali"), None)
        self.assertIsNotNone(test_item)

        # On 2026-10-15, it should be IN_PLANNING_WINDOW (planning started Oct 1, celebration is Nov 1)
        self.assertEqual(test_item["phase"], "IN_PLANNING_WINDOW")
        self.assertEqual(test_item["days_until_festival"], 17)

    # -------------------------------------------------------------------------
    # 6. 200-YEAR INDIAN CALENDAR ENGINE TESTS
    # -------------------------------------------------------------------------
    def test_engine_astronomical_moon_phases(self):
        """Verifies calculation of New Moons and Full Moons over centuries."""
        for yr in [2026, 2050, 2126, 2226]:
            new_moons, full_moons = get_year_moon_phases(yr)
            self.assertTrue(12 <= len(new_moons) <= 13)
            self.assertTrue(12 <= len(full_moons) <= 13)

    def test_engine_hijri_islamic_calendar(self):
        """Verifies Tabular Islamic Hijri algorithm across 200 years."""
        # 1447 AH Eid al-Fitr (1st Shawwal) should be in early 2026
        g_eid = hijri_to_gregorian(1447, 10, 1)
        self.assertEqual(g_eid.year, 2026)
        self.assertEqual(g_eid.month, 3)

        # 200 years in future (e.g. 2226 CE)
        h_yr, h_m, h_d = gregorian_to_hijri(date(2226, 5, 1))
        self.assertGreater(h_yr, 1650)
        self.assertTrue(1 <= h_m <= 12)
        self.assertTrue(1 <= h_d <= 30)

    def test_engine_easter_computus(self):
        """Verifies Easter calculation."""
        # 2026 Easter Sunday is April 5, 2026
        easter_2026 = compute_easter(2026)
        self.assertEqual(easter_2026, date(2026, 4, 5))

    def test_engine_generates_25_plus_festivals_for_any_year_up_to_200_years(self):
        """Generates 25+ major Indian festivals for future years."""
        for yr in [2027, 2075, 2150, 2226]:
            fests = generate_all_indian_festivals_for_year(yr)
            self.assertGreaterEqual(len(fests), 25)

            # Check that major festivals are all present
            names = [f["festival_name"] for f in fests]
            self.assertTrue(any("diwali" in n.lower() for n in names))
            self.assertTrue(any("eid" in n.lower() for n in names))
            self.assertTrue(any("christmas" in n.lower() for n in names))
            self.assertTrue(any("pongal" in n.lower() for n in names))
            self.assertTrue(any("onam" in n.lower() for n in names))
            self.assertTrue(any("ganesh" in n.lower() for n in names))
            self.assertTrue(any("durga" in n.lower() for n in names))

            # All start_dates must be valid ISO in that year
            for f in fests:
                s_d = parse_iso_date(f["start_date"])
                e_d = parse_iso_date(f["end_date"])
                self.assertEqual(s_d.year, yr)
                self.assertTrue(s_d <= e_d)
                self.assertEqual(f["is_sample_date"], 1)
                self.assertEqual(f["is_verified"], 0)


if __name__ == "__main__":
    unittest.main()
