"""
FestivePulse — Expense Management & P&L Accounting Unit Test Suite
Comprehensive tests validating:
- Expense recording across rent, transport, packaging, wages, marketing, other
- Edit, correction, and cancellation audit trails
- Sales returns adjusting revenue, COGS, and gross profit
- Invoice and customer trade discounts
- Changing product catalog costs preserving historical cost snapshots
- Expense filtering and labeled exclusions for net operating profit
- Visible mathematical formula verification
"""

import unittest
import json
from datetime import date
from database.connection import init_db, db_session, get_db_connection
from services.expense_service import (
    record_expense,
    edit_expense,
    cancel_expense,
    get_expense_audit_trail,
    get_financial_pnl_statement,
    normalize_category
)
from repositories.expense_repository import ExpenseRepository


class TestExpenseManagementAndPnL(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        """Sets up isolated fixtures for expense management and P&L accounting tests."""
        with db_session() as conn:
            cursor = conn.cursor()

            # Clean test fixtures
            cursor.execute("DELETE FROM expense_audit_logs WHERE expense_id IN (SELECT expense_id FROM expenses WHERE vendor_name LIKE 'EXP-TEST-%')")
            cursor.execute("DELETE FROM expenses WHERE vendor_name LIKE 'EXP-TEST-%'")
            cursor.execute("DELETE FROM sales_returns WHERE return_number LIKE 'EXP-RET-%'")
            cursor.execute("DELETE FROM sales_items WHERE invoice_id IN (SELECT invoice_id FROM sales_invoices WHERE invoice_number LIKE 'EXP-INV-%')")
            cursor.execute("DELETE FROM sales_invoices WHERE invoice_number LIKE 'EXP-INV-%'")
            cursor.execute("DELETE FROM festival_occurrences WHERE notes LIKE 'EXP_TEST_%'")
            cursor.execute("DELETE FROM festivals WHERE festival_code LIKE 'EXP_TEST_%'")
            cursor.execute("DELETE FROM products WHERE sku LIKE 'EXP-SKU-%'")
            cursor.execute("DELETE FROM product_categories WHERE category_name LIKE 'EXP_CAT_%'")

            # 1. Test Category
            cursor.execute("""
                INSERT INTO product_categories (category_name, default_gst_rate, description)
                VALUES ('EXP_CAT_SWEETS', 5.0, 'Expense Test Category')
            """)
            self.cat_id = cursor.lastrowid

            # 2. Test Products
            # Product 1: Kaju Katli (Cost: 200.0, Sell: 300.0)
            cursor.execute("""
                INSERT INTO products (
                    sku, barcode, product_name, category_id, unit_of_measure,
                    cost_price, selling_price, mrp, gst_rate, min_safety_stock, reorder_quantity, is_active
                ) VALUES ('EXP-SKU-001', '8908888001', 'Expense Test Kaju Katli', ?, 'box', 200.0, 300.0, 350.0, 5.0, 10, 20, 1)
            """, (self.cat_id,))
            self.prod_1_id = cursor.lastrowid

            # 3. Test Festivals & Occurrences
            cursor.execute("""
                INSERT INTO festivals (festival_name, festival_code, primary_regions, typical_surge_multiplier)
                VALUES ('Expense Test Festival', 'EXP_TEST_FEST', '["National"]', 2.0)
            """)
            self.fest_id = cursor.lastrowid

            # Occurrence 100
            cursor.execute("""
                INSERT INTO festival_occurrences (
                    festival_id, year, prep_start_date, campaign_start_date, campaign_end_date,
                    peak_start_date, festival_date, notes
                ) VALUES (?, 2026, '2026-10-01', '2026-10-15', '2026-10-24', '2026-10-20', '2026-10-24', 'EXP_TEST_2026_A')
            """, (self.fest_id,))
            self.occ_100_id = cursor.lastrowid

            # Occurrence 200 (Different festival occurrence)
            cursor.execute("""
                INSERT INTO festival_occurrences (
                    festival_id, year, prep_start_date, campaign_start_date, campaign_end_date,
                    peak_start_date, festival_date, notes
                ) VALUES (?, 2027, '2027-10-01', '2027-10-15', '2027-10-24', '2027-10-20', '2027-10-24', 'EXP_TEST_2027_B')
            """, (self.fest_id,))
            self.occ_200_id = cursor.lastrowid

    def tearDown(self):
        """Cleans test fixtures."""
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM expense_audit_logs WHERE expense_id IN (SELECT expense_id FROM expenses WHERE vendor_name LIKE 'EXP-TEST-%')")
            cursor.execute("DELETE FROM expenses WHERE vendor_name LIKE 'EXP-TEST-%'")
            cursor.execute("DELETE FROM sales_returns WHERE return_number LIKE 'EXP-RET-%'")
            cursor.execute("DELETE FROM sales_items WHERE invoice_id IN (SELECT invoice_id FROM sales_invoices WHERE invoice_number LIKE 'EXP-INV-%')")
            cursor.execute("DELETE FROM sales_invoices WHERE invoice_number LIKE 'EXP-INV-%'")
            cursor.execute("DELETE FROM festival_occurrences WHERE notes LIKE 'EXP_TEST_%'")
            cursor.execute("DELETE FROM festivals WHERE festival_code LIKE 'EXP_TEST_%'")
            cursor.execute("DELETE FROM products WHERE sku LIKE 'EXP-SKU-%'")
            cursor.execute("DELETE FROM product_categories WHERE category_name LIKE 'EXP_CAT_%'")

    def test_record_expense_across_categories_with_audit(self):
        """
        Tests recording operational expenses across rent, transport, packaging,
        wages, marketing, and other costs, storing amount, date, category, description,
        and optional festival reference, verifying initial audit log.
        """
        categories_to_test = [
            ("RENT", 30000.0, "Monthly Store Rent"),
            ("TRANSPORT", 4500.0, "Inbound Freight Logistics"),
            ("PACKAGING", 6000.0, "1000 Mithai Boxes"),
            ("WAGES", 15000.0, "Peak Festival Staff Bonus"),
            ("MARKETING", 8000.0, "Canopy Banners & Local Ads"),
            ("OTHER", 2500.0, "Special Generator & Lighting")
        ]

        for cat, amt, desc in categories_to_test:
            exp_id = record_expense(
                amount=amt,
                expense_date="2026-10-16",
                category=cat,
                description=desc,
                occurrence_id=self.occ_100_id,
                payment_mode="BANK_TRANSFER",
                vendor_name=f"EXP-TEST-{cat}-Vendor",
                invoice_receipt_no=f"REC-{cat}-001"
            )
            self.assertGreater(exp_id, 0)

            # Verify audit trail contains CREATE action
            trail = get_expense_audit_trail(exp_id)
            self.assertEqual(len(trail), 1)
            self.assertEqual(trail[0]["action"], "CREATE")
            self.assertEqual(trail[0]["new_values"]["amount"], amt)
            self.assertEqual(trail[0]["new_values"]["category"], cat)

    def test_edit_and_correction_audit_handling(self):
        """
        Tests editing and correcting an expense:
        Verifies that old values are preserved in audit history,
        status becomes 'CORRECTED', and new values are stored.
        """
        exp_id = record_expense(
            amount=5000.0,
            expense_date="2026-10-16",
            category="TRANSPORT",
            description="Initial Freight Bill",
            occurrence_id=self.occ_100_id,
            vendor_name="EXP-TEST-Carrier"
        )

        # Edit the expense per revision bill
        success = edit_expense(
            expense_id=exp_id,
            reason="Carrier adjusted fuel surcharge by ₹650",
            amount=5650.0,
            description="Revised Freight Bill including Fuel Surcharge"
        )
        self.assertTrue(success)

        # Verify database record
        exp_row = ExpenseRepository.get_expense_by_id(exp_id)
        self.assertEqual(exp_row["amount"], 5650.0)
        self.assertEqual(exp_row["status"], "CORRECTED")
        self.assertEqual(exp_row["description"], "Revised Freight Bill including Fuel Surcharge")

        # Verify complete audit history
        trail = get_expense_audit_trail(exp_id)
        self.assertEqual(len(trail), 2)
        # Entry 1: CREATE
        self.assertEqual(trail[0]["action"], "CREATE")
        # Entry 2: CORRECTION
        self.assertEqual(trail[1]["action"], "CORRECTION")
        self.assertEqual(trail[1]["previous_values"]["amount"], 5000.0)
        self.assertEqual(trail[1]["new_values"]["amount"], 5650.0)
        self.assertIn("fuel surcharge", trail[1]["reason"])

    def test_cancel_expense_audit_and_pnl_exclusion(self):
        """
        Tests cancelling an expense:
        - Status becomes 'CANCELLED'
        - Cancellation reason is logged in audit trail
        - Cancelled expense is excluded from P&L included expenses
        - Labeled under labeled_exclusions
        """
        exp_id = record_expense(
            amount=12000.0,
            expense_date="2026-10-18",
            category="MARKETING",
            description="Cancelled Newspaper Ad Voucher",
            occurrence_id=self.occ_100_id,
            vendor_name="EXP-TEST-Publisher"
        )

        success = cancel_expense(
            expense_id=exp_id,
            reason="Newspaper publication delayed; order cancelled"
        )
        self.assertTrue(success)

        # Verify status in database
        exp_row = ExpenseRepository.get_expense_by_id(exp_id)
        self.assertEqual(exp_row["status"], "CANCELLED")

        # Verify audit trail
        trail = get_expense_audit_trail(exp_id)
        self.assertEqual(trail[-1]["action"], "CANCEL")
        self.assertIn("publication delayed", trail[-1]["reason"])

        # Verify P&L excludes it
        pnl = get_financial_pnl_statement(occurrence_id=self.occ_100_id)
        self.assertEqual(pnl["total_included_expenses"], 0.0)
        self.assertTrue(pnl["has_exclusions"])

        # Must appear under labeled exclusions
        excl_reasons = [e["reason"] for e in pnl["labeled_exclusions"]]
        self.assertTrue(any("Cancelled audit record" in r for r in excl_reasons))

    def test_changing_product_costs_preserves_historical_snapshots(self):
        """
        CRITICAL TEST:
        'Historical cost snapshots must not change when a product's current purchase cost changes.'
        1. Product is sold with cost snapshot = 200.0.
        2. Catalog price of product is subsequently changed to 450.0.
        3. P&L statement must continue to compute COGS from the 200.0 snapshot, NOT 450.0.
        """
        with db_session() as conn:
            cursor = conn.cursor()
            # Invoice: 10 units at selling price 300.0, snapshot cost 200.0
            # Gross Taxable = 3000.0, COGS = 2000.0, Gross Profit = 1000.0
            cursor.execute("""
                INSERT INTO sales_invoices (
                    invoice_number, invoice_date, occurrence_id, payment_mode,
                    subtotal_amount, discount_amount, total_taxable_amount, net_total_amount, status
                ) VALUES ('EXP-INV-1', '2026-10-16', ?, 'CASH', 3000.0, 0.0, 3000.0, 3150.0, 'COMPLETED')
            """, (self.occ_100_id,))
            inv_id = cursor.lastrowid

            cursor.execute("""
                INSERT INTO sales_items (
                    invoice_id, product_id, quantity, unit_cost_price, unit_selling_price,
                    taxable_value, gst_rate, total_item_amount, gross_profit
                ) VALUES (?, ?, 10, 200.0, 300.0, 3000.0, 5.0, 3150.0, 1000.0)
            """, (inv_id, self.prod_1_id))

        # Check initial P&L
        pnl_before = get_financial_pnl_statement(occurrence_id=self.occ_100_id)
        self.assertEqual(pnl_before["net_sales_revenue"], 3000.0)
        self.assertEqual(pnl_before["net_cogs"], 2000.0)
        self.assertEqual(pnl_before["gross_profit"], 1000.0)

        # NOW: Supplier raises catalog cost in products table from 200.0 to 450.0 (selling price and mrp also adjusted)
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE products SET cost_price = 450.0, selling_price = 550.0, mrp = 600.0 WHERE product_id = ?", (self.prod_1_id,))

        # Verify catalog price was updated
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT cost_price FROM products WHERE product_id = ?", (self.prod_1_id,))
            self.assertEqual(cursor.fetchone()[0], 450.0)

        # Re-compute P&L statement
        pnl_after = get_financial_pnl_statement(occurrence_id=self.occ_100_id)

        # Historical COGS MUST REMAIN 2000.0 (based on snapshot 200.0), NOT 4500.0!
        self.assertEqual(pnl_after["net_sales_revenue"], 3000.0)
        self.assertEqual(pnl_after["net_cogs"], 2000.0)
        self.assertEqual(pnl_after["gross_profit"], 1000.0)
        self.assertEqual(pnl_after["gross_margin_pct"], 33.33)

    def test_discounts_in_pnl(self):
        """
        Tests that trade and customer discounts are properly tracked and accounted for.
        Gross Billed = 5000.0, Discount = 600.0 -> Net Taxable = 4400.0.
        """
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO sales_invoices (
                    invoice_number, invoice_date, occurrence_id, payment_mode,
                    subtotal_amount, discount_amount, total_taxable_amount, net_total_amount, status
                ) VALUES ('EXP-INV-DISC', '2026-10-17', ?, 'CASH', 5000.0, 600.0, 4400.0, 4620.0, 'COMPLETED')
            """, (self.occ_100_id,))
            inv_id = cursor.lastrowid

            cursor.execute("""
                INSERT INTO sales_items (
                    invoice_id, product_id, quantity, unit_cost_price, unit_selling_price,
                    taxable_value, gst_rate, total_item_amount, gross_profit
                ) VALUES (?, ?, 10, 200.0, 500.0, 4400.0, 5.0, 4620.0, 2400.0)
            """, (inv_id, self.prod_1_id))

        pnl = get_financial_pnl_statement(occurrence_id=self.occ_100_id)
        self.assertEqual(pnl["gross_billed"], 5000.0)
        self.assertEqual(pnl["total_discounts"], 600.0)
        self.assertEqual(pnl["net_sales_revenue"], 4400.0)
        self.assertEqual(pnl["net_cogs"], 2000.0)
        self.assertEqual(pnl["gross_profit"], 2400.0)

    def test_returns_adjust_revenue_and_cogs(self):
        """
        Tests that sales returns reverse both revenue and COGS using snapshot prices:
        Sale: 10 units at 300.0 sell, 200.0 cost (Revenue 3000, COGS 2000).
        Return: 3 units returned with refund 900.0.
        Net Revenue = 3000 - 900 = 2100.0
        Returned COGS = 3 * 200 = 600.0
        Net COGS = 2000 - 600 = 1400.0
        Gross Profit = 2100 - 1400 = 700.0
        """
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO sales_invoices (
                    invoice_number, invoice_date, occurrence_id, payment_mode,
                    subtotal_amount, discount_amount, total_taxable_amount, net_total_amount, status
                ) VALUES ('EXP-INV-RET', '2026-10-18', ?, 'CASH', 3000.0, 0.0, 3000.0, 3000.0, 'COMPLETED')
            """, (self.occ_100_id,))
            inv_id = cursor.lastrowid

            cursor.execute("""
                INSERT INTO sales_items (
                    invoice_id, product_id, quantity, unit_cost_price, unit_selling_price,
                    taxable_value, gst_rate, total_item_amount, gross_profit
                ) VALUES (?, ?, 10, 200.0, 300.0, 3000.0, 0.0, 3000.0, 1000.0)
            """, (inv_id, self.prod_1_id))
            item_id = cursor.lastrowid

            # Customer returns 3 units
            cursor.execute("""
                INSERT INTO sales_returns (
                    return_number, invoice_id, item_id, product_id,
                    return_date, quantity, refund_amount, tax_refund_amount, reason, restock_to_inventory
                ) VALUES ('EXP-RET-001', ?, ?, ?, '2026-10-19', 3, 900.0, 0.0, 'Customer gift box excess', 1)
            """, (inv_id, item_id, self.prod_1_id))

        pnl = get_financial_pnl_statement(occurrence_id=self.occ_100_id)
        self.assertEqual(pnl["returns"]["returned_units_count"], 3)
        self.assertEqual(pnl["returns"]["net_taxable_returns"], 900.0)
        self.assertEqual(pnl["returns"]["returned_cogs"], 600.0)
        self.assertEqual(pnl["net_sales_revenue"], 2100.0)
        self.assertEqual(pnl["net_cogs"], 1400.0)
        self.assertEqual(pnl["gross_profit"], 700.0)

    def test_expense_filtering_and_labeled_exclusions(self):
        """
        Tests calculating net operating profit only when relevant expenses are included,
        and clearly labelling exclusions:
        - Exp 1: Packaging (5000.0, festival 100) -> INCLUDED
        - Exp 2: Marketing (8000.0, festival 100) -> INCLUDED
        - Exp 3: Store Rent (20000.0, general overhead, occurrence_id=None) -> EXCLUDED when viewing festival 100
        - Exp 4: Transport (3000.0, festival 200) -> EXCLUDED (different festival)
        - Exp 5: Cancelled Wages (4000.0, festival 100) -> EXCLUDED (cancelled status)
        """
        # Create expenses
        e1 = record_expense(5000.0, "2026-10-16", "PACKAGING", "Boxes", occurrence_id=self.occ_100_id, vendor_name="EXP-TEST-1")
        e2 = record_expense(8000.0, "2026-10-17", "MARKETING", "Banners", occurrence_id=self.occ_100_id, vendor_name="EXP-TEST-2")
        e3 = record_expense(20000.0, "2026-10-15", "RENT", "General Store Rent", occurrence_id=None, vendor_name="EXP-TEST-3")
        e4 = record_expense(3000.0, "2026-10-16", "TRANSPORT", "Festival 200 Transport", occurrence_id=self.occ_200_id, vendor_name="EXP-TEST-4")
        e5 = record_expense(4000.0, "2026-10-18", "WAGES", "Cancelled Wages", occurrence_id=self.occ_100_id, vendor_name="EXP-TEST-5")
        cancel_expense(e5, "Cancelled shift overtime voucher")

        # Create a sale in festival 100 so gross profit = 5000.0
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO sales_invoices (
                    invoice_number, invoice_date, occurrence_id, payment_mode,
                    subtotal_amount, discount_amount, total_taxable_amount, net_total_amount, status
                ) VALUES ('EXP-INV-SCOPE', '2026-10-16', ?, 'CASH', 10000.0, 0.0, 10000.0, 10000.0, 'COMPLETED')
            """, (self.occ_100_id,))
            inv_id = cursor.lastrowid

            cursor.execute("""
                INSERT INTO sales_items (
                    invoice_id, product_id, quantity, unit_cost_price, unit_selling_price,
                    taxable_value, gst_rate, total_item_amount, gross_profit
                ) VALUES (?, ?, 25, 200.0, 400.0, 10000.0, 0.0, 10000.0, 5000.0)
            """, (inv_id, self.prod_1_id))

        # Test Case 1: Festival 100 Campaign Scope (General overheads excluded)
        pnl = get_financial_pnl_statement(occurrence_id=self.occ_100_id, include_general_overheads=False)

        # Included expenses should be ONLY Packaging (5000) + Marketing (8000) = 13000.0
        self.assertEqual(pnl["total_included_expenses"], 13000.0)
        # Gross profit = 5000.0, Net operating profit = 5000.0 - 13000.0 = -8000.0
        self.assertEqual(pnl["net_operating_profit"], -8000.0)

        # Labeled exclusions must include Rent, Transport (Festival 200), and Cancelled Wages
        excl_list = pnl["labeled_exclusions"]
        self.assertGreaterEqual(len(excl_list), 3)
        excl_ids = [x["expense_id"] for x in excl_list]
        self.assertIn(e3, excl_ids)  # General rent
        self.assertIn(e4, excl_ids)  # Different festival transport
        self.assertIn(e5, excl_ids)  # Cancelled wages

        # Test Case 2: Category filter: MARKETING only
        pnl_mkt = get_financial_pnl_statement(occurrence_id=self.occ_100_id, category_filter="MARKETING", include_general_overheads=False)
        self.assertEqual(pnl_mkt["total_included_expenses"], 8000.0)
        # Packaging (5000) is now also in labeled exclusions
        excl_mkt_ids = [x["expense_id"] for x in pnl_mkt["labeled_exclusions"]]
        self.assertIn(e1, excl_mkt_ids)

    def test_normalize_category_canonical_mapping(self):
        """Verifies that all primary categories and legacy aliases normalize to the 6 primary categories."""
        expected = {
            "RENT": "RENT",
            "TEMPORARY_STALL_RENT": "RENT",
            "TRANSPORT": "TRANSPORT",
            "TRANSPORT_FREIGHT": "TRANSPORT",
            "PACKAGING": "PACKAGING",
            "PACKAGING_BOXES": "PACKAGING",
            "WAGES": "WAGES",
            "STAFF_BONUS_OVERTIME": "WAGES",
            "MARKETING": "MARKETING",
            "MARKETING_BANNERS_PAMPHLETS": "MARKETING",
            "OTHER": "OTHER",
            "FESTIVAL_DECORATION": "OTHER",
            "UTILITIES_POWER": "OTHER",
            "MISCELLANEOUS": "OTHER",
            "": "OTHER",
            None: "OTHER"
        }
        for raw, expected_canon in expected.items():
            self.assertEqual(normalize_category(raw), expected_canon, f"Failed for category: {raw}")


if __name__ == "__main__":
    unittest.main()

