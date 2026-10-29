"""
FestivePulse — Database, Inventory & Transactional Unit Tests
"""

import unittest
from database.connection import init_db, query_df
from services.sales_service import create_sales_invoice, cancel_sales_invoice
from services.demand_engine import estimate_product_demand
from services.stock_recommender import get_stock_recommendation_for_product


class TestFestivePulseDBAndInventory(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Initialize fresh test database
        init_db(force_recreate=True)

    def test_database_tables_exist(self):
        prods = query_df("SELECT * FROM products")
        self.assertGreater(len(prods), 0)

        fests = query_df("SELECT * FROM festivals")
        self.assertGreater(len(fests), 0)

        occs = query_df("SELECT * FROM festival_occurrences")
        self.assertGreater(len(occs), 0)

    def test_deterministic_demand_estimation(self):
        # Product 1 (Kaju Katli) had historical 2025 sales
        est = estimate_product_demand(product_id=1, target_occurrence_id=10, growth_multiplier=1.20)
        self.assertEqual(est["method"], "HISTORICAL_YOY")
        self.assertGreater(est["estimated_demand_units"], 0)
        self.assertEqual(est["multiplier"], 1.20)

    def test_stock_recommendation_math(self):
        # Reorder advice for product 1
        rec = get_stock_recommendation_for_product(product_id=1, occurrence_id=10, growth_multiplier=1.20)
        self.assertIn("recommended_order_quantity", rec)
        self.assertIn("safety_stock", rec)
        self.assertIn("reorder_point", rec)
        self.assertGreaterEqual(rec["safety_stock"], 2)

    def test_sales_invoice_creation_and_fifo_stock_depletion(self):
        # Check stock before
        prods_before = query_df("SELECT current_stock FROM (SELECT p.product_id, COALESCE(SUM(b.quantity_available), 0) as current_stock FROM products p LEFT JOIN inventory_batches b ON p.product_id = b.product_id WHERE p.product_id = 1 GROUP BY p.product_id)")
        initial_stock = int(prods_before.iloc[0]["current_stock"])

        # Sell 5 units
        inv_id, inv_num = create_sales_invoice(
            customer_id=1,
            payment_mode="UPI",
            items=[{"product_id": 1, "quantity": 5, "selling_price": 550.0, "discount_pct": 0.0}]
        )
        self.assertIsNotNone(inv_id)
        self.assertTrue(inv_num.startswith("INV-"))

        # Verify stock decreased by 5
        prods_after = query_df("SELECT current_stock FROM (SELECT p.product_id, COALESCE(SUM(b.quantity_available), 0) as current_stock FROM products p LEFT JOIN inventory_batches b ON p.product_id = b.product_id WHERE p.product_id = 1 GROUP BY p.product_id)")
        after_stock = int(prods_after.iloc[0]["current_stock"])
        self.assertEqual(after_stock, initial_stock - 5)

        # Cancel invoice and verify stock restoration
        cancel_sales_invoice(inv_id, reason="Test Cancel")
        prods_restored = query_df("SELECT current_stock FROM (SELECT p.product_id, COALESCE(SUM(b.quantity_available), 0) as current_stock FROM products p LEFT JOIN inventory_batches b ON p.product_id = b.product_id WHERE p.product_id = 1 GROUP BY p.product_id)")
        restored_stock = int(prods_restored.iloc[0]["current_stock"])
        self.assertEqual(restored_stock, initial_stock)

    def test_insufficient_stock_raises_error(self):
        # Attempt to sell 99999 units of product 1
        with self.assertRaises(ValueError) as ctx:
            create_sales_invoice(
                customer_id=1,
                payment_mode="CASH",
                items=[{"product_id": 1, "quantity": 99999, "selling_price": 550.0}]
            )
        self.assertIn("Insufficient stock", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
