"""
FestivePulse — Festival Stock Planning Unit Test Suite
Comprehensive tests validating deterministic formulas, budget limit analysis,
zero costs, stock sufficiency, insufficient history, pack rounding, and manual overrides.
- Suggested purchase quantity = max(0, planned demand + safety stock - usable stock)
- Estimated purchase cost = purchase quantity * unit cost
- Zero automated order placement guardrails
- 100% Non-AI
"""

import unittest
import math
from datetime import date, timedelta
from database.connection import init_db, db_session, get_db_connection
from services.stock_planning_service import (
    get_usable_stock,
    compute_product_stock_plan,
    analyze_budget_excess,
    generate_festival_stock_plan_table
)


class TestFestivalStockPlanning(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        """Creates clean, isolated database fixtures for stock planning tests."""
        with db_session() as conn:
            cursor = conn.cursor()

            # Clean fixtures
            cursor.execute("DELETE FROM sales_items WHERE invoice_id IN (SELECT invoice_id FROM sales_invoices WHERE invoice_number LIKE 'PLAN-INV-%')")
            cursor.execute("DELETE FROM sales_invoices WHERE invoice_number LIKE 'PLAN-INV-%'")
            cursor.execute("DELETE FROM inventory_batches WHERE batch_number LIKE 'PLAN-BATCH-%'")
            cursor.execute("DELETE FROM festival_occurrences WHERE notes LIKE 'PLAN_TEST_%'")
            cursor.execute("DELETE FROM festivals WHERE festival_code LIKE 'PLAN_TEST_%'")
            cursor.execute("DELETE FROM products WHERE sku LIKE 'PLAN-SKU-%'")
            cursor.execute("DELETE FROM product_categories WHERE category_name LIKE 'PLAN_CAT_%'")

            # 1. Test Category
            cursor.execute("""
                INSERT INTO product_categories (category_name, default_gst_rate, description)
                VALUES ('PLAN_CAT_SWEETS', 5.0, 'Stock Planning Test Sweets')
            """)
            self.cat_id = cursor.lastrowid

            # 2. Test Products
            # Product 1: Standard product with pack_size=10, cost=100.0, safety=20
            cursor.execute("""
                INSERT INTO products (
                    sku, barcode, product_name, category_id, unit_of_measure,
                    cost_price, selling_price, mrp, gst_rate, min_safety_stock, reorder_quantity, is_active
                ) VALUES ('PLAN-SKU-001', '8909999001', 'Plan Test Kaju Katli', ?, 'box', 100.0, 200.0, 220.0, 5.0, 20, 10, 1)
            """, (self.cat_id,))
            self.prod_1_id = cursor.lastrowid

            # Product 2: Zero cost item (promotional free gift sample, cost=0.0)
            cursor.execute("""
                INSERT INTO products (
                    sku, barcode, product_name, category_id, unit_of_measure,
                    cost_price, selling_price, mrp, gst_rate, min_safety_stock, reorder_quantity, is_active
                ) VALUES ('PLAN-SKU-002', '8909999002', 'Plan Test Free Gift Box', ?, 'box', 0.0, 0.0, 0.0, 0.0, 15, 1, 1)
            """, (self.cat_id,))
            self.prod_zero_cost_id = cursor.lastrowid

            # Product 3: Cold Start (Zero Sales History)
            cursor.execute("""
                INSERT INTO products (
                    sku, barcode, product_name, category_id, unit_of_measure,
                    cost_price, selling_price, mrp, gst_rate, min_safety_stock, reorder_quantity, is_active
                ) VALUES ('PLAN-SKU-003', '8909999003', 'Plan Test Cold Start Peda', ?, 'box', 150.0, 250.0, 280.0, 5.0, 10, 5, 1)
            """, (self.cat_id,))
            self.prod_cold_id = cursor.lastrowid

            # Product 4: High Value Luxury Item (cost=1000.0) for budget excess tests
            cursor.execute("""
                INSERT INTO products (
                    sku, barcode, product_name, category_id, unit_of_measure,
                    cost_price, selling_price, mrp, gst_rate, min_safety_stock, reorder_quantity, is_active
                ) VALUES ('PLAN-SKU-004', '8909999004', 'Plan Test Luxury Hamper', ?, 'box', 1000.0, 1800.0, 2000.0, 5.0, 5, 1, 1)
            """, (self.cat_id,))
            self.prod_luxury_id = cursor.lastrowid

            # 3. Test Festival Definition & Occurrences
            cursor.execute("""
                INSERT INTO festivals (festival_name, festival_code, primary_regions, typical_surge_multiplier)
                VALUES ('Plan Test Diwali', 'PLAN_TEST_DIWALI', '["National"]', 2.0)
            """)
            self.fest_id = cursor.lastrowid

            # 2025 Historical Occurrence (10 days: 2025-10-15 to 2025-10-24)
            cursor.execute("""
                INSERT INTO festival_occurrences (
                    festival_id, year, prep_start_date, campaign_start_date, campaign_end_date,
                    peak_start_date, festival_date, notes
                ) VALUES (?, 2025, '2025-10-01', '2025-10-15', '2025-10-24', '2025-10-20', '2025-10-24', 'PLAN_TEST_2025')
            """, (self.fest_id,))
            self.occ_2025_id = cursor.lastrowid

            # 2026 Target Occurrence (10 days: 2026-10-25 to 2026-11-03)
            cursor.execute("""
                INSERT INTO festival_occurrences (
                    festival_id, year, prep_start_date, campaign_start_date, campaign_end_date,
                    peak_start_date, festival_date, notes
                ) VALUES (?, 2026, '2026-10-01', '2026-10-25', '2026-11-03', '2026-10-30', '2026-11-03', 'PLAN_TEST_2026')
            """, (self.fest_id,))
            self.occ_2026_id = cursor.lastrowid

            # 4. Populate Historical Sales for Product 1 (50 units in 2025 Diwali)
            cursor.execute("""
                INSERT INTO sales_invoices (
                    invoice_number, invoice_date, occurrence_id, payment_mode,
                    subtotal_amount, total_taxable_amount, net_total_amount, status
                ) VALUES ('PLAN-INV-1', '2025-10-18', ?, 'CASH', 10000.0, 10000.0, 10500.0, 'COMPLETED')
            """, (self.occ_2025_id,))
            inv_id = cursor.lastrowid

            cursor.execute("""
                INSERT INTO sales_items (
                    invoice_id, product_id, quantity, unit_cost_price, unit_selling_price,
                    taxable_value, gst_rate, total_item_amount, gross_profit
                ) VALUES (?, ?, 50, 100.0, 200.0, 10000.0, 5.0, 10500.0, 5000.0)
            """, (inv_id, self.prod_1_id))

            # 5. Populate Inventory Batches for Product 1:
            # Batch 1: Usable unexpired stock = 30 units
            cursor.execute("""
                INSERT INTO inventory_batches (
                    product_id, batch_number, received_date, expiry_date,
                    quantity_received, quantity_available, unit_cost
                ) VALUES (?, 'PLAN-BATCH-001', '2026-10-01', DATE('now', '+30 days'), 50, 30, 100.0)
            """, (self.prod_1_id,))

            # Batch 2: Expired stock = 20 units (MUST NOT BE COUNTED AS USABLE)
            cursor.execute("""
                INSERT INTO inventory_batches (
                    product_id, batch_number, received_date, expiry_date,
                    quantity_received, quantity_available, unit_cost
                ) VALUES (?, 'PLAN-BATCH-EXPIRED', '2026-08-01', DATE('now', '-5 days'), 20, 20, 100.0)
            """, (self.prod_1_id,))

    def tearDown(self):
        """Cleans test fixtures."""
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM sales_items WHERE invoice_id IN (SELECT invoice_id FROM sales_invoices WHERE invoice_number LIKE 'PLAN-INV-%')")
            cursor.execute("DELETE FROM sales_invoices WHERE invoice_number LIKE 'PLAN-INV-%'")
            cursor.execute("DELETE FROM inventory_batches WHERE batch_number LIKE 'PLAN-BATCH-%'")
            cursor.execute("DELETE FROM festival_occurrences WHERE notes LIKE 'PLAN_TEST_%'")
            cursor.execute("DELETE FROM festivals WHERE festival_code LIKE 'PLAN_TEST_%'")
            cursor.execute("DELETE FROM products WHERE sku LIKE 'PLAN-SKU-%'")
            cursor.execute("DELETE FROM product_categories WHERE category_name LIKE 'PLAN_CAT_%'")

    def test_usable_stock_excludes_expired_batches(self):
        """
        Tests that get_usable_stock only returns unexpired, positive inventory batches.
        Product 1 has Batch 1 (30 usable) and Batch 2 (20 expired).
        Usable stock must be strictly 30.
        """
        usable = get_usable_stock(self.prod_1_id)
        self.assertEqual(usable, 30)

    def test_deterministic_purchase_quantity_and_rounding(self):
        """
        Tests: Suggested purchase quantity = max(0, planned demand + safety stock - usable stock)
        Product 1:
          - Planned Demand: 50 units (historical 2025 run-rate over 10 days * 1.0 growth = 50 units)
          - Configured Safety Stock: 20 units
          - Usable Stock: 30 units
          - Gross Required = 50 + 20 = 70 units
          - Raw Net to Order = max(0, 70 - 30) = 40 units
          - Pack Size = 10 -> ceil(40 / 10) * 10 = 40 units
          - Unit Cost = 100.0 -> Estimated Cost = 40 * 100.0 = 4000.0
        """
        plan = compute_product_stock_plan(
            product_id=self.prod_1_id,
            occurrence_id=self.occ_2026_id,
            growth_multiplier=1.0
        )

        self.assertEqual(plan["planned_demand"], 50)
        self.assertEqual(plan["safety_stock"], 20)
        self.assertEqual(plan["usable_stock"], 30)
        self.assertEqual(plan["raw_suggested_quantity"], 40)
        self.assertEqual(plan["original_suggested_quantity"], 40)
        self.assertEqual(plan["edited_purchase_quantity"], 40)
        self.assertEqual(plan["original_procurement_cost"], 4000.0)
        self.assertEqual(plan["planned_procurement_cost"], 4000.0)
        self.assertFalse(plan["is_sufficient"])
        self.assertEqual(plan["procurement_status"], "ORDER_REQUIRED")
        self.assertIn("max(0, 50 demand + 20 safety - 30 usable)", plan["arithmetic_breakdown"])

    def test_pack_size_rounding(self):
        """
        Tests pack size rounding:
        If raw net required is 23 units and pack size is 10:
        Suggested purchase quantity must round up to ceil(23 / 10) * 10 = 30 units.
        """
        # Add 17 more units to inventory -> usable stock = 47 units
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO inventory_batches (
                    product_id, batch_number, received_date, expiry_date,
                    quantity_received, quantity_available, unit_cost
                ) VALUES (?, 'PLAN-BATCH-002', '2026-10-01', DATE('now', '+30 days'), 17, 17, 100.0)
            """, (self.prod_1_id,))

        # Gross Required = 50 + 20 = 70 units
        # Usable Stock = 30 + 17 = 47 units
        # Raw Suggested = 70 - 47 = 23 units
        # Pack Size = 10 -> Rounded = ceil(23 / 10) * 10 = 30 units
        plan = compute_product_stock_plan(
            product_id=self.prod_1_id,
            occurrence_id=self.occ_2026_id,
            growth_multiplier=1.0
        )
        self.assertEqual(plan["usable_stock"], 47)
        self.assertEqual(plan["raw_suggested_quantity"], 23)
        self.assertEqual(plan["original_suggested_quantity"], 30)
        self.assertEqual(plan["original_procurement_cost"], 30 * 100.0)

    def test_stock_sufficiency(self):
        """
        Tests that when usable stock >= planned demand + safety stock:
        Suggested purchase quantity is 0 and status is SUFFICIENT_STOCK.
        """
        # Add 100 units to inventory -> usable stock = 130 units
        # Gross Required = 50 + 20 = 70 units <= 130 usable stock
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO inventory_batches (
                    product_id, batch_number, received_date, expiry_date,
                    quantity_received, quantity_available, unit_cost
                ) VALUES (?, 'PLAN-BATCH-SURPLUS', '2026-10-01', DATE('now', '+30 days'), 100, 100, 100.0)
            """, (self.prod_1_id,))

        plan = compute_product_stock_plan(
            product_id=self.prod_1_id,
            occurrence_id=self.occ_2026_id,
            growth_multiplier=1.0
        )
        self.assertEqual(plan["usable_stock"], 130)
        self.assertEqual(plan["raw_suggested_quantity"], 0)
        self.assertEqual(plan["original_suggested_quantity"], 0)
        self.assertEqual(plan["original_procurement_cost"], 0.0)
        self.assertTrue(plan["is_sufficient"])
        self.assertEqual(plan["procurement_status"], "SUFFICIENT_STOCK")
        self.assertIn("Sufficient Stock", plan["status_badge"])

    def test_zero_costs(self):
        """
        Tests that products with recorded unit cost of 0.0 (promotional/free sample)
        calculate cost = 0.0 without errors or division by zero.
        """
        plan = compute_product_stock_plan(
            product_id=self.prod_zero_cost_id,
            occurrence_id=self.occ_2026_id,
            growth_multiplier=1.0,
            configured_safety_stock=15
        )

        self.assertEqual(plan["unit_cost"], 0.0)
        self.assertEqual(plan["original_procurement_cost"], 0.0)
        self.assertEqual(plan["planned_procurement_cost"], 0.0)
        self.assertEqual(plan["safety_stock"], 15)
        # 0 demand + 15 safety - 0 usable = 15 units
        self.assertEqual(plan["original_suggested_quantity"], 15)

    def test_insufficient_history_handling(self):
        """
        Tests that products with insufficient history:
        - Planned demand defaults to 0 (no fake numbers invented)
        - Suggested purchase quantity = max(0, 0 + safety stock - usable stock)
        - If manual demand estimate is supplied, uses manual demand
        """
        # Case A: Without manual override
        plan_no_override = compute_product_stock_plan(
            product_id=self.prod_cold_id,
            occurrence_id=self.occ_2026_id
        )
        self.assertEqual(plan_no_override["demand_status"], "INSUFFICIENT_HISTORICAL_DATA")
        self.assertEqual(plan_no_override["planned_demand"], 0)
        # Safety stock = 10 (from min_safety_stock), Usable stock = 0 -> Suggested = 10
        self.assertEqual(plan_no_override["safety_stock"], 10)
        self.assertEqual(plan_no_override["original_suggested_quantity"], 10)

        # Case B: With manual planning estimate (e.g. 5.0 units/day for 10 days = 50 units)
        plan_with_manual = compute_product_stock_plan(
            product_id=self.prod_cold_id,
            occurrence_id=self.occ_2026_id,
            manual_demand_override=5.0
        )
        self.assertEqual(plan_with_manual["planned_demand"], 50)
        # Gross = 50 + 10 = 60 units
        self.assertEqual(plan_with_manual["original_suggested_quantity"], 60)
        self.assertEqual(plan_with_manual["original_procurement_cost"], 60 * 150.0)

    def test_manual_overrides_side_by_side(self):
        """
        Tests that manual overrides preserve BOTH the original calculated quantity
        and the edited quantity side-by-side, along with override deltas.
        """
        # Original calculation for Product 1 is 40 units (cost = 4000.0)
        # User manually overrides purchase quantity to 70 units
        plan = compute_product_stock_plan(
            product_id=self.prod_1_id,
            occurrence_id=self.occ_2026_id,
            growth_multiplier=1.0,
            manual_purchase_override=70
        )

        self.assertTrue(plan["is_overridden"])
        self.assertEqual(plan["original_suggested_quantity"], 40)
        self.assertEqual(plan["edited_purchase_quantity"], 70)
        self.assertEqual(plan["override_delta"], 30)
        self.assertEqual(plan["original_procurement_cost"], 4000.0)
        self.assertEqual(plan["planned_procurement_cost"], 7000.0)
        self.assertEqual(plan["procurement_status"], "OVERRIDDEN")

    def test_budget_limits_and_top_contributors(self):
        """
        Tests budget constraint evaluation and top-contributor excess analysis:
        Product 1: 40 units * 100.0 = 4,000.0
        Product 4 (Luxury): 10 units * 1000.0 = 10,000.0
        Total Planned Cost = 14,000.0
        Available Budget = 10,000.0
        Expected:
          - Budget Exceeded by 4,000.0 (140.0% utilization)
          - Top Contributor is Product 4 (71.4% of total plan)
          - Narrative clearly names Product 4 and explains the excess
        """
        items = [
            compute_product_stock_plan(self.prod_1_id, self.occ_2026_id, growth_multiplier=1.0),
            compute_product_stock_plan(self.prod_luxury_id, self.occ_2026_id, growth_multiplier=1.0, manual_purchase_override=10)
        ]

        analysis = analyze_budget_excess(items, purchasing_budget=10000.0)

        self.assertTrue(analysis["is_budget_exceeded"])
        self.assertEqual(analysis["overrun_amount"], 4000.0)
        self.assertEqual(analysis["budget_utilization_pct"], 140.0)
        self.assertEqual(analysis["total_planned_cost"], 14000.0)

        # Top contributor must be Product 4
        top_items = analysis["top_contributors"]
        self.assertEqual(top_items[0]["product_id"], self.prod_luxury_id)
        self.assertEqual(top_items[0]["planned_cost"], 10000.0)
        self.assertAlmostEqual(top_items[0]["cost_share_pct"], 71.4, places=1)

        # Explanation narrative must highlight Product 4 and overrun
        narrative = analysis["explanation_narrative"]
        self.assertIn("Budget Exceeded by ₹4,000.00", narrative)
        self.assertIn("Plan Test Luxury Hamper", narrative)

    def test_within_budget_surplus_analysis(self):
        """
        Tests budget analysis when plan is within budget.
        Total Planned Cost = 4,000.0, Budget = 10,000.0 -> Surplus = 6,000.0.
        """
        items = [
            compute_product_stock_plan(self.prod_1_id, self.occ_2026_id, growth_multiplier=1.0)
        ]
        analysis = analyze_budget_excess(items, purchasing_budget=10000.0)

        self.assertFalse(analysis["is_budget_exceeded"])
        self.assertEqual(analysis["overrun_amount"], 0.0)
        self.assertEqual(analysis["budget_utilization_pct"], 40.0)
        self.assertIn("Plan Within Budget", analysis["explanation_narrative"])
        self.assertIn("₹6,000.00", analysis["explanation_narrative"])

    def test_never_automatically_places_orders(self):
        """
        Guardrail Test:
        Verifies that running the stock planning service NEVER modifies database tables
        or places automated purchase orders.
        """
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) AS c FROM inventory_batches")
            batches_before = cursor.fetchone()["c"]

            cursor.execute("SELECT COUNT(*) AS c FROM sales_invoices")
            inv_before = cursor.fetchone()["c"]

            cursor.execute("SELECT COUNT(*) AS c FROM stock_movements")
            movements_before = cursor.fetchone()["c"]
        finally:
            conn.close()

        # Run stock planning table generation with manual overrides
        df, analysis = generate_festival_stock_plan_table(
            occurrence_id=self.occ_2026_id,
            purchasing_budget=50000.0,
            growth_multiplier=1.15,
            manual_purchase_overrides={self.prod_1_id: 100}
        )
        self.assertFalse(df.empty)

        # Verify zero writes in database
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) AS c FROM inventory_batches")
            self.assertEqual(cursor.fetchone()["c"], batches_before)

            cursor.execute("SELECT COUNT(*) AS c FROM sales_invoices")
            self.assertEqual(cursor.fetchone()["c"], inv_before)

            cursor.execute("SELECT COUNT(*) AS c FROM stock_movements")
            self.assertEqual(cursor.fetchone()["c"], movements_before)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
