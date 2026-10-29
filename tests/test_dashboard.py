"""
FestivePulse — Dashboard Analytics Unit Tests
Tests every dashboard metric and chart series against known SQLite database fixtures:
- Total Sales (completed invoices net of returns, exclusions of cancellations)
- Sales This Month
- Gross Profit (where cost data is available, cost coverage percentage)
- Current Inventory Value (batch valuation)
- Low-Stock Product Count
- Upcoming Configured Festivals
- Empty Database Onboarding State
- Date, Category, and Product Filters
"""

import unittest
from datetime import date, timedelta
from database.connection import init_db, db_session, get_db_connection
from services.dashboard_service import (
    check_database_state,
    get_dashboard_kpis,
    get_revenue_over_time,
    get_top_selling_products,
    get_stock_status_breakdown,
    get_festival_period_comparisons
)


class TestDashboardMetrics(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        """Set up isolated known database fixtures for testing."""
        with db_session() as conn:
            cursor = conn.cursor()
            # Clean any previous test data
            cursor.execute("DELETE FROM sales_returns WHERE return_number LIKE 'TEST-RET-%'")
            cursor.execute("DELETE FROM sales_items WHERE invoice_id IN (SELECT invoice_id FROM sales_invoices WHERE invoice_number LIKE 'TEST-INV-%')")
            cursor.execute("DELETE FROM sales_invoices WHERE invoice_number LIKE 'TEST-INV-%'")
            cursor.execute("DELETE FROM stock_movements WHERE reference_id LIKE 'TEST-%'")
            cursor.execute("DELETE FROM inventory_batches WHERE batch_number LIKE 'TEST-BATCH-%'")
            cursor.execute("DELETE FROM products WHERE sku LIKE 'TEST-SKU-%'")
            cursor.execute("DELETE FROM product_categories WHERE category_name LIKE 'TEST_CAT_%'")
            cursor.execute("DELETE FROM festival_calendar WHERE festival_name LIKE 'TEST_DASH_%'")

            # 1. Create 2 Test Categories
            cursor.execute("INSERT INTO product_categories (category_name, default_gst_rate, description) VALUES ('TEST_CAT_SWEETS', 5.0, 'Test Sweets')")
            self.cat_sweets_id = cursor.lastrowid
            cursor.execute("INSERT INTO product_categories (category_name, default_gst_rate, description) VALUES ('TEST_CAT_DECOR', 18.0, 'Test Decor')")
            self.cat_decor_id = cursor.lastrowid

            # 2. Create 3 Test Products with known costs and safety stocks
            # Product 1: Kaju Katli (Cost: 400, Sell: 600, Safety: 10)
            cursor.execute("""
                INSERT INTO products (
                    sku, barcode, product_name, category_id, unit_of_measure,
                    cost_price, selling_price, mrp, gst_rate, min_safety_stock, reorder_quantity, is_active
                ) VALUES ('TEST-SKU-001', '8901111001', 'TEST Kaju Katli', ?, 'box', 400.0, 600.0, 650.0, 5.0, 10, 50, 1)
            """, (self.cat_sweets_id,))
            self.prod_kaju_id = cursor.lastrowid

            # Product 2: Gulab Jamun (Cost: 200, Sell: 300, Safety: 15)
            cursor.execute("""
                INSERT INTO products (
                    sku, barcode, product_name, category_id, unit_of_measure,
                    cost_price, selling_price, mrp, gst_rate, min_safety_stock, reorder_quantity, is_active
                ) VALUES ('TEST-SKU-002', '8901111002', 'TEST Gulab Jamun', ?, 'box', 200.0, 300.0, 350.0, 5.0, 15, 40, 1)
            """, (self.cat_sweets_id,))
            self.prod_jamun_id = cursor.lastrowid

            # Product 3: Brass Diya (Cost: 100, Sell: 250, Safety: 20)
            cursor.execute("""
                INSERT INTO products (
                    sku, barcode, product_name, category_id, unit_of_measure,
                    cost_price, selling_price, mrp, gst_rate, min_safety_stock, reorder_quantity, is_active
                ) VALUES ('TEST-SKU-003', '8901111003', 'TEST Brass Diya', ?, 'pcs', 100.0, 250.0, 300.0, 18.0, 20, 100, 1)
            """, (self.cat_decor_id,))
            self.prod_diya_id = cursor.lastrowid

            # 3. Create Inventory Batches
            # Product 1 has 5 units available (<= 10 -> Low Stock!)
            cursor.execute("""
                INSERT INTO inventory_batches (
                    product_id, batch_number, received_date, expiry_date, quantity_received, quantity_available, unit_cost
                ) VALUES (?, 'TEST-BATCH-001', '2026-10-01', '2026-11-30', 20, 5, 400.0)
            """, (self.prod_kaju_id,))
            self.batch_kaju_id = cursor.lastrowid

            # Product 2 has 25 units available (> 15 -> In Stock Healthy!)
            cursor.execute("""
                INSERT INTO inventory_batches (
                    product_id, batch_number, received_date, expiry_date, quantity_received, quantity_available, unit_cost
                ) VALUES (?, 'TEST-BATCH-002', '2026-10-05', '2026-12-15', 30, 25, 200.0)
            """, (self.prod_jamun_id,))
            self.batch_jamun_id = cursor.lastrowid

            # Product 3 has 0 units available (<= 20 -> Out of Stock / Low Stock!)
            cursor.execute("""
                INSERT INTO inventory_batches (
                    product_id, batch_number, received_date, expiry_date, quantity_received, quantity_available, unit_cost
                ) VALUES (?, 'TEST-BATCH-003', '2026-10-10', NULL, 50, 0, 100.0)
            """, (self.prod_diya_id,))
            self.batch_diya_id = cursor.lastrowid

            # 4. Create Invoices for Testing
            # Invoice 1: Completed, Oct 15, 2026 (Kaju: 2 units, Jamun: 3 units)
            # Kaju: 2 * 600 = 1200 taxable + 60 GST = 1260. Cost: 2 * 400 = 800. Profit: 400.
            # Jamun: 3 * 300 = 900 taxable + 45 GST = 945. Cost: 3 * 200 = 600. Profit: 300.
            # Inv 1 Net: 1260 + 945 = 2205.
            cursor.execute("""
                INSERT INTO sales_invoices (
                    invoice_number, invoice_date, payment_mode, subtotal_amount,
                    discount_amount, total_taxable_amount, cgst_amount, sgst_amount,
                    igst_amount, roundoff_amount, net_total_amount, status
                ) VALUES ('TEST-INV-001', '2026-10-15', 'UPI', 2100.0, 0.0, 2100.0, 52.5, 52.5, 0.0, 0.0, 2205.0, 'COMPLETED')
            """)
            self.inv1_id = cursor.lastrowid

            cursor.execute("""
                INSERT INTO sales_items (
                    invoice_id, product_id, batch_id, quantity, unit_cost_price, unit_selling_price,
                    discount_percent, taxable_value, gst_rate, cgst_rate, cgst_amount, sgst_rate,
                    sgst_amount, igst_rate, igst_amount, total_item_amount, gross_profit
                ) VALUES (?, ?, ?, 2, 400.0, 600.0, 0.0, 1200.0, 5.0, 2.5, 30.0, 2.5, 30.0, 0.0, 0.0, 1260.0, 400.0)
            """, (self.inv1_id, self.prod_kaju_id, self.batch_kaju_id))

            cursor.execute("""
                INSERT INTO sales_items (
                    invoice_id, product_id, batch_id, quantity, unit_cost_price, unit_selling_price,
                    discount_percent, taxable_value, gst_rate, cgst_rate, cgst_amount, sgst_rate,
                    sgst_amount, igst_rate, igst_amount, total_item_amount, gross_profit
                ) VALUES (?, ?, ?, 3, 200.0, 300.0, 0.0, 900.0, 5.0, 2.5, 22.5, 2.5, 2.5, 0.0, 0.0, 945.0, 300.0)
            """, (self.inv1_id, self.prod_jamun_id, self.batch_jamun_id))

            # Invoice 2: Previous Month (Sept 20, 2026), Completed
            # Diya: 4 units * 250 = 1000 taxable + 180 GST = 1180. Cost: 4 * 100 = 400. Profit: 600.
            cursor.execute("""
                INSERT INTO sales_invoices (
                    invoice_number, invoice_date, payment_mode, subtotal_amount,
                    discount_amount, total_taxable_amount, cgst_amount, sgst_amount,
                    igst_amount, roundoff_amount, net_total_amount, status
                ) VALUES ('TEST-INV-002', '2026-09-20', 'CASH', 1000.0, 0.0, 1000.0, 90.0, 90.0, 0.0, 0.0, 1180.0, 'COMPLETED')
            """)
            self.inv2_id = cursor.lastrowid

            cursor.execute("""
                INSERT INTO sales_items (
                    invoice_id, product_id, batch_id, quantity, unit_cost_price, unit_selling_price,
                    discount_percent, taxable_value, gst_rate, cgst_rate, cgst_amount, sgst_rate,
                    sgst_amount, igst_rate, igst_amount, total_item_amount, gross_profit
                ) VALUES (?, ?, ?, 4, 100.0, 250.0, 0.0, 1000.0, 18.0, 9.0, 90.0, 9.0, 90.0, 0.0, 0.0, 1180.0, 600.0)
            """, (self.inv2_id, self.prod_diya_id, self.batch_diya_id))

            # Invoice 3: CANCELLED Invoice (Must be excluded from all revenue and profit!)
            cursor.execute("""
                INSERT INTO sales_invoices (
                    invoice_number, invoice_date, payment_mode, subtotal_amount,
                    discount_amount, total_taxable_amount, cgst_amount, sgst_amount,
                    igst_amount, roundoff_amount, net_total_amount, status
                ) VALUES ('TEST-INV-003', '2026-10-18', 'CARD', 5000.0, 0.0, 5000.0, 125.0, 125.0, 0.0, 0.0, 5250.0, 'CANCELLED')
            """)
            self.inv3_id = cursor.lastrowid
            cursor.execute("""
                INSERT INTO sales_items (
                    invoice_id, product_id, batch_id, quantity, unit_cost_price, unit_selling_price,
                    discount_percent, taxable_value, gst_rate, cgst_rate, cgst_amount, sgst_rate,
                    sgst_amount, igst_rate, igst_amount, total_item_amount, gross_profit
                ) VALUES (?, ?, ?, 10, 200.0, 500.0, 0.0, 5000.0, 5.0, 2.5, 125.0, 2.5, 125.0, 0.0, 0.0, 5250.0, 3000.0)
            """, (self.inv3_id, self.prod_jamun_id, self.batch_jamun_id))

            # 5. Create a Sales Return for Invoice 1
            # Customer returned 1 box of Kaju Katli (Refund: 630)
            cursor.execute("""
                INSERT INTO sales_returns (
                    return_number, invoice_id, product_id, batch_id, return_date, quantity, refund_amount, tax_refund_amount, reason, restock_to_inventory
                ) VALUES ('TEST-RET-001', ?, ?, ?, '2026-10-16', 1, 630.0, 30.0, 'Customer bought extra box', 1)
            """, (self.inv1_id, self.prod_kaju_id, self.batch_kaju_id))

            # 6. Add a Test Upcoming Festival
            cursor.execute("""
                INSERT INTO festival_calendar (
                    festival_name, festival_code, region, start_date, end_date, category, planning_window_days, planning_start_date, is_sample_date, is_verified, year
                ) VALUES ('TEST_DASH_Diwali', 'TEST_DIWALI', 'Pan-India', '2026-11-08', '2026-11-12', 'Major Religious', 30, '2026-10-09', 0, 1, 2026)
            """)

    def tearDown(self):
        """Clean test records."""
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM sales_returns WHERE return_number LIKE 'TEST-RET-%'")
            cursor.execute("DELETE FROM sales_items WHERE invoice_id IN (SELECT invoice_id FROM sales_invoices WHERE invoice_number LIKE 'TEST-INV-%')")
            cursor.execute("DELETE FROM sales_invoices WHERE invoice_number LIKE 'TEST-INV-%'")
            cursor.execute("DELETE FROM stock_movements WHERE reference_id LIKE 'TEST-%'")
            cursor.execute("DELETE FROM inventory_batches WHERE batch_number LIKE 'TEST-BATCH-%'")
            cursor.execute("DELETE FROM products WHERE sku LIKE 'TEST-SKU-%'")
            cursor.execute("DELETE FROM product_categories WHERE category_name LIKE 'TEST_CAT_%'")
            cursor.execute("DELETE FROM festival_calendar WHERE festival_name LIKE 'TEST_DASH_%'")

    # -------------------------------------------------------------------------
    # 1. TOTAL SALES & CANCELLATION/RETURN ADJUSTMENTS
    # -------------------------------------------------------------------------
    def test_total_sales_for_specific_product(self):
        """
        Verify total sales for Kaju Katli:
        Sold 2 units = 1260 gross, minus 1 returned unit (630 refund) = 630.0 net.
        """
        kpis = get_dashboard_kpis(product_id=self.prod_kaju_id)
        self.assertEqual(kpis["total_sales"], 630.0)
        self.assertEqual(kpis["invoice_count"], 1)

    def test_total_sales_excludes_cancelled_invoices(self):
        """
        Verify that CANCELLED Invoice 3 (₹5,250) is strictly excluded from sales.
        """
        kpis = get_dashboard_kpis(product_id=self.prod_jamun_id)
        # Only Inv 1 (3 units * 300 + 5% GST = 945.0) should be present; Inv 3 is cancelled!
        self.assertEqual(kpis["total_sales"], 945.0)

    # -------------------------------------------------------------------------
    # 2. SALES THIS MONTH METRIC
    # -------------------------------------------------------------------------
    def test_sales_this_month_isolates_current_calendar_month(self):
        """
        Reference date: 2026-10-20.
        Current month (October 2026):
        - Inv 1 (Oct 15) is included: 2205 gross - 630 return = 1575 net.
        - Inv 2 (Sept 20) is in September, so it must NOT be in October sales.
        """
        ref_date = date(2026, 10, 20)
        # Query for Sweets category (Kaju + Jamun) in October 2026
        kpis = get_dashboard_kpis(category_id=self.cat_sweets_id, reference_date=ref_date)
        # Gross in Oct: 1260 + 945 = 2205. Returns in Oct: 630. Net = 1575.0.
        self.assertEqual(kpis["sales_this_month"], 1575.0)

    # -------------------------------------------------------------------------
    # 3. GROSS PROFIT WHERE COST DATA IS AVAILABLE
    # -------------------------------------------------------------------------
    def test_gross_profit_calculation_and_cost_coverage(self):
        """
        Gross profit where cost data is available:
        Product 1 (Kaju): 2 units sold. Taxable = 1200. Cost = 2 * 400 = 800. Profit = 400.
        Returned 1 unit: 630 refund - 400 cost = 230 returned profit (tax refund 30).
        Net profit for Kaju = 400 - (600 - 400) = 200.
        Product 2 (Jamun): 3 units sold. Taxable = 900. Cost = 3 * 200 = 600. Profit = 300.
        Total gross profit for Sweets category = 200 + 300 = 500.0.
        Cost coverage = 100.0%.
        """
        kpis = get_dashboard_kpis(category_id=self.cat_sweets_id)
        self.assertEqual(kpis["cost_coverage_pct"], 100.0)
        self.assertEqual(kpis["gross_profit"], 500.0)

    # -------------------------------------------------------------------------
    # 4. CURRENT INVENTORY VALUE METRIC
    # -------------------------------------------------------------------------
    def test_current_inventory_value_from_active_batches(self):
        """
        Valuation of stock on hand for our test products:
        - Kaju: 5 available * 400.0 cost = 2,000.0
        - Jamun: 25 available * 200.0 cost = 5,000.0
        - Diya: 0 available * 100.0 cost = 0.0
        Total for Sweets category = 2,000 + 5,000 = 7,000.0.
        """
        kpis_sweets = get_dashboard_kpis(category_id=self.cat_sweets_id)
        self.assertEqual(kpis_sweets["current_inventory_value"], 7000.0)

        kpis_decor = get_dashboard_kpis(category_id=self.cat_decor_id)
        self.assertEqual(kpis_decor["current_inventory_value"], 0.0)

    # -------------------------------------------------------------------------
    # 5. LOW-STOCK PRODUCT COUNT METRIC
    # -------------------------------------------------------------------------
    def test_low_stock_product_count_calculation(self):
        """
        Out of the 2 Sweets products:
        - Kaju has 5 stock <= safety stock 10 -> Low stock! (1)
        - Jamun has 25 stock > safety stock 15 -> Healthy! (0)
        Low stock count for Sweets = 1.
        Out of Decor:
        - Diya has 0 stock <= safety stock 20 -> Low stock! (1)
        """
        kpis_sweets = get_dashboard_kpis(category_id=self.cat_sweets_id)
        self.assertEqual(kpis_sweets["low_stock_product_count"], 1)
        self.assertEqual(kpis_sweets["total_products"], 2)

        kpis_decor = get_dashboard_kpis(category_id=self.cat_decor_id)
        self.assertEqual(kpis_decor["low_stock_product_count"], 1)
        self.assertEqual(kpis_decor["total_products"], 1)

    # -------------------------------------------------------------------------
    # 6. UPCOMING CONFIGURED FESTIVALS METRIC
    # -------------------------------------------------------------------------
    def test_upcoming_configured_festivals_retrieval(self):
        """
        Upcoming festivals relative to 2026-10-20.
        TEST_DASH_Diwali starts 2026-11-08 (19 days away).
        """
        kpis = get_dashboard_kpis(reference_date=date(2026, 10, 20))
        names = [f["festival_name"] for f in kpis["upcoming_festivals"]]
        self.assertIn("TEST_DASH_Diwali", names)

        test_f = next(f for f in kpis["upcoming_festivals"] if f["festival_name"] == "TEST_DASH_Diwali")
        self.assertEqual(test_f["days_until"], 19)

    # -------------------------------------------------------------------------
    # 7. CHARTS & REVENUE OVER TIME REFLECTING FILTERS
    # -------------------------------------------------------------------------
    def test_revenue_over_time_respects_date_and_category_filters(self):
        """
        Revenue trend returns daily points within filtered criteria.
        For Sweets in October 2026: only 2026-10-15 should be returned.
        """
        trend_df = get_revenue_over_time(
            start_date="2026-10-01",
            end_date="2026-10-31",
            category_id=self.cat_sweets_id
        )
        self.assertFalse(trend_df.empty)
        dates = trend_df["invoice_date"].tolist()
        self.assertIn("2026-10-15", dates)
        self.assertNotIn("2026-09-20", dates)

    def test_top_selling_products_ranking(self):
        """
        Top products ranking accurately orders products by revenue.
        """
        top_df = get_top_selling_products(category_id=self.cat_sweets_id)
        self.assertFalse(top_df.empty)
        top_name = top_df.iloc[0]["product_name"]
        self.assertIn(top_name, ["TEST Kaju Katli", "TEST Gulab Jamun"])

    def test_stock_status_breakdown_categories(self):
        """
        Stock health breakdown correctly tags 'Low Stock' vs 'In Stock'.
        """
        breakdown_df = get_stock_status_breakdown(category_id=self.cat_sweets_id)
        self.assertEqual(len(breakdown_df), 2)
        kaju_row = breakdown_df[breakdown_df["product_id"] == self.prod_kaju_id].iloc[0]
        jamun_row = breakdown_df[breakdown_df["product_id"] == self.prod_jamun_id].iloc[0]
        self.assertEqual(kaju_row["stock_status"], "Low Stock")
        self.assertEqual(jamun_row["stock_status"], "In Stock")

    def test_empty_database_and_sample_data_detection(self):
        """
        Verify that database state correctly detects product and invoice counts,
        and distinguishes between empty and sample populated states.
        """
        state = check_database_state()
        self.assertIn("is_empty", state)
        self.assertIn("product_count", state)
        self.assertIn("invoice_count", state)
        self.assertIn("is_sample_data", state)
        self.assertGreater(state["product_count"], 0)
        self.assertGreater(state["invoice_count"], 0)


if __name__ == "__main__":
    unittest.main()
