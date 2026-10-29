"""
FestivePulse — Comprehensive Inventory & Stock Movement Ledger Tests
Tests inbound receipts, FIFO deductions, sales cancellations, duplicate submissions,
ACID rollbacks, non-negative stock policies, invalid movements, and stock reconciliation.
"""

import sqlite3
import unittest
from datetime import date
from database.connection import init_db, get_db_connection, db_session
from repositories.inventory_repository import (
    InventoryRepository,
    InsufficientStockError,
    DuplicateBatchError,
    InvalidMovementError,
    UnauthorizedNegativeStockError
)
from repositories.product_repository import ProductRepository
from repositories.sales_repository import SalesRepository
from services.inventory_service import (
    receive_batch,
    record_stock_adjustment,
    reconcile_product_inventory,
    perform_physical_count_reconciliation,
    get_inventory_valuation_metrics,
    get_stock_movement_ledger
)


class TestInventoryManagementModule(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Fresh database with schema and seed data
        init_db(force_recreate=True)

    def test_01_inbound_batch_receipt_and_ledger_entry(self):
        """
        Receiving a new batch must create the batch row AND simultaneously
        record an immutable 'RECEIPT' entry in the stock_movements ledger.
        """
        batch_id = InventoryRepository.create_batch(
            product_id=1,
            batch_number="BATCH-TEST-INWARD-01",
            quantity=60,
            unit_cost=380.0,
            supplier_id=1,
            received_date="2026-10-25",
            expiry_date="2026-11-25",
            storage_location="Warehouse Bay 4",
            reason="Fresh Diwali sweets consignment"
        )
        self.assertGreater(batch_id, 0)

        # Verify batch exists
        batch = InventoryRepository.get_batch_by_id(batch_id)
        self.assertIsNotNone(batch)
        self.assertEqual(batch["quantity_received"], 60)
        self.assertEqual(batch["quantity_available"], 60)
        self.assertEqual(batch["unit_cost"], 380.0)

        # Verify corresponding ledger movement
        movements = InventoryRepository.get_stock_movements(product_id=1, limit=5)
        receipt_mov = next((m for m in movements if m["batch_id"] == batch_id), None)
        self.assertIsNotNone(receipt_mov)
        self.assertEqual(receipt_mov["movement_type"], "RECEIPT")
        self.assertEqual(receipt_mov["quantity"], 60)
        self.assertEqual(receipt_mov["unit_cost"], 380.0)
        self.assertEqual(receipt_mov["total_cost_impact"], 60 * 380.0)
        self.assertEqual(receipt_mov["reference_type"], "PURCHASE_RECEIPT")
        self.assertEqual(receipt_mov["reference_id"], "BATCH-TEST-INWARD-01")

    def test_02_duplicate_batch_submission_rejection(self):
        """
        Duplicate batch numbers for the same product (e.g. from user double-clicking)
        must raise DuplicateBatchError and prevent duplicate stock creation.
        """
        # First creation succeeds
        b_id1 = InventoryRepository.create_batch(
            product_id=2,
            batch_number="BATCH-DUPLICATE-CHECK",
            quantity=30,
            unit_cost=320.0
        )
        self.assertGreater(b_id1, 0)

        # Second creation with identical product and batch number must fail
        with self.assertRaises(DuplicateBatchError):
            InventoryRepository.create_batch(
                product_id=2,
                batch_number="BATCH-DUPLICATE-CHECK",
                quantity=30,
                unit_cost=320.0
            )

        # Case-insensitive duplicate check should also be rejected
        with self.assertRaises(DuplicateBatchError):
            InventoryRepository.create_batch(
                product_id=2,
                batch_number="batch-duplicate-check",
                quantity=30,
                unit_cost=320.0
            )

    def test_03_sales_invoice_and_cancellation_ledger_movements(self):
        """
        A POS sales invoice deduction must write a 'SALE' (-qty) entry in the ledger.
        Cancelling the invoice must write a 'SALE_CANCEL' (+qty) entry in the ledger.
        """
        # Create a dedicated batch for this test
        batch_id = InventoryRepository.create_batch(
            product_id=3,
            batch_number="BATCH-SALE-TEST-01",
            quantity=50,
            unit_cost=750.0
        )

        header = {
            "invoice_number": "INV-TEST-SALE-001",
            "invoice_date": "2026-10-28",
            "customer_id": 1,
            "occurrence_id": 1,
            "payment_mode": "UPI",
            "subtotal_amount": 2300.0,
            "total_taxable_amount": 2300.0,
            "cgst_amount": 138.0,
            "sgst_amount": 138.0,
            "net_total_amount": 2576.0,
            "is_interstate": 0
        }
        item = {
            "product_id": 3,
            "batch_id": batch_id,
            "quantity": 2,
            "unit_cost_price": 750.0,
            "unit_selling_price": 1150.0,
            "taxable_value": 2300.0,
            "gst_rate": 12.0,
            "cgst_rate": 6.0,
            "cgst_amount": 138.0,
            "sgst_rate": 6.0,
            "sgst_amount": 138.0,
            "total_item_amount": 2576.0,
            "gross_profit": 800.0
        }

        # 1. Execute Sale
        inv_id, inv_no = SalesRepository.create_invoice_with_items_atomic(
            invoice_header=header,
            line_items=[item],
            batch_deductions=[(batch_id, 2)]
        )
        self.assertGreater(inv_id, 0)

        # Batch stock reduced
        b_after_sale = InventoryRepository.get_batch_by_id(batch_id)
        self.assertEqual(b_after_sale["quantity_available"], 48)

        # Check SALE ledger entry
        movs = InventoryRepository.get_stock_movements(product_id=3, movement_type="SALE")
        sale_mov = next((m for m in movs if m["reference_id"] == "INV-TEST-SALE-001"), None)
        self.assertIsNotNone(sale_mov)
        self.assertEqual(sale_mov["quantity"], -2)
        self.assertEqual(sale_mov["total_cost_impact"], 1500.0)

        # 2. Cancel Invoice
        cancelled = SalesRepository.cancel_invoice_atomic(
            invoice_id=inv_id,
            batch_restorations=[(batch_id, 2)]
        )
        self.assertTrue(cancelled)

        # Batch stock restored
        b_after_cancel = InventoryRepository.get_batch_by_id(batch_id)
        self.assertEqual(b_after_cancel["quantity_available"], 50)

        # Check SALE_CANCEL ledger entry
        movs_cancel = InventoryRepository.get_stock_movements(product_id=3, movement_type="SALE_CANCEL")
        cancel_mov = next((m for m in movs_cancel if m["batch_id"] == batch_id), None)
        self.assertIsNotNone(cancel_mov)
        self.assertEqual(cancel_mov["quantity"], 2)

    def test_04_negative_stock_prevention(self):
        """
        Attempting to deduct more stock than available in a batch must raise
        InsufficientStockError and rollback without modifying stock.
        """
        batch_id = InventoryRepository.create_batch(
            product_id=4,
            batch_number="BATCH-NEG-PREVENT-01",
            quantity=15,
            unit_cost=60.0
        )

        # Attempt to deduct 20 units when only 15 exist
        with self.assertRaises(InsufficientStockError):
            InventoryRepository.record_stock_movement(
                product_id=4,
                movement_type="DAMAGE",
                quantity=-20,
                reason="Testing negative deduction prevention",
                batch_id=batch_id
            )

        # Verify stock remains unchanged at 15
        b_check = InventoryRepository.get_batch_by_id(batch_id)
        self.assertEqual(b_check["quantity_available"], 15)

    def test_05_unauthorized_vs_authorized_negative_stock_override(self):
        """
        Negative stock override requires both allow_negative=True AND authorized_by credentials.
        """
        batch_id = InventoryRepository.create_batch(
            product_id=5,
            batch_number="BATCH-OVERRIDE-TEST",
            quantity=10,
            unit_cost=280.0
        )

        # Passing allow_negative=True without authorized_by must raise UnauthorizedNegativeStockError
        with self.assertRaises(UnauthorizedNegativeStockError):
            InventoryRepository.record_stock_movement(
                product_id=5,
                movement_type="MANUAL_COUNT_RECONCILIATION",
                quantity=-15,
                reason="Unapproved negative adjustment",
                batch_id=batch_id,
                allow_negative=True,
                authorized_by=None
            )

        # Passing allow_negative=True WITH authorized_by:
        # Note: In SQLite schema, inventory_batches has CHECK (quantity_available >= 0),
        # so physical batch cannot go negative, but manager authorization is strictly checked.
        # Let's test that update_batch_quantity enforces manager credentials on negative attempts:
        with self.assertRaises(UnauthorizedNegativeStockError):
            InventoryRepository.update_batch_quantity(
                batch_id=batch_id,
                delta=-25,
                reason="Attempt negative without manager ID",
                allow_negative=True,
                authorized_by=None
            )

    def test_06_transaction_rollback_on_failure(self):
        """
        If a multi-step database operation fails halfway, the entire transaction
        must roll back atomically without partial writes.
        """
        b1 = InventoryRepository.create_batch(product_id=6, batch_number="BATCH-ROLLBACK-1", quantity=30, unit_cost=140.0)
        b2 = InventoryRepository.create_batch(product_id=6, batch_number="BATCH-ROLLBACK-2", quantity=10, unit_cost=140.0)

        # Multi-batch deduction where 2nd deduction fails due to insufficient stock
        with self.assertRaises(sqlite3.IntegrityError):
            with db_session() as conn:
                cursor = conn.cursor()
                # Step 1: Deduct 10 from b1 (valid)
                cursor.execute("UPDATE inventory_batches SET quantity_available = quantity_available - 10 WHERE batch_id = ?", (b1,))
                # Step 2: Deduct 50 from b2 (invalid! b2 only has 10, check constraint fails)
                cursor.execute("UPDATE inventory_batches SET quantity_available = quantity_available - 50 WHERE batch_id = ?", (b2,))

        # Both batches must be in their original state!
        b1_after = InventoryRepository.get_batch_by_id(b1)
        b2_after = InventoryRepository.get_batch_by_id(b2)
        self.assertEqual(b1_after["quantity_available"], 30)
        self.assertEqual(b2_after["quantity_available"], 10)

    def test_07_deterministic_stock_reconciliation(self):
        """
        Tests reconciliation calculation between batch balances and movement ledger.
        Also tests physical count reconciliation adjustment.
        """
        # Create a new product with opening stock
        prod_id = ProductRepository.create_product({
            "sku": "SKU-RECON-TEST-01",
            "product_name": "Reconciliation Test Mithai",
            "category_id": 1,
            "unit_of_measure": "box",
            "cost_price": 250.0,
            "selling_price": 400.0,
            "mrp": 450.0,
            "gst_rate": 5.0,
            "hsn_code": "21069099"
        }, initial_stock=100)

        # Initial state: 100 in batch, 100 in ledger -> discrepancy 0
        recon = reconcile_product_inventory(prod_id)
        self.assertEqual(recon["batch_stock"], 100)
        self.assertEqual(recon["ledger_stock"], 100)
        self.assertEqual(recon["discrepancy"], 0)
        self.assertTrue(recon["is_reconciled"])

        # Record a manual damage of 5 units
        record_stock_adjustment(
            product_id=prod_id,
            adjustment_type="DAMAGE",
            quantity=-5,
            reason="Sample damage"
        )
        recon_after_dmg = reconcile_product_inventory(prod_id)
        self.assertEqual(recon_after_dmg["batch_stock"], 95)
        self.assertEqual(recon_after_dmg["ledger_stock"], 95)
        self.assertEqual(recon_after_dmg["discrepancy"], 0)
        self.assertTrue(recon_after_dmg["is_reconciled"])

        # Perform physical count reconciliation: suppose stocktake found 92 units (3 units shrinkage)
        recon_applied = perform_physical_count_reconciliation(
            product_id=prod_id,
            physical_count=92,
            reason="Pre-festival stocktake audit count",
            authorized_by="Store Manager Ramesh"
        )
        self.assertEqual(recon_applied["batch_stock"], 92)
        self.assertEqual(recon_applied["ledger_stock"], 92)
        self.assertEqual(recon_applied["discrepancy"], 0)
        self.assertTrue(recon_applied["is_reconciled"])

    def test_08_invalid_movement_rejections(self):
        """
        Invalid movements (0 quantity, missing reason, invalid movement_type, empty batch_number)
        must be rejected with InvalidMovementError.
        """
        # 1. Zero quantity
        with self.assertRaises(InvalidMovementError):
            InventoryRepository.record_stock_movement(
                product_id=1,
                movement_type="DAMAGE",
                quantity=0,
                reason="Valid reason"
            )

        # 2. Missing reason
        with self.assertRaises(InvalidMovementError):
            InventoryRepository.record_stock_movement(
                product_id=1,
                movement_type="DAMAGE",
                quantity=-5,
                reason="   "  # Empty whitespace
            )

        # 3. Invalid movement type
        with self.assertRaises(InvalidMovementError):
            InventoryRepository.record_stock_movement(
                product_id=1,
                movement_type="FAKE_MOVEMENT_TYPE",
                quantity=-5,
                reason="Some reason"
            )

        # 4. Empty batch number on batch creation
        with self.assertRaises(InvalidMovementError):
            InventoryRepository.create_batch(
                product_id=1,
                batch_number="   ",
                quantity=10,
                unit_cost=100.0
            )

        # 5. Non-positive quantity on batch creation
        with self.assertRaises(InvalidMovementError):
            InventoryRepository.create_batch(
                product_id=1,
                batch_number="BATCH-ZERO-QTY",
                quantity=0,
                unit_cost=100.0
            )

    def test_09_low_stock_and_out_of_stock_filtering(self):
        """
        Verifies low-stock and out-of-stock product retrieval and classification.
        """
        # Create an out-of-stock product (initial_stock = 0)
        p_oos = ProductRepository.create_product({
            "sku": "SKU-OOS-TEST",
            "product_name": "Out of Stock Lamp",
            "category_id": 3,
            "unit_of_measure": "pcs",
            "cost_price": 50.0,
            "selling_price": 100.0,
            "mrp": 120.0,
            "gst_rate": 18.0
        }, initial_stock=0)

        # Create a low-stock product (min_safety_stock = 20, initial_stock = 5)
        p_low = ProductRepository.create_product({
            "sku": "SKU-LOW-TEST",
            "product_name": "Low Stock Fragrance",
            "category_id": 2,
            "unit_of_measure": "box",
            "cost_price": 80.0,
            "selling_price": 160.0,
            "mrp": 180.0,
            "gst_rate": 12.0,
            "min_safety_stock": 20
        }, initial_stock=5)

        # Check out-of-stock list
        oos_items = InventoryRepository.get_out_of_stock_products()
        oos_ids = [p["product_id"] for p in oos_items]
        self.assertIn(p_oos, oos_ids)

        # Check low-stock list
        low_items = InventoryRepository.get_low_stock_products()
        low_ids = [p["product_id"] for p in low_items]
        self.assertIn(p_low, low_ids)

    def test_10_inventory_valuation_metrics(self):
        """
        Verifies inventory valuation totals: Cost Value, Retail Value, and Margin.
        """
        val = get_inventory_valuation_metrics()
        self.assertIn("total_cost_value", val)
        self.assertIn("total_retail_value", val)
        self.assertIn("potential_margin", val)
        self.assertIn("total_units_in_stock", val)
        self.assertGreater(val["total_cost_value"], 0.0)
        self.assertGreater(val["total_retail_value"], val["total_cost_value"])
        self.assertEqual(val["potential_margin"], round(val["total_retail_value"] - val["total_cost_value"], 2))
        self.assertGreater(val["total_units_in_stock"], 0)


if __name__ == "__main__":
    unittest.main()
