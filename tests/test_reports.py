"""
FestivePulse — Comprehensive Analytics & Audit Reporting Engine Test Suite
Tests cover:
- CSV & PDF generation for all 6 core report categories:
  1. Sales Summary & Tax Ledger
  2. Inventory Valuation & Stock Health
  3. Stock Movement Audit Ledger
  4. Festival Campaign Comparisons
  5. Operating Expense Summary
  6. Forecast-Based Stock Procurement Plan
- Application of date, region, product, category, and status filters
- Inclusion of report generation timestamp, currency INR, and calculation definitions
- Unambiguous distinction between ACTUAL RESULTS and ESTIMATES/PROJECTIONS
- Valid binary PDF structure (%PDF- header and %%EOF trailer)
- Valid CSV structure with metadata comment header and parsable tabular body
- Graceful handling of empty reports
- Safe Unicode and INR currency string handling
"""

import unittest
import io
import csv
import os
from datetime import datetime, date, timedelta
import pandas as pd

from database.connection import init_db, db_session, get_db_connection
from services.reports_service import (
    get_sales_summary_data,
    get_inventory_report_data,
    get_stock_movements_data,
    get_festival_comparisons_data,
    get_expense_summary_data,
    get_forecast_stock_plan_data,
    generate_report_csv,
    generate_report_pdf
)


class TestReportsEngine(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        """Sets up isolated fixtures for reporting tests."""
        with db_session() as conn:
            cursor = conn.cursor()

            # Clean previous test fixtures
            cursor.execute("DELETE FROM expense_audit_logs WHERE expense_id IN (SELECT expense_id FROM expenses WHERE vendor_name LIKE 'REP-TEST-%')")
            cursor.execute("DELETE FROM expenses WHERE vendor_name LIKE 'REP-TEST-%'")
            cursor.execute("DELETE FROM sales_returns WHERE return_number LIKE 'REP-RET-%'")
            cursor.execute("DELETE FROM sales_items WHERE invoice_id IN (SELECT invoice_id FROM sales_invoices WHERE invoice_number LIKE 'REP-INV-%')")
            cursor.execute("DELETE FROM sales_invoices WHERE invoice_number LIKE 'REP-INV-%'")
            cursor.execute("DELETE FROM stock_movements WHERE reason LIKE 'REP_TEST_%'")
            cursor.execute("DELETE FROM inventory_batches WHERE batch_number LIKE 'REP-BAT-%'")
            cursor.execute("DELETE FROM festival_occurrences WHERE notes LIKE 'REP_TEST_%'")
            cursor.execute("DELETE FROM festivals WHERE festival_code LIKE 'REP_TEST_%'")
            cursor.execute("DELETE FROM products WHERE sku LIKE 'REP-SKU-%'")
            cursor.execute("DELETE FROM product_categories WHERE category_name LIKE 'REP_CAT_%'")

            # 1. Product Category
            cursor.execute("""
                INSERT INTO product_categories (category_name, default_gst_rate, description)
                VALUES ('REP_CAT_SWEETS', 5.0, 'Reporting Test Sweets Category')
            """)
            self.cat_id = cursor.lastrowid

            # 2. Products
            cursor.execute("""
                INSERT INTO products (
                    sku, product_name, category_id, unit_of_measure,
                    cost_price, selling_price, mrp, gst_rate, min_safety_stock,
                    reorder_quantity, is_perishable, shelf_life_days, region_tags, is_active
                ) VALUES (
                    'REP-SKU-001', 'Reporting Test Kaju Katli', ?, 'kg',
                    400.0, 600.0, 650.0, 5.0, 10, 20, 1, 15, 'North India,Maharashtra', 1
                )
            """, (self.cat_id,))
            self.prod1_id = cursor.lastrowid

            cursor.execute("""
                INSERT INTO products (
                    sku, product_name, category_id, unit_of_measure,
                    cost_price, selling_price, mrp, gst_rate, min_safety_stock,
                    reorder_quantity, is_perishable, shelf_life_days, region_tags, is_active
                ) VALUES (
                    'REP-SKU-002', 'Reporting Test Brass Diya', ?, 'pcs',
                    50.0, 120.0, 150.0, 12.0, 5, 25, 0, NULL, 'Pan-India', 1
                )
            """, (self.cat_id,))
            self.prod2_id = cursor.lastrowid

            # 3. Batches
            cursor.execute("""
                INSERT INTO inventory_batches (
                    product_id, batch_number, quantity_received, quantity_available,
                    unit_cost, received_date, expiry_date
                ) VALUES (
                    ?, 'REP-BAT-001', 50, 5, 400.0, '2026-10-01', '2026-11-01'
                )
            """, (self.prod1_id,))
            self.batch1_id = cursor.lastrowid

            cursor.execute("""
                INSERT INTO inventory_batches (
                    product_id, batch_number, quantity_received, quantity_available,
                    unit_cost, received_date, expiry_date
                ) VALUES (
                    ?, 'REP-BAT-002', 100, 80, 50.0, '2026-10-01', NULL
                )
            """, (self.prod2_id,))
            self.batch2_id = cursor.lastrowid

            # 4. Festival & Occurrence
            cursor.execute("""
                INSERT INTO festivals (festival_code, festival_name, primary_regions, typical_surge_multiplier)
                VALUES ('REP_TEST_DIWALI', 'Reporting Test Diwali', 'Pan-India', 2.5)
            """)
            self.fest_id = cursor.lastrowid

            cursor.execute("""
                INSERT INTO festival_occurrences (
                    festival_id, year, prep_start_date, campaign_start_date, peak_start_date, festival_date, campaign_end_date, notes
                ) VALUES (
                    ?, 2026, '2026-10-01', '2026-10-15', '2026-10-20', '2026-10-25', '2026-10-31', 'REP_TEST_DIWALI_OCC'
                )
            """, (self.fest_id,))
            self.occ_id = cursor.lastrowid

            # 5. Sales Invoice
            cursor.execute("""
                INSERT INTO sales_invoices (
                    invoice_number, customer_id, occurrence_id, invoice_date,
                    subtotal_amount, discount_amount, total_taxable_amount,
                    cgst_amount, sgst_amount, igst_amount, roundoff_amount,
                    net_total_amount, payment_mode, status, notes
                ) VALUES (
                    'REP-INV-001', NULL, ?, '2026-10-20',
                    6000.0, 0.0, 6000.0,
                    150.0, 150.0, 0.0, 0.0,
                    6300.0, 'CASH', 'COMPLETED', 'REP_TEST_INVOICE'
                )
            """, (self.occ_id,))
            self.inv_id = cursor.lastrowid

            cursor.execute("""
                INSERT INTO sales_items (
                    invoice_id, product_id, batch_id, quantity,
                    unit_selling_price, unit_cost_price, discount_percent,
                    taxable_value, gst_rate, cgst_rate, cgst_amount,
                    sgst_rate, sgst_amount, igst_rate, igst_amount,
                    total_item_amount, gross_profit
                ) VALUES (
                    ?, ?, ?, 10,
                    600.0, 400.0, 0.0,
                    6000.0, 5.0, 2.5, 150.0,
                    2.5, 150.0, 0.0, 0.0,
                    6300.0, 2000.0
                )
            """, (self.inv_id, self.prod1_id, self.batch1_id))

            # 6. Stock Movements
            cursor.execute("""
                INSERT INTO stock_movements (
                    product_id, batch_id, movement_type, quantity,
                    unit_cost, total_cost_impact, reference_type, reference_id, reason
                ) VALUES (
                    ?, ?, 'RECEIPT', 50, 400.0, 20000.0, 'PURCHASE_RECEIPT', 'REP-PO-001', 'REP_TEST_PURCHASE'
                )
            """, (self.prod1_id, self.batch1_id))

            cursor.execute("""
                INSERT INTO stock_movements (
                    product_id, batch_id, movement_type, quantity,
                    unit_cost, total_cost_impact, reference_type, reference_id, reason
                ) VALUES (
                    ?, ?, 'SALE', -10, 400.0, 4000.0, 'SALES_INVOICE', 'REP-INV-001', 'REP_TEST_SALE'
                )
            """, (self.prod1_id, self.batch1_id))

            # 7. Expense Record
            cursor.execute("""
                INSERT INTO expenses (
                    expense_date, expense_category, amount, description, occurrence_id,
                    vendor_name, payment_mode, status
                ) VALUES (
                    '2026-10-20', 'MARKETING', 1500.0, 'REP_TEST Promotional Flyers', ?,
                    'REP-TEST-PRINTERS', 'UPI', 'ACTIVE'
                )
            """, (self.occ_id,))
            self.exp_id = cursor.lastrowid

    def tearDown(self):
        """Cleans up all reporting test fixtures."""
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM expense_audit_logs WHERE expense_id IN (SELECT expense_id FROM expenses WHERE vendor_name LIKE 'REP-TEST-%')")
            cursor.execute("DELETE FROM expenses WHERE vendor_name LIKE 'REP-TEST-%'")
            cursor.execute("DELETE FROM sales_returns WHERE return_number LIKE 'REP-RET-%'")
            cursor.execute("DELETE FROM sales_items WHERE invoice_id IN (SELECT invoice_id FROM sales_invoices WHERE invoice_number LIKE 'REP-INV-%')")
            cursor.execute("DELETE FROM sales_invoices WHERE invoice_number LIKE 'REP-INV-%'")
            cursor.execute("DELETE FROM stock_movements WHERE reason LIKE 'REP_TEST_%'")
            cursor.execute("DELETE FROM inventory_batches WHERE batch_number LIKE 'REP-BAT-%'")
            cursor.execute("DELETE FROM festival_occurrences WHERE notes LIKE 'REP_TEST_%'")
            cursor.execute("DELETE FROM festivals WHERE festival_code LIKE 'REP_TEST_%'")
            cursor.execute("DELETE FROM products WHERE sku LIKE 'REP-SKU-%'")
            cursor.execute("DELETE FROM product_categories WHERE category_name LIKE 'REP_CAT_%'")

    # ==========================================================================
    # 1. SALES SUMMARY REPORT TESTS
    # ==========================================================================
    def test_sales_summary_report_and_filters(self):
        """Verifies sales summary data extraction, filtering, CSV and PDF generation."""
        # Unfiltered / broad
        df, meta = get_sales_summary_data()
        self.assertFalse(df.empty)
        self.assertIn("invoice_number", df.columns)
        self.assertIn("gross_profit", df.columns)
        self.assertIn("ACTUAL", meta["classification"])
        self.assertEqual(meta["currency"], "INR")
        self.assertIn("Gross Profit", meta["calculation_definitions"])

        # Filter by specific product
        df_prod, meta_prod = get_sales_summary_data(product_id=self.prod1_id)
        self.assertFalse(df_prod.empty)
        self.assertTrue((df_prod["product_id"] == self.prod1_id).all())
        self.assertEqual(df_prod.iloc[0]["invoice_number"], "REP-INV-001")
        self.assertEqual(df_prod.iloc[0]["gross_profit"], 2000.0)  # (600 - 400) * 10

        # Filter by non-matching date range
        df_none, _ = get_sales_summary_data(start_date="2099-01-01", end_date="2099-01-31")
        self.assertTrue(df_none.empty)

        # Generate and verify CSV
        csv_text = generate_report_csv(df_prod, meta_prod)
        self.assertIn("# Report Title: Sales Summary", csv_text)
        self.assertIn("# DATA CLASSIFICATION: ACTUAL", csv_text)
        self.assertIn("# Currency: INR", csv_text)
        self.assertIn("REP-INV-001", csv_text)
        self.assertIn("Reporting Test Kaju Katli", csv_text)

        # Parse CSV to confirm valid syntax
        reader = list(csv.reader(io.StringIO(csv_text)))
        self.assertGreater(len(reader), 10)

        # Generate and verify PDF
        pdf_bytes = generate_report_pdf(df_prod, meta_prod, orientation="landscape")
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))
        self.assertIn(b"%%EOF", pdf_bytes[-120:])
        self.assertGreater(len(pdf_bytes), 2000)

    # ==========================================================================
    # 2. INVENTORY VALUATION REPORT TESTS
    # ==========================================================================
    def test_inventory_valuation_report_and_low_stock_filter(self):
        """Verifies inventory valuation calculation and low stock filtering."""
        df_all, meta_all = get_inventory_report_data(category_id=self.cat_id)
        self.assertEqual(len(df_all), 2)  # prod1 and prod2
        self.assertIn("ACTUAL", meta_all["classification"])
        self.assertIn("Cost Valuation (Asset)", meta_all["calculation_definitions"])

        # Check status derivation: Prod 1 has 5 units <= min 10 => LOW STOCK
        # Prod 2 has 80 units > min 5 => HEALTHY
        prod1_row = df_all[df_all["product_id"] == self.prod1_id].iloc[0]
        self.assertEqual(prod1_row["status"], "LOW STOCK")
        self.assertEqual(prod1_row["total_cost_valuation"], 5 * 400.0)

        # Filter low stock only
        df_low, meta_low = get_inventory_report_data(category_id=self.cat_id, low_stock_only=True)
        self.assertEqual(len(df_low), 1)
        self.assertEqual(df_low.iloc[0]["product_id"], self.prod1_id)

        # Verify CSV & PDF
        csv_text = generate_report_csv(df_low, meta_low)
        self.assertIn("Inventory Valuation & Stock Status Report", csv_text)
        self.assertIn("REP-SKU-001", csv_text)

        pdf_bytes = generate_report_pdf(df_low, meta_low, orientation="landscape")
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))
        self.assertIn(b"%%EOF", pdf_bytes[-120:])

    # ==========================================================================
    # 3. STOCK MOVEMENTS AUDIT LEDGER TESTS
    # ==========================================================================
    def test_stock_movements_report_and_type_filter(self):
        """Verifies stock movements ledger and filtering by movement_type."""
        # Filter only RECEIPT
        df_purch, meta_purch = get_stock_movements_data(
            product_id=self.prod1_id,
            movement_type="RECEIPT"
        )
        self.assertFalse(df_purch.empty)
        self.assertTrue((df_purch["movement_type"] == "RECEIPT").all())
        self.assertEqual(df_purch.iloc[0]["quantity"], 50)
        self.assertEqual(df_purch.iloc[0]["total_cost_impact"], 20000.0)

        # Filter only SALE
        df_sale, _ = get_stock_movements_data(
            product_id=self.prod1_id,
            movement_type="SALE"
        )
        self.assertFalse(df_sale.empty)
        self.assertTrue((df_sale["movement_type"] == "SALE").all())
        self.assertEqual(df_sale.iloc[0]["quantity"], -10)

        # Verify CSV and PDF
        csv_text = generate_report_csv(df_purch, meta_purch)
        self.assertIn("Stock Movement Audit Ledger Report", csv_text)
        self.assertIn("RECEIPT", csv_text)

        pdf_bytes = generate_report_pdf(df_purch, meta_purch, orientation="landscape")
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))
        self.assertIn(b"%%EOF", pdf_bytes[-120:])

    # ==========================================================================
    # 4. FESTIVAL CAMPAIGN COMPARISONS TESTS
    # ==========================================================================
    def test_festival_comparisons_report(self):
        """Verifies multi-year festival comparative report and ROI metrics."""
        df, meta = get_festival_comparisons_data(festival_id=self.fest_id)
        self.assertFalse(df.empty)
        self.assertIn("ACTUAL", meta["classification"])
        self.assertEqual(df.iloc[0]["festival_name"], "Reporting Test Diwali")
        self.assertEqual(df.iloc[0]["year"], 2026)
        self.assertGreater(df.iloc[0]["net_revenue"], 0)
        self.assertGreater(df.iloc[0]["gross_profit"], 0)
        self.assertGreater(df.iloc[0]["operating_expenses"], 0)
        self.assertIn("roi_pct", df.columns)

        # Verify definitions
        self.assertIn("Festival ROI %", meta["calculation_definitions"])

        # CSV & PDF
        csv_text = generate_report_csv(df, meta)
        self.assertIn("Festival Campaign Comparative Performance Report", csv_text)
        self.assertIn("Reporting Test Diwali", csv_text)

        pdf_bytes = generate_report_pdf(df, meta, orientation="landscape")
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))
        self.assertIn(b"%%EOF", pdf_bytes[-120:])

    # ==========================================================================
    # 5. EXPENSE SUMMARY REPORT TESTS
    # ==========================================================================
    def test_expense_summary_report_and_filters(self):
        """Verifies expense summary report with category and audit status filters."""
        # Filter MARKETING
        df_mkt, meta_mkt = get_expense_summary_data(category="MARKETING", occurrence_id=self.occ_id)
        self.assertFalse(df_mkt.empty)
        self.assertEqual(df_mkt.iloc[0]["category"], "MARKETING")
        self.assertEqual(df_mkt.iloc[0]["amount"], 1500.0)
        self.assertEqual(df_mkt.iloc[0]["vendor_name"], "REP-TEST-PRINTERS")

        # Filter RENT (should be empty for this test occurrence)
        df_rent, _ = get_expense_summary_data(category="RENT", occurrence_id=self.occ_id)
        self.assertTrue(df_rent.empty)

        # CSV & PDF
        csv_text = generate_report_csv(df_mkt, meta_mkt)
        self.assertIn("Operating Expenses & Overheads", csv_text)
        self.assertIn("REP-TEST-PRINTERS", csv_text)

        pdf_bytes = generate_report_pdf(df_mkt, meta_mkt, orientation="landscape")
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))
        self.assertIn(b"%%EOF", pdf_bytes[-120:])

    # ==========================================================================
    # 6. FORECAST-BASED STOCK PROCUREMENT PLAN TESTS
    # ==========================================================================
    def test_forecast_stock_plan_report_and_budget_analysis(self):
        """Verifies deterministic formula planning, budget variance, and explicit ESTIMATE distinction."""
        df_plan, meta_plan = get_forecast_stock_plan_data(
            occurrence_id=self.occ_id,
            purchasing_budget=5000.0,
            growth_multiplier=1.10
        )
        self.assertFalse(df_plan.empty)

        # Invariant: Data classification must clearly state ESTIMATES, not ACTUAL
        self.assertIn("ESTIMATES", meta_plan["classification"])
        self.assertIn("Non-Guaranteed Forecasts", meta_plan["classification"])

        # Calculation Definitions must clearly include deterministic inventory formula
        self.assertIn("Suggested Purchase Quantity", meta_plan["calculation_definitions"])
        formula_text = meta_plan["calculation_definitions"]["Suggested Purchase Quantity"]
        self.assertIn("max(0, Planned Demand + Safety Stock - Usable Stock)", formula_text)

        # Budget evaluation analysis present
        self.assertIn("budget_analysis", meta_plan)
        b_eval = meta_plan["budget_analysis"]
        self.assertIn("total_planned_cost", b_eval)
        self.assertIn("is_budget_exceeded", b_eval)

        # Verify CSV & PDF
        csv_text = generate_report_csv(df_plan, meta_plan)
        self.assertIn("DATA CLASSIFICATION: ESTIMATES & PLANNING PROJECTIONS", csv_text)
        self.assertIn("Suggested Purchase Quantity", csv_text)

        pdf_bytes = generate_report_pdf(df_plan, meta_plan, orientation="landscape")
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))
        self.assertIn(b"%%EOF", pdf_bytes[-120:])

    # ==========================================================================
    # 7. EMPTY REPORTS HANDLING TESTS
    # ==========================================================================
    def test_empty_reports_produce_valid_csv_and_pdf(self):
        """Ensures that zero-record queries produce valid, non-corrupted CSV and PDF downloads."""
        empty_df, empty_meta = get_sales_summary_data(
            start_date="2099-01-01",
            end_date="2099-01-02"
        )
        self.assertTrue(empty_df.empty)

        # CSV should contain headers and empty note
        csv_out = generate_report_csv(empty_df, empty_meta)
        self.assertTrue(csv_out.startswith("# =============================================================================="))
        self.assertIn("# NOTE: No database records matched the selected filter criteria.", csv_out)

        # PDF must be a valid PDF document with %PDF- header and %%EOF trailer
        pdf_out = generate_report_pdf(empty_df, empty_meta, orientation="landscape")
        self.assertIsInstance(pdf_out, bytes)
        self.assertTrue(pdf_out.startswith(b"%PDF-"))
        self.assertIn(b"%%EOF", pdf_out[-120:])
        self.assertGreater(len(pdf_out), 1500)

    # ==========================================================================
    # 8. UNICODE & CURRENCY SAFETY TESTS
    # ==========================================================================
    def test_unicode_and_inr_formatting(self):
        """Verifies that regional characters and Indian Rupee symbols are handled cleanly."""
        # Insert a product with regional Hindi / Marathi characters in name
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO products (
                    sku, product_name, category_id, unit_of_measure,
                    cost_price, selling_price, gst_rate, is_active
                ) VALUES (
                    'REP-SKU-UNI', 'काजू कतली (Kaju Katli) & Motichoor Laddoo & Co.', ?, 'box',
                    250.0, 450.0, 5.0, 1
                )
            """, (self.cat_id,))
            uni_prod_id = cursor.lastrowid

            cursor.execute("""
                INSERT INTO inventory_batches (
                    product_id, batch_number, quantity_received, quantity_available, unit_cost, received_date
                ) VALUES (?, 'REP-BAT-UNI', 10, 10, 250.0, '2026-10-01')
            """, (uni_prod_id,))

        df, meta = get_inventory_report_data(category_id=self.cat_id)
        # Generate CSV and PDF without any exceptions
        csv_str = generate_report_csv(df, meta)
        pdf_data = generate_report_pdf(df, meta)

        self.assertIn("REP-SKU-UNI", csv_str)
        self.assertTrue(pdf_data.startswith(b"%PDF-"))


if __name__ == "__main__":
    unittest.main()
