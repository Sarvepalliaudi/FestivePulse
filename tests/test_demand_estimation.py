"""
FestivePulse — Demand Estimation Unit Test Suite
Comprehensive tests validating transparent, non-AI festival demand estimation:
- Duration-normalized YoY historical calculations (accounting for number of days in each period)
- Missing historical data handling ("Insufficient historical data" with 0 units, zero fabricated data)
- Manual planning estimate fallback (clearly labelled as user-defined assumption)
- Partial period normalization (scaling daily run-rates when historical duration != target duration)
- Unusual spike detection and optional trimming (identifying bulk institutional orders >= 50%)
- Forecast ledger isolation (ensuring actual sales tables are never written to)
- Non-AI, non-guaranteed uncertainty limitations
"""

import unittest
import math
from datetime import date, timedelta
from database.connection import init_db, db_session, get_db_connection
from services.demand_estimation_service import (
    estimate_product_demand,
    generate_demand_forecast_table,
    detect_sales_spike,
    get_festival_occurrence_details,
    STANDARD_UNCERTAINTY_LIMITATIONS
)


class TestFestivalDemandEstimation(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        """Creates clean, isolated database fixtures for demand estimation tests."""
        with db_session() as conn:
            cursor = conn.cursor()

            # Clean test fixtures
            cursor.execute("DELETE FROM sales_items WHERE invoice_id IN (SELECT invoice_id FROM sales_invoices WHERE invoice_number LIKE 'DEMAND-INV-%')")
            cursor.execute("DELETE FROM sales_invoices WHERE invoice_number LIKE 'DEMAND-INV-%'")
            cursor.execute("DELETE FROM festival_occurrences WHERE notes LIKE 'DEMAND_TEST_%'")
            cursor.execute("DELETE FROM festivals WHERE festival_code LIKE 'DEMAND_TEST_%'")
            cursor.execute("DELETE FROM products WHERE sku LIKE 'DEMAND-SKU-%'")
            cursor.execute("DELETE FROM product_categories WHERE category_name LIKE 'DEMAND_CAT_%'")

            # 1. Test Category (Default Surge: 2.0x)
            cursor.execute("""
                INSERT INTO product_categories (category_name, default_gst_rate, description)
                VALUES ('DEMAND_CAT_SWEETS', 5.0, 'Demand Test Sweets')
            """)
            self.cat_id = cursor.lastrowid

            # 2. Test Products
            # Product A: Has 2025 festival history
            cursor.execute("""
                INSERT INTO products (
                    sku, barcode, product_name, category_id, unit_of_measure,
                    cost_price, selling_price, mrp, gst_rate, min_safety_stock, reorder_quantity, is_active
                ) VALUES ('DEMAND-SKU-A', '890123456001', 'Demand Test Kaju Katli', ?, 'box', 300.0, 500.0, 550.0, 5.0, 10, 20, 1)
            """, (self.cat_id,))
            self.prod_a_id = cursor.lastrowid

            # Product B: Cold Start (Zero Sales History)
            cursor.execute("""
                INSERT INTO products (
                    sku, barcode, product_name, category_id, unit_of_measure,
                    cost_price, selling_price, mrp, gst_rate, min_safety_stock, reorder_quantity, is_active
                ) VALUES ('DEMAND-SKU-B', '890123456002', 'Demand Test New Peda', ?, 'box', 200.0, 350.0, 400.0, 5.0, 5, 10, 1)
            """, (self.cat_id,))
            self.prod_b_id = cursor.lastrowid

            # Product C: Has Bulk Spike in History
            cursor.execute("""
                INSERT INTO products (
                    sku, barcode, product_name, category_id, unit_of_measure,
                    cost_price, selling_price, mrp, gst_rate, min_safety_stock, reorder_quantity, is_active
                ) VALUES ('DEMAND-SKU-C', '890123456003', 'Demand Test Bulk Gift Box', ?, 'box', 400.0, 800.0, 850.0, 5.0, 10, 25, 1)
            """, (self.cat_id,))
            self.prod_c_id = cursor.lastrowid

            # 3. Test Festival Definition
            cursor.execute("""
                INSERT INTO festivals (festival_name, festival_code, primary_regions, typical_surge_multiplier)
                VALUES ('Demand Test Diwali', 'DEMAND_TEST_DIWALI', '["National"]', 2.0)
            """)
            self.fest_id = cursor.lastrowid

            # 4. Festival Occurrences:
            # 2025 Historical Occurrence: 10 days (2025-10-15 to 2025-10-24)
            cursor.execute("""
                INSERT INTO festival_occurrences (
                    festival_id, year, prep_start_date, campaign_start_date, campaign_end_date,
                    peak_start_date, festival_date, notes
                ) VALUES (?, 2025, '2025-10-01', '2025-10-15', '2025-10-24', '2025-10-20', '2025-10-24', 'DEMAND_TEST_2025')
            """, (self.fest_id,))
            self.occ_2025_id = cursor.lastrowid

            # 2026 Target Occurrence: 10 days (2026-10-25 to 2026-11-03)
            cursor.execute("""
                INSERT INTO festival_occurrences (
                    festival_id, year, prep_start_date, campaign_start_date, campaign_end_date,
                    peak_start_date, festival_date, notes
                ) VALUES (?, 2026, '2026-10-01', '2026-10-25', '2026-11-03', '2026-10-30', '2026-11-03', 'DEMAND_TEST_2026')
            """, (self.fest_id,))
            self.occ_2026_id = cursor.lastrowid

            # 2027 Partial Occurrence (e.g. 5 days, 2027-10-25 to 2027-10-29)
            cursor.execute("""
                INSERT INTO festival_occurrences (
                    festival_id, year, prep_start_date, campaign_start_date, campaign_end_date,
                    peak_start_date, festival_date, notes
                ) VALUES (?, 2027, '2027-10-01', '2027-10-25', '2027-10-29', '2027-10-27', '2027-10-29', 'DEMAND_TEST_2027_PARTIAL')
            """, (self.fest_id,))
            self.occ_2027_partial_id = cursor.lastrowid

            # 5. Populate Historical Sales for Product A in 2025 (100 units across 5 days)
            # Days: 2025-10-16 (20), 2025-10-17 (20), 2025-10-18 (20), 2025-10-19 (20), 2025-10-20 (20)
            for i in range(5):
                dt_str = f"2025-10-{16 + i:02d}"
                cursor.execute("""
                    INSERT INTO sales_invoices (
                        invoice_number, invoice_date, occurrence_id, payment_mode,
                        subtotal_amount, total_taxable_amount, net_total_amount, status
                    ) VALUES (?, ?, ?, 'CASH', 10000.0, 10000.0, 10500.0, 'COMPLETED')
                """, (f"DEMAND-INV-A-{i}", dt_str, self.occ_2025_id))
                inv_id = cursor.lastrowid

                cursor.execute("""
                    INSERT INTO sales_items (
                        invoice_id, product_id, quantity, unit_cost_price, unit_selling_price,
                        taxable_value, gst_rate, total_item_amount, gross_profit
                    ) VALUES (?, ?, 20, 300.0, 500.0, 10000.0, 5.0, 10500.0, 4000.0)
                """, (inv_id, self.prod_a_id))

            # 6. Populate Historical Sales for Product C with an Unusual Bulk Spike
            # Day 1: 100 units (Corporate order)
            # Day 2: 5 units
            # Day 3: 5 units
            # Day 4: 6 units
            # Day 5: 4 units
            # Total = 120 units, where Day 1 represents 83.3% of total
            spike_quantities = [100, 5, 5, 6, 4]
            for i, q in enumerate(spike_quantities):
                dt_str = f"2025-10-{16 + i:02d}"
                val = float(q * 800)
                cursor.execute("""
                    INSERT INTO sales_invoices (
                        invoice_number, invoice_date, occurrence_id, payment_mode,
                        subtotal_amount, total_taxable_amount, net_total_amount, status
                    ) VALUES (?, ?, ?, 'CASH', ?, ?, ?, 'COMPLETED')
                """, (f"DEMAND-INV-C-{i}", dt_str, self.occ_2025_id, val, val, val))
                inv_id = cursor.lastrowid

                cursor.execute("""
                    INSERT INTO sales_items (
                        invoice_id, product_id, quantity, unit_cost_price, unit_selling_price,
                        taxable_value, gst_rate, total_item_amount, gross_profit
                    ) VALUES (?, ?, ?, 400.0, 800.0, ?, 0.0, ?, ?)
                """, (inv_id, self.prod_c_id, q, val, val, float(q * 400)))

    def tearDown(self):
        """Cleans test fixtures."""
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM sales_items WHERE invoice_id IN (SELECT invoice_id FROM sales_invoices WHERE invoice_number LIKE 'DEMAND-INV-%')")
            cursor.execute("DELETE FROM sales_invoices WHERE invoice_number LIKE 'DEMAND-INV-%'")
            cursor.execute("DELETE FROM festival_occurrences WHERE notes LIKE 'DEMAND_TEST_%'")
            cursor.execute("DELETE FROM festivals WHERE festival_code LIKE 'DEMAND_TEST_%'")
            cursor.execute("DELETE FROM products WHERE sku LIKE 'DEMAND-SKU-%'")
            cursor.execute("DELETE FROM product_categories WHERE category_name LIKE 'DEMAND_CAT_%'")

    def test_empirical_festival_yoy_calculation(self):
        """
        Tests transparent calculation comparing daily sales across previous occurrences of the SAME festival.
        Historical: 100 units across 10-day campaign (2025) -> 10.0 units/day.
        Target: 10-day campaign (2026), growth factor = 1.15.
        Expected: Ceil(10.0 * 10 * 1.15) = 115 units.
        """
        est = estimate_product_demand(
            product_id=self.prod_a_id,
            target_occurrence_id=self.occ_2026_id,
            growth_multiplier=1.15,
            trim_spikes=False
        )

        self.assertEqual(est["status"], "EMPIRICAL_FESTIVAL_YOY")
        self.assertEqual(est["estimated_units"], 115)
        self.assertEqual(est["daily_run_rate"], 11.5)
        self.assertEqual(est["estimated_revenue"], 115 * 500.0)
        self.assertEqual(est["estimated_cost"], 115 * 300.0)

        # Verify historical sample size
        sample = est["historical_sample_size"]
        self.assertEqual(sample["total_units_sold"], 100)
        self.assertEqual(sample["transaction_count"], 5)
        self.assertEqual(sample["active_sales_days"], 5)
        self.assertEqual(sample["period_duration_days"], 10)
        self.assertEqual(sample["daily_sales_rate"], 10.0)

        # Verify baseline period details
        baseline = est["baseline_period"]
        self.assertEqual(baseline["type"], "PREVIOUS_FESTIVAL_OCCURRENCE")
        self.assertIn("Demand Test Diwali 2025", baseline["name"])
        self.assertEqual(baseline["duration_days"], 10)

        # Verify formula and calculation breakdown
        calc = est["calculation_details"]
        self.assertIn("Duration-Normalized Previous Festival Run-Rate", calc["formula_name"])
        self.assertIn("⌈(Historical Festival Units / Historical Duration Days)", calc["formula_latex"])
        self.assertIn("⌈(100 units ÷ 10 historical days) × 10 target days × 1.15 growth⌉", calc["arithmetic_breakdown"])

        # Guardrails: Non-AI and non-guaranteed
        self.assertFalse(est["is_guaranteed"])
        self.assertFalse(est["is_manual"])
        self.assertGreaterEqual(len(est["uncertainty_limitations"]), 3)

    def test_partial_periods_duration_normalization(self):
        """
        Tests that demand estimation explicitly accounts for differing period durations.
        Historical: 100 units over 10 days = 10.0 units/day.
        Target: Partial festival of 5 days (2026 partial occurrence), growth factor = 1.0.
        Expected: Ceil(10.0 units/day * 5 days * 1.0) = 50 units.
        """
        est = estimate_product_demand(
            product_id=self.prod_a_id,
            target_occurrence_id=self.occ_2027_partial_id,
            growth_multiplier=1.0,
            trim_spikes=False
        )

        self.assertEqual(est["status"], "EMPIRICAL_FESTIVAL_YOY")
        self.assertEqual(est["estimated_units"], 50)
        self.assertEqual(est["target_period"]["duration_days"], 5)
        self.assertEqual(est["baseline_period"]["duration_days"], 10)

        calc = est["calculation_details"]
        self.assertIsNotNone(calc["partial_period_note"])
        self.assertIn("10 days", calc["partial_period_note"])
        self.assertIn("5 days", calc["partial_period_note"])

    def test_insufficient_historical_data_zero_sales(self):
        """
        Tests that when a product has NO historical sales, the system:
        - Displays 'Insufficient historical data'
        - Projects 0 units (strictly no invented fake baseline or 0.5 default)
        - Reports sample size of 0
        """
        est = estimate_product_demand(
            product_id=self.prod_b_id,
            target_occurrence_id=self.occ_2026_id,
            growth_multiplier=1.10
        )

        self.assertEqual(est["status"], "INSUFFICIENT_HISTORICAL_DATA")
        self.assertIn("Insufficient historical data", est["status_label"])
        self.assertEqual(est["estimated_units"], 0)
        self.assertEqual(est["estimated_revenue"], 0.0)
        self.assertEqual(est["estimated_cost"], 0.0)

        # Historical sample size must be strictly 0
        sample = est["historical_sample_size"]
        self.assertEqual(sample["total_units_sold"], 0)
        self.assertEqual(sample["transaction_count"], 0)
        self.assertEqual(sample["active_sales_days"], 0)
        self.assertEqual(sample["period_duration_days"], 0)

        self.assertFalse(est["is_manual"])
        self.assertFalse(est["is_guaranteed"])

    def test_clearly_labelled_manual_planning_estimate(self):
        """
        Tests offering a clearly labelled manual planning estimate when history is insufficient.
        User inputs 8.0 units/day for cold-start SKU B over a 10-day target window.
        Expected: Ceil(8.0 * 10) = 80 units.
        """
        est = estimate_product_demand(
            product_id=self.prod_b_id,
            target_occurrence_id=self.occ_2026_id,
            manual_daily_estimate=8.0
        )

        self.assertEqual(est["status"], "MANUAL_PLANNING_ESTIMATE")
        self.assertTrue(est["is_manual"])
        self.assertIn("Manual Planning Estimate", est["status_label"])
        self.assertIn("User-Defined Assumption", est["status_label"])
        self.assertEqual(est["estimated_units"], 80)
        self.assertEqual(est["estimated_revenue"], 80 * 350.0)
        self.assertEqual(est["estimated_cost"], 80 * 200.0)

        calc = est["calculation_details"]
        self.assertIn("⌈8.0 units/day × 10 days⌉ = 80 units", calc["arithmetic_breakdown"])

    def test_unusual_spike_detection_and_normalization(self):
        """
        Tests detection and trimming of bulk institutional spikes.
        Product C has 120 units over 5 active days:
        Day 1: 100 units (83.3% of total period sales, institutional gift)
        Days 2-5: 5, 5, 6, 4 units (median = 5 units).
        """
        # Test detection helper directly
        sales_days = [
            {"date": "2025-10-16", "units": 100},
            {"date": "2025-10-17", "units": 5},
            {"date": "2025-10-18", "units": 5},
            {"date": "2025-10-19", "units": 6},
            {"date": "2025-10-20", "units": 4}
        ]
        has_spike, spike_desc, norm_units = detect_sales_spike(sales_days, total_units=120)
        self.assertTrue(has_spike)
        self.assertIn("83.3%", spike_desc)
        self.assertIn("institutional/corporate", spike_desc)
        # Normalized: (120 - 100) + 5 = 25 units
        self.assertEqual(norm_units, 25)

        # Test Case 1: Without trimming (default)
        est_raw = estimate_product_demand(
            product_id=self.prod_c_id,
            target_occurrence_id=self.occ_2026_id,
            growth_multiplier=1.0,
            trim_spikes=False
        )
        self.assertTrue(est_raw["calculation_details"]["spike_analysis"]["has_spike"])
        self.assertFalse(est_raw["calculation_details"]["spike_analysis"]["trimmed"])
        # Uses full 120 units over 10 days = 12.0 units/day -> 120 units
        self.assertEqual(est_raw["estimated_units"], 120)

        # Test Case 2: With trimming enabled
        est_trimmed = estimate_product_demand(
            product_id=self.prod_c_id,
            target_occurrence_id=self.occ_2026_id,
            growth_multiplier=1.0,
            trim_spikes=True
        )
        self.assertTrue(est_trimmed["calculation_details"]["spike_analysis"]["has_spike"])
        self.assertTrue(est_trimmed["calculation_details"]["spike_analysis"]["trimmed"])
        # Uses normalized 25 units over 10 historical days = 2.5 units/day -> Ceil(2.5 * 10) = 25 units
        self.assertEqual(est_trimmed["estimated_units"], 25)

    def test_forecast_does_not_modify_actual_sales_tables(self):
        """
        Tests that running demand forecasts strictly separates forecasts from actual sales,
        and never inserts, modifies, or deletes records in sales ledgers.
        """
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) AS c FROM sales_invoices")
            inv_before = cursor.fetchone()["c"]

            cursor.execute("SELECT COUNT(*) AS c FROM sales_items")
            items_before = cursor.fetchone()["c"]

            cursor.execute("SELECT COUNT(*) AS c FROM inventory_batches")
            batches_before = cursor.fetchone()["c"]
        finally:
            conn.close()

        # Run demand estimation table generation and individual estimates
        df = generate_demand_forecast_table(
            target_occurrence_id=self.occ_2026_id,
            category_id=self.cat_id,
            growth_multiplier=1.20,
            manual_overrides={self.prod_b_id: 10.0}
        )
        self.assertFalse(df.empty)

        # Verify counts in sales and inventory tables are identical (zero writes)
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) AS c FROM sales_invoices")
            self.assertEqual(cursor.fetchone()["c"], inv_before)

            cursor.execute("SELECT COUNT(*) AS c FROM sales_items")
            self.assertEqual(cursor.fetchone()["c"], items_before)

            cursor.execute("SELECT COUNT(*) AS c FROM inventory_batches")
            self.assertEqual(cursor.fetchone()["c"], batches_before)
        finally:
            conn.close()

    def test_uncertainty_limitations_and_non_guaranteed_disclaimers(self):
        """
        Tests that estimates never claim guaranteed outcomes and contain clear uncertainty limitations.
        """
        est = estimate_product_demand(
            product_id=self.prod_a_id,
            target_occurrence_id=self.occ_2026_id
        )

        self.assertFalse(est["is_guaranteed"])
        for limitation in STANDARD_UNCERTAINTY_LIMITATIONS:
            self.assertIn(limitation, est["uncertainty_limitations"])

    def test_recent_baseline_with_category_surge(self):
        """
        Tests estimation when a product has NO same-festival history, but has regular
        non-festival sales in the past 60 days.
        """
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO products (
                    sku, barcode, product_name, category_id, unit_of_measure,
                    cost_price, selling_price, mrp, gst_rate, min_safety_stock, reorder_quantity, is_active
                ) VALUES ('DEMAND-SKU-D', '890123456004', 'Demand Test Regular Sweet', ?, 'box', 150.0, 250.0, 280.0, 5.0, 10, 20, 1)
            """, (self.cat_id,))
            prod_d_id = cursor.lastrowid

            # Create regular non-festival sales within last 60 days (60 units sold)
            cursor.execute("""
                INSERT INTO sales_invoices (
                    invoice_number, invoice_date, occurrence_id, payment_mode,
                    subtotal_amount, total_taxable_amount, net_total_amount, status
                ) VALUES ('DEMAND-INV-D-0', DATE('now', '-10 days'), NULL, 'CASH', 15000.0, 15000.0, 15750.0, 'COMPLETED')
            """)
            inv_id = cursor.lastrowid

            cursor.execute("""
                INSERT INTO sales_items (
                    invoice_id, product_id, quantity, unit_cost_price, unit_selling_price,
                    taxable_value, gst_rate, total_item_amount, gross_profit
                ) VALUES (?, ?, 60, 150.0, 250.0, 15000.0, 5.0, 15750.0, 6000.0)
            """, (inv_id, prod_d_id))

        try:
            # Category surge is 2.0x, target days = 10, growth = 1.0
            # Daily baseline = 60 / 60.0 = 1.0 unit/day
            # Expected = Ceil(1.0 * 2.0 * 10 * 1.0) = 20 units
            est = estimate_product_demand(
                product_id=prod_d_id,
                target_occurrence_id=self.occ_2026_id,
                growth_multiplier=1.0
            )

            self.assertEqual(est["status"], "EMPIRICAL_RECENT_BASELINE")
            self.assertEqual(est["estimated_units"], 20)
            self.assertEqual(est["historical_sample_size"]["total_units_sold"], 60)
            self.assertEqual(est["historical_sample_size"]["period_duration_days"], 60)
            self.assertEqual(est["historical_sample_size"]["daily_sales_rate"], 1.0)
            self.assertIn("Off-Season Baseline Run-Rate with Category Surge", est["calculation_details"]["formula_name"])
            self.assertEqual(est["calculation_details"]["applied_surge_multiplier"], 2.0)
        finally:
            with db_session() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM sales_items WHERE invoice_id IN (SELECT invoice_id FROM sales_invoices WHERE invoice_number = 'DEMAND-INV-D-0')")
                cursor.execute("DELETE FROM sales_invoices WHERE invoice_number = 'DEMAND-INV-D-0'")
                cursor.execute("DELETE FROM products WHERE product_id = ?", (prod_d_id,))


if __name__ == "__main__":
    unittest.main()
