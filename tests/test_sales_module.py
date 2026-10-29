"""
FestivePulse — Comprehensive Sales Module Automated Test Suite
Tests exact Decimal line and transaction totals, discounts, GST breakdown (intra vs inter-state),
FIFO batch allocation, available stock validation, atomic stock movements, duplicate transaction
reference prevention, ACID rollbacks, safe cancellation reversals, and item-level returns.
"""

from decimal import Decimal
import unittest
import sqlite3
from datetime import date

from database.connection import init_db, get_db_connection, db_session
from repositories.product_repository import ProductRepository
from repositories.inventory_repository import InventoryRepository
from repositories.sales_repository import (
    SalesRepository,
    to_decimal,
    DuplicateTransactionError,
    InsufficientStockError,
    InvalidSaleError,
    InvalidReturnError,
    CustomerCreditLimitExceededError
)
from services.sales_service import (
    calculate_line_gst,
    create_sales_invoice,
    cancel_sales_invoice,
    process_sales_return,
    correct_sales_invoice,
    get_invoice_full_details,
    get_sales_report_df,
    get_sales_line_items_df,
    get_sales_returns_df,
    get_sales_kpis
)
from services.currency_utils import rupees_to_paise, paise_to_rupees, calculate_monetary_line


class TestSalesModule(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Fresh database initialization with clean schema and seed data
        init_db(force_recreate=True)
        cls.test_customer_id = SalesRepository.create_customer(
            name="Ramesh Sharma",
            phone="9876543210",
            email="ramesh@example.com",
            address="12 MG Road",
            city="Pune",
            state="Maharashtra",
            credit_limit=10000.0
        )
        cls.interstate_customer_id = SalesRepository.create_customer(
            name="Vikram Patel",
            phone="9812345678",
            email="vikram@example.com",
            address="45 SG Highway",
            city="Ahmedabad",
            state="Gujarat",
            credit_limit=8000.0
        )

    def test_01_calculate_line_gst_exact_decimal_precision(self):
        """
        Verify calculate_line_gst computes exact rounded GST values:
        Intra-state: 50% CGST + 50% SGST
        Inter-state: 100% IGST
        """
        # Case 1: Intra-state 18% GST on Rs. 1,000.00
        intra = calculate_line_gst(taxable_value=1000.0, gst_rate=18.0, is_interstate=False)
        self.assertEqual(intra["taxable_value"], 1000.0)
        self.assertEqual(intra["cgst_rate"], 9.0)
        self.assertEqual(intra["cgst_amount"], 90.0)
        self.assertEqual(intra["sgst_rate"], 9.0)
        self.assertEqual(intra["sgst_amount"], 90.0)
        self.assertEqual(intra["igst_amount"], 0.0)
        self.assertEqual(intra["total_line_amount"], 1180.0)

        # Case 2: Inter-state 12% GST on Rs. 2,500.50
        inter = calculate_line_gst(taxable_value=2500.50, gst_rate=12.0, is_interstate=True)
        self.assertEqual(inter["taxable_value"], 2500.50)
        self.assertEqual(inter["cgst_amount"], 0.0)
        self.assertEqual(inter["sgst_amount"], 0.0)
        self.assertEqual(inter["igst_rate"], 12.0)
        self.assertEqual(inter["igst_amount"], 300.06)
        self.assertEqual(inter["total_line_amount"], 2800.56)

    def test_02_create_sale_exact_totals_and_discounts(self):
        """
        Test sale creation with exact line-item discounts, GST computation,
        and bill-level extra discount with rounding.
        """
        # Create a dedicated test product with GST 5%
        prod_id = ProductRepository.create_product({
            "sku": "SKU-TEST-CALC-02",
            "product_name": "Test Sweets Pack 02",
            "category_id": 1,
            "unit_of_measure": "box",
            "cost_price": 350.0,
            "selling_price": 500.0,
            "mrp": 550.0,
            "gst_rate": 5.0,
            "min_safety_stock": 5,
            "reorder_quantity": 20
        })

        batch_id = InventoryRepository.create_batch(
            product_id=prod_id,
            batch_number="BATCH-SALE-DECIMAL-02",
            quantity=50,
            unit_cost=350.0,
            supplier_id=1,
            received_date="2026-10-20",
            expiry_date="2026-12-31",
            reason="Fresh stock for sale test"
        )
        self.assertGreater(batch_id, 0)

        # Sell 4 units @ Rs. 500.00 with 10% item discount and Rs. 10.00 extra bill discount
        # Gross = 4 * 500 = 2000.00
        # Line Disc = 2000.00 * 0.10 = 200.00
        # Line Taxable = 1800.00
        # CGST (2.5%) = 45.00
        # SGST (2.5%) = 45.00
        # Total line = 1890.00
        # Overall bill discount = 10.00
        # Final taxable = 1790.00
        # Net before round = 1790.00 + 45.00 + 45.00 = 1880.00
        inv_id, inv_num = create_sales_invoice(
            customer_id=self.test_customer_id,
            payment_mode="UPI",
            items=[{
                "product_id": prod_id,
                "quantity": 4,
                "selling_price": 500.0,
                "discount_pct": 10.0
            }],
            overall_discount=10.0,
            transaction_reference="UPI-UTR-99887711",
            notes="Festive gift box purchase"
        )
        self.assertGreater(inv_id, 0)
        self.assertTrue(inv_num.startswith("INV-"))

        # Verify persisted invoice
        inv = SalesRepository.get_invoice_by_id(inv_id)
        self.assertIsNotNone(inv)
        self.assertEqual(inv["payment_mode"], "UPI")
        self.assertEqual(inv["status"], "COMPLETED")
        self.assertEqual(inv["subtotal_amount"], 2000.0)
        self.assertEqual(inv["discount_amount"], 10.0)
        self.assertEqual(inv["cgst_amount"], 45.0)
        self.assertEqual(inv["sgst_amount"], 45.0)
        self.assertEqual(inv["igst_amount"], 0.0)
        self.assertEqual(inv["net_total_amount"], 1880.0)
        self.assertEqual(inv["transaction_reference"], "UPI-UTR-99887711")

        # Verify line item
        self.assertEqual(len(inv["items"]), 1)
        item = inv["items"][0]
        self.assertEqual(item["quantity"], 4)
        self.assertEqual(item["unit_selling_price"], 500.0)
        self.assertEqual(item["discount_percent"], 10.0)
        self.assertEqual(item["taxable_value"], 1800.0)
        self.assertEqual(item["total_item_amount"], 1890.0)

    def test_03_inventory_depletion_and_stock_movement_in_same_transaction(self):
        """
        Verify that a completed sale:
        1. Updates inventory batches exactly once.
        2. Inserts an immutable SALE movement with negative quantity in stock_movements.
        3. Both happen within the same atomic database transaction.
        """
        # Create a dedicated product and single batch
        prod_id = ProductRepository.create_product({
            "sku": "SKU-TEST-ATOMIC-03",
            "product_name": "Test Dedicated Product 03",
            "category_id": 1,
            "unit_of_measure": "box",
            "cost_price": 250.0,
            "selling_price": 400.0,
            "mrp": 450.0,
            "gst_rate": 5.0,
            "min_safety_stock": 5,
            "reorder_quantity": 20
        })

        batch_id = InventoryRepository.create_batch(
            product_id=prod_id,
            batch_number="BATCH-ATOMIC-03",
            quantity=20,
            unit_cost=250.0,
            supplier_id=1,
            received_date="2026-10-25",
            expiry_date="2026-12-31"
        )

        batch_before = InventoryRepository.get_batch_by_id(batch_id)
        initial_avail = batch_before["quantity_available"]
        self.assertEqual(initial_avail, 20)

        # Sell 6 units
        inv_id, inv_num = create_sales_invoice(
            customer_id=self.test_customer_id,
            payment_mode="CASH",
            items=[{"product_id": prod_id, "quantity": 6, "selling_price": 400.0}],
            transaction_reference="CASH-TXN-003"
        )

        # Verify batch was depleted by exactly 6 units
        batch_after = InventoryRepository.get_batch_by_id(batch_id)
        self.assertEqual(batch_after["quantity_available"], 14)

        # Verify stock movement entry
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM stock_movements
                WHERE reference_type = 'SALES_INVOICE' AND reference_id = ?
            """, (inv_num,))
            movements = cursor.fetchall()
            self.assertEqual(len(movements), 1)
            sm = movements[0]
            self.assertEqual(sm["movement_type"], "SALE")
            self.assertEqual(sm["quantity"], -6)
            self.assertEqual(sm["product_id"], prod_id)
            self.assertEqual(sm["batch_id"], batch_id)
        finally:
            conn.close()

    def test_04_fifo_multi_batch_allocation(self):
        """
        Verify FIFO depletion across multiple batches:
        Earlier expiring batch must be depleted first.
        """
        prod_id = ProductRepository.create_product({
            "sku": "SKU-TEST-FIFO-04",
            "product_name": "Test Dry Fruits 04",
            "category_id": 1,
            "unit_of_measure": "box",
            "cost_price": 150.0,
            "selling_price": 280.0,
            "mrp": 300.0,
            "gst_rate": 5.0,
            "min_safety_stock": 5,
            "reorder_quantity": 20
        })

        # Create Batch 1: 5 units expiring 2026-11-10
        b1_id = InventoryRepository.create_batch(
            product_id=prod_id,
            batch_number="BATCH-FIFO-A",
            quantity=5,
            unit_cost=150.0,
            supplier_id=1,
            received_date="2026-10-01",
            expiry_date="2026-11-10"
        )
        # Create Batch 2: 15 units expiring 2026-12-25
        b2_id = InventoryRepository.create_batch(
            product_id=prod_id,
            batch_number="BATCH-FIFO-B",
            quantity=15,
            unit_cost=155.0,
            supplier_id=1,
            received_date="2026-10-05",
            expiry_date="2026-12-25"
        )

        # Sell 9 units: should consume 5 units from B1 and 4 units from B2
        inv_id, inv_num = create_sales_invoice(
            customer_id=self.test_customer_id,
            payment_mode="UPI",
            items=[{"product_id": prod_id, "quantity": 9, "selling_price": 280.0}],
            transaction_reference="FIFO-SALE-001"
        )

        b1_after = InventoryRepository.get_batch_by_id(b1_id)
        b2_after = InventoryRepository.get_batch_by_id(b2_id)

        self.assertEqual(b1_after["quantity_available"], 0)
        self.assertEqual(b2_after["quantity_available"], 11)

        # Verify two stock movements logged
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT batch_id, quantity FROM stock_movements WHERE reference_id = ? ORDER BY movement_id ASC", (inv_num,))
            moves = cursor.fetchall()
            self.assertEqual(len(moves), 2)
            self.assertEqual(moves[0]["batch_id"], b1_id)
            self.assertEqual(moves[0]["quantity"], -5)
            self.assertEqual(moves[1]["batch_id"], b2_id)
            self.assertEqual(moves[1]["quantity"], -4)
        finally:
            conn.close()

    def test_05_insufficient_stock_validation_and_rollback(self):
        """
        Verify that attempting to sell more than available stock raises InsufficientStockError
        and rolls back the entire transaction without leaving orphaned records.
        """
        # Query total available stock for product 4
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COALESCE(SUM(quantity_available), 0) FROM inventory_batches WHERE product_id = 4")
            current_avail = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM sales_invoices")
            inv_count_before = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM stock_movements")
            sm_count_before = cursor.fetchone()[0]
        finally:
            conn.close()

        excess_qty = current_avail + 500

        with self.assertRaises(InsufficientStockError) as ctx:
            create_sales_invoice(
                customer_id=self.test_customer_id,
                payment_mode="CASH",
                items=[{"product_id": 4, "quantity": excess_qty, "selling_price": 200.0}]
            )

        self.assertIn("Insufficient stock", str(ctx.exception))

        # Verify no invoice was created and no stock movement was written
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM sales_invoices")
            inv_count_after = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM stock_movements")
            sm_count_after = cursor.fetchone()[0]

            self.assertEqual(inv_count_before, inv_count_after)
            self.assertEqual(sm_count_before, sm_count_after)
        finally:
            conn.close()

    def test_06_prevent_duplicate_transaction_reference(self):
        """
        Verify that submitting an identical non-null transaction reference (e.g. UPI UTR)
        raises DuplicateTransactionError and prevents duplicate charge/deduction.
        """
        unique_ref = "UPI-REF-DUPLICATE-CHECK-01"

        # First submission should succeed
        inv_id, inv_num = create_sales_invoice(
            customer_id=self.test_customer_id,
            payment_mode="UPI",
            items=[{"product_id": 1, "quantity": 1, "selling_price": 550.0}],
            transaction_reference=unique_ref
        )
        self.assertGreater(inv_id, 0)

        # Second submission with identical reference must fail
        with self.assertRaises(DuplicateTransactionError) as ctx:
            create_sales_invoice(
                customer_id=self.test_customer_id,
                payment_mode="UPI",
                items=[{"product_id": 1, "quantity": 1, "selling_price": 550.0}],
                transaction_reference=unique_ref
            )

        self.assertIn("already been processed", str(ctx.exception))

    def test_07_invalid_sales_payload_validation(self):
        """
        Verify validation for non-positive quantities, negative prices, and bad payment modes.
        """
        # Zero quantity
        with self.assertRaises(InvalidSaleError):
            create_sales_invoice(
                customer_id=self.test_customer_id,
                payment_mode="CASH",
                items=[{"product_id": 1, "quantity": 0, "selling_price": 500.0}]
            )

        # Negative price
        with self.assertRaises(InvalidSaleError):
            create_sales_invoice(
                customer_id=self.test_customer_id,
                payment_mode="CASH",
                items=[{"product_id": 1, "quantity": 1, "selling_price": -50.0}]
            )

        # Invalid discount (> 100%)
        with self.assertRaises(InvalidSaleError):
            create_sales_invoice(
                customer_id=self.test_customer_id,
                payment_mode="CASH",
                items=[{"product_id": 1, "quantity": 1, "selling_price": 500.0, "discount_pct": 110.0}]
            )

        # Invalid payment mode
        with self.assertRaises(InvalidSaleError):
            create_sales_invoice(
                customer_id=self.test_customer_id,
                payment_mode="CRYPTO_BITCOIN",
                items=[{"product_id": 1, "quantity": 1, "selling_price": 500.0}]
            )

    def test_08_safe_cancellation_workflow_preserves_audit(self):
        """
        Verify safe cancellation workflow:
        1. Status changes to 'CANCELLED'.
        2. Stock is restored back to the batch.
        3. Reverse 'SALE_CANCEL' movement is recorded.
        4. Invoice and items remain in database for audit integrity.
        5. Cannot cancel an already cancelled invoice.
        """
        # Create a dedicated product and batch of 15 units
        prod_id = ProductRepository.create_product({
            "sku": "SKU-TEST-CANCEL-08",
            "product_name": "Test Decor Item 08",
            "category_id": 1,
            "unit_of_measure": "pcs",
            "cost_price": 120.0,
            "selling_price": 200.0,
            "mrp": 250.0,
            "gst_rate": 18.0,
            "min_safety_stock": 5,
            "reorder_quantity": 20
        })

        b_id = InventoryRepository.create_batch(
            product_id=prod_id,
            batch_number="BATCH-CANCEL-TEST-08",
            quantity=15,
            unit_cost=120.0,
            supplier_id=1,
            received_date="2026-10-25"
        )

        inv_id, inv_num = create_sales_invoice(
            customer_id=self.test_customer_id,
            payment_mode="CARD",
            items=[{"product_id": prod_id, "quantity": 5, "selling_price": 200.0}],
            transaction_reference="CARD-AUTH-CANCEL-08"
        )

        b_sold = InventoryRepository.get_batch_by_id(b_id)
        self.assertEqual(b_sold["quantity_available"], 10)

        # Execute safe cancellation
        success = cancel_sales_invoice(invoice_id=inv_id, reason="Customer changed mind before dispatch")
        self.assertTrue(success)

        # Verify status is CANCELLED and audit history preserved
        inv_cancelled = SalesRepository.get_invoice_by_id(inv_id)
        self.assertEqual(inv_cancelled["status"], "CANCELLED")
        self.assertEqual(len(inv_cancelled["items"]), 1)

        # Verify stock restored to batch
        b_restored = InventoryRepository.get_batch_by_id(b_id)
        self.assertEqual(b_restored["quantity_available"], 15)

        # Verify SALE_CANCEL movement exists
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM stock_movements
                WHERE movement_type = 'SALE_CANCEL' AND reference_type = 'INVOICE_CANCEL' AND reference_id = ?
            """, (inv_num,))
            cancel_move = cursor.fetchone()
            self.assertIsNotNone(cancel_move)
            self.assertEqual(cancel_move["quantity"], 5)
        finally:
            conn.close()

        # Attempting to re-cancel must fail
        with self.assertRaises(ValueError):
            cancel_sales_invoice(invoice_id=inv_id, reason="Second cancel attempt")

    def test_09_item_level_sales_returns_prorated_refund_and_restock(self):
        """
        Verify item-level customer returns workflow:
        1. Partial return with restock to inventory (stock restored, SALE_CANCEL logged).
        2. Prorated Decimal refund amount.
        3. Returns row inserted in sales_returns with unique RET- number.
        4. Invoice transitions to PARTIALLY_RETURNED, then to RETURNED.
        5. Return with restock=False (damaged) records DAMAGE movement without restocking.
        """
        prod_id = ProductRepository.create_product({
            "sku": "SKU-TEST-RETURN-09",
            "product_name": "Test Lamp 09",
            "category_id": 1,
            "unit_of_measure": "pcs",
            "cost_price": 80.0,
            "selling_price": 150.0,
            "mrp": 180.0,
            "gst_rate": 12.0,
            "min_safety_stock": 5,
            "reorder_quantity": 20
        })

        b_id = InventoryRepository.create_batch(
            product_id=prod_id,
            batch_number="BATCH-RETURN-TEST-09",
            quantity=30,
            unit_cost=80.0,
            supplier_id=1,
            received_date="2026-10-25"
        )

        # Sell 10 units @ Rs. 150.00
        inv_id, inv_num = create_sales_invoice(
            customer_id=self.test_customer_id,
            payment_mode="CASH",
            items=[{"product_id": prod_id, "quantity": 10, "selling_price": 150.0}],
            transaction_reference="CASH-RETURN-TXN-09"
        )

        inv_details = SalesRepository.get_invoice_by_id(inv_id)
        item_id = inv_details["items"][0]["item_id"]
        total_item_amount = inv_details["items"][0]["total_item_amount"]

        # Step 1: Return 4 units (Restock = True)
        ret_id1, ret_num1, refund1 = process_sales_return(
            invoice_id=inv_id,
            returned_items=[{
                "item_id": item_id,
                "quantity": 4,
                "reason": "Excess quantity purchased",
                "restock": True
            }]
        )
        self.assertGreater(ret_id1, 0)
        self.assertTrue(ret_num1.startswith("RET-"))

        # Verify prorated refund: (total_item_amount / 10) * 4
        expected_refund1 = round((total_item_amount / 10.0) * 4, 2)
        self.assertAlmostEqual(refund1, expected_refund1, places=2)

        # Batch stock was 20 after sale; now with 4 restocked, should be 24
        b_after_ret1 = InventoryRepository.get_batch_by_id(b_id)
        self.assertEqual(b_after_ret1["quantity_available"], 24)

        # Invoice status should now be PARTIALLY_RETURNED
        inv_partial = SalesRepository.get_invoice_by_id(inv_id)
        self.assertEqual(inv_partial["status"], "PARTIALLY_RETURNED")

        # Step 2: Return remaining 6 units (Restock = False, e.g. packaging damaged)
        ret_id2, ret_num2, refund2 = process_sales_return(
            invoice_id=inv_id,
            returned_items=[{
                "item_id": item_id,
                "quantity": 6,
                "reason": "Damaged in transit by customer",
                "restock": False
            }]
        )
        self.assertGreater(ret_id2, 0)

        # Batch stock should still be 24 (not restocked because restock=False)
        b_after_ret2 = InventoryRepository.get_batch_by_id(b_id)
        self.assertEqual(b_after_ret2["quantity_available"], 24)

        # Verify DAMAGE movement was logged with SALES_RETURN reference
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM stock_movements
                WHERE movement_type = 'DAMAGE' AND reference_type = 'SALES_RETURN' AND reference_id = ?
            """, (ret_num2,))
            dmg_move = cursor.fetchone()
            self.assertIsNotNone(dmg_move)
        finally:
            conn.close()

        # Invoice status should now be fully RETURNED
        inv_full_ret = SalesRepository.get_invoice_by_id(inv_id)
        self.assertEqual(inv_full_ret["status"], "RETURNED")

    def test_10_return_quantity_limit_validation(self):
        """
        Verify that returning more items than purchased or remaining raises InvalidReturnError.
        """
        prod_id = ProductRepository.create_product({
            "sku": "SKU-TEST-RETLIMIT-10",
            "product_name": "Test Sweets 10",
            "category_id": 1,
            "unit_of_measure": "box",
            "cost_price": 300.0,
            "selling_price": 500.0,
            "mrp": 550.0,
            "gst_rate": 5.0,
            "min_safety_stock": 5,
            "reorder_quantity": 20
        })
        InventoryRepository.create_batch(
            product_id=prod_id,
            batch_number="BATCH-RETLIMIT-10",
            quantity=20,
            unit_cost=300.0,
            supplier_id=1,
            received_date="2026-10-25"
        )

        inv_id, _ = create_sales_invoice(
            customer_id=self.test_customer_id,
            payment_mode="CASH",
            items=[{"product_id": prod_id, "quantity": 3, "selling_price": 500.0}]
        )
        inv = SalesRepository.get_invoice_by_id(inv_id)
        item_id = inv["items"][0]["item_id"]

        # Attempt to return 5 units when only 3 were purchased
        with self.assertRaises(InvalidReturnError) as ctx:
            process_sales_return(
                invoice_id=inv_id,
                returned_items=[{"item_id": item_id, "quantity": 5, "reason": "Too many"}]
            )
        self.assertIn("Maximum Returnable", str(ctx.exception))

        # First return 2 units successfully
        process_sales_return(
            invoice_id=inv_id,
            returned_items=[{"item_id": item_id, "quantity": 2, "reason": "2 returned"}]
        )

        # Attempt to return 2 more units (only 1 remaining returnable)
        with self.assertRaises(InvalidReturnError) as ctx2:
            process_sales_return(
                invoice_id=inv_id,
                returned_items=[{"item_id": item_id, "quantity": 2, "reason": "Excess return"}]
            )
        self.assertIn("Maximum Returnable", str(ctx2.exception))

    def test_11_customer_khata_credit_sale_and_credit_limit_enforcement(self):
        """
        Verify CREDIT_KHATA sales:
        1. Updates customer outstanding_credit.
        2. Enforces customer credit_limit.
        3. Cancellation reverses the credit addition.
        """
        # Create customer with a tight credit limit of Rs. 1,000.00
        tight_cust_id = SalesRepository.create_customer(
            name="Suresh Khata Test",
            phone="9898989898",
            credit_limit=1000.0
        )

        # Sale 1: Rs. 600.00 (within limit)
        inv_id, _ = create_sales_invoice(
            customer_id=tight_cust_id,
            payment_mode="CREDIT_KHATA",
            items=[{"product_id": 1, "quantity": 1, "selling_price": 600.0}]
        )
        inv = SalesRepository.get_invoice_by_id(inv_id)
        bill_total = inv["net_total_amount"]

        cust = SalesRepository.get_customer_by_id(tight_cust_id)
        self.assertEqual(cust["outstanding_credit"], bill_total)

        # Sale 2: Attempt Rs. 800.00 (would make total Rs. 1,400+ > Rs. 1,000 limit)
        with self.assertRaises(CustomerCreditLimitExceededError) as ctx:
            create_sales_invoice(
                customer_id=tight_cust_id,
                payment_mode="CREDIT_KHATA",
                items=[{"product_id": 1, "quantity": 2, "selling_price": 500.0}]
            )
        self.assertIn("Khata credit limit exceeded", str(ctx.exception))

        # Cancel Sale 1: customer outstanding credit should return to 0.0
        cancel_sales_invoice(inv_id, reason="Customer cancelled credit purchase")
        cust_after_cancel = SalesRepository.get_customer_by_id(tight_cust_id)
        self.assertEqual(cust_after_cancel["outstanding_credit"], 0.0)

    def test_12_interstate_sale_igst_applied(self):
        """
        Verify that sales to customers located in a different Indian state
        have is_interstate=True, CGST=0, SGST=0, and IGST applied at full rate.
        """
        inv_id, _ = create_sales_invoice(
            customer_id=self.interstate_customer_id,  # Gujarat customer vs Maharashtra store
            payment_mode="CARD",
            items=[{"product_id": 1, "quantity": 2, "selling_price": 500.0}]
        )
        inv = SalesRepository.get_invoice_by_id(inv_id)
        self.assertEqual(inv["is_interstate"], 1)
        self.assertEqual(inv["cgst_amount"], 0.0)
        self.assertEqual(inv["sgst_amount"], 0.0)
        self.assertGreater(inv["igst_amount"], 0.0)

    def test_13_sales_reporting_and_search_queries(self):
        """
        Verify sales query filtering by date, payment mode, status, and search string.
        """
        today_str = date.today().strftime("%Y-%m-%d")

        # Query all invoices
        invoices = SalesRepository.get_invoices(limit=200)
        self.assertGreater(len(invoices), 0)

        # Test search filter by customer name
        search_results = SalesRepository.get_invoices(search="Ramesh Sharma")
        for s in search_results:
            self.assertEqual(s["customer_name"], "Ramesh Sharma")

        # Test payment mode filter
        upi_invoices = SalesRepository.get_invoices(payment_mode="UPI")
        for u in upi_invoices:
            self.assertEqual(u["payment_mode"], "UPI")

        # Test sales report dataframe
        df = get_sales_report_df(start_date=today_str, end_date=today_str)
        self.assertFalse(df.empty)
        self.assertIn("invoice_number", df.columns)
        self.assertIn("net_total_amount", df.columns)

        # Test executive KPI metrics
        kpis = get_sales_kpis(start_date=today_str, end_date=today_str)
        self.assertIn("total_revenue", kpis)
        self.assertIn("total_invoices", kpis)
        self.assertGreater(kpis["total_invoices"], 0)

    def test_14_integer_paise_and_decimal_monetary_accuracy(self):
        """
        Verify exact Decimal and integer paise conversion utilities and line calculations:
        - Exact integer paise conversion without floating point drift
        - calculate_monetary_line provides zero-drift calculations
        """
        # Test rupees to paise
        self.assertEqual(rupees_to_paise(123.45), 12345)
        self.assertEqual(rupees_to_paise(0.01), 1)
        self.assertEqual(rupees_to_paise(100), 10000)
        self.assertEqual(rupees_to_paise(99.999), 10000)  # Rounding to nearest paise

        # Test paise to rupees
        self.assertEqual(paise_to_rupees(12345), Decimal("123.45"))
        self.assertEqual(paise_to_rupees(1), Decimal("0.01"))
        self.assertEqual(paise_to_rupees(0), Decimal("0.00"))

        # Test calculate_monetary_line with mixed values
        calc = calculate_monetary_line(
            quantity=3,
            unit_price=499.99,
            discount_pct=10.0,
            gst_rate=18.0
        )
        self.assertEqual(calc["gross_amount"], Decimal("1499.97"))
        self.assertEqual(calc["discount_amount"], Decimal("150.00"))
        self.assertEqual(calc["taxable_amount"], Decimal("1349.97"))
        self.assertEqual(calc["tax_total"], Decimal("243.00"))
        self.assertEqual(calc["line_total"], Decimal("1592.97"))
        self.assertEqual(calc["paise"]["line_total"], 159297)

    def test_15_flat_rupee_discount_and_mixed_discounts(self):
        """
        Test sale creation with flat rupee discount on lines and extra bill discount.
        """
        prod_id = ProductRepository.create_product({
            "sku": "SKU-TEST-FLAT-DISC",
            "product_name": "Flat Discount Test Sweets",
            "category_id": 1,
            "unit_of_measure": "box",
            "cost_price": 200.0,
            "selling_price": 400.0,
            "mrp": 450.0,
            "gst_rate": 5.0
        })
        InventoryRepository.create_batch(
            product_id=prod_id,
            batch_number="BATCH-FLAT-01",
            quantity=20,
            unit_cost=200.0,
            supplier_id=1,
            received_date="2026-10-25"
        )

        # 2 units @ 400 = 800 gross. Flat line discount = Rs. 100. Taxable = 700.
        # Bill discount = Rs. 50. Final taxable = 650. GST 5% = 32.50. Net total = 682.50 -> 683 (rounded).
        inv_id, inv_num = create_sales_invoice(
            customer_id=self.test_customer_id,
            payment_mode="CASH",
            items=[{
                "product_id": prod_id,
                "quantity": 2,
                "selling_price": 400.0,
                "discount_amount": 100.0
            }],
            overall_discount=50.0
        )
        inv = SalesRepository.get_invoice_by_id(inv_id)
        self.assertEqual(inv["status"], "COMPLETED")
        self.assertEqual(inv["items"][0]["taxable_value"], 700.0)
        self.assertEqual(inv["items"][0]["discount_percent"], 12.5)  # 100 / 800 = 12.5%
        self.assertEqual(inv["discount_amount"], 50.0)
        self.assertEqual(inv["net_total_amount"], 685.0)

    def test_16_duplicate_product_lines_aggregate_stock_validation(self):
        """
        Verify multi-line invoices containing duplicate product lines:
        1. Aggregates requested quantities across lines and rejects if sum exceeds stock.
        2. Successfully fulfills via FIFO when total sum <= available stock.
        """
        prod_id = ProductRepository.create_product({
            "sku": "SKU-TEST-DUP-LINES",
            "product_name": "Duplicate Lines Aggregate Stock Test",
            "category_id": 1,
            "unit_of_measure": "pcs",
            "cost_price": 100.0,
            "selling_price": 250.0,
            "mrp": 300.0,
            "gst_rate": 18.0
        })
        # Add exactly 5 units to stock
        b_id = InventoryRepository.create_batch(
            product_id=prod_id,
            batch_number="BATCH-DUP-01",
            quantity=5,
            unit_cost=100.0,
            supplier_id=1,
            received_date="2026-10-25"
        )

        # Case 1: Line 1 requests 3 units, Line 2 requests 3 units. Sum = 6 > 5. Must fail.
        with self.assertRaises(InsufficientStockError) as ctx:
            create_sales_invoice(
                customer_id=self.test_customer_id,
                payment_mode="CASH",
                items=[
                    {"product_id": prod_id, "quantity": 3, "selling_price": 250.0},
                    {"product_id": prod_id, "quantity": 3, "selling_price": 250.0}
                ]
            )
        self.assertIn("Insufficient stock", str(ctx.exception))

        # Stock must remain intact (5 units)
        batch = InventoryRepository.get_batch_by_id(b_id)
        self.assertEqual(batch["quantity_available"], 5)

        # Case 2: Line 1 requests 2 units, Line 2 requests 3 units. Sum = 5 <= 5. Must succeed.
        inv_id, inv_num = create_sales_invoice(
            customer_id=self.test_customer_id,
            payment_mode="CASH",
            items=[
                {"product_id": prod_id, "quantity": 2, "selling_price": 250.0},
                {"product_id": prod_id, "quantity": 3, "selling_price": 250.0}
            ]
        )
        inv = SalesRepository.get_invoice_by_id(inv_id)
        self.assertEqual(len(inv["items"]), 2)
        self.assertEqual(inv["items"][0]["quantity"], 2)
        self.assertEqual(inv["items"][1]["quantity"], 3)

        # Batches must now be fully depleted (0 available)
        batch_after = InventoryRepository.get_batch_by_id(b_id)
        self.assertEqual(batch_after["quantity_available"], 0)

    def test_17_multi_item_insufficient_stock_acid_rollback(self):
        """
        Verify that in a multi-item sale, if any item fails stock availability,
        the entire transaction rolls back completely:
        - 0 invoices created
        - 0 stock movements logged
        - Earlier items' inventory batches remain untouched
        """
        prod_a = ProductRepository.create_product({
            "sku": "SKU-ACID-A",
            "product_name": "Acid Rollback Item A",
            "category_id": 1,
            "unit_of_measure": "box",
            "cost_price": 50.0,
            "selling_price": 100.0,
            "gst_rate": 12.0
        })
        prod_b = ProductRepository.create_product({
            "sku": "SKU-ACID-B",
            "product_name": "Acid Rollback Item B",
            "category_id": 1,
            "unit_of_measure": "box",
            "cost_price": 80.0,
            "selling_price": 150.0,
            "gst_rate": 12.0
        })
        b_a = InventoryRepository.create_batch(
            product_id=prod_a,
            batch_number="BATCH-ACID-A",
            quantity=10,
            unit_cost=50.0,
            supplier_id=1,
            received_date="2026-10-25"
        )
        b_b = InventoryRepository.create_batch(
            product_id=prod_b,
            batch_number="BATCH-ACID-B",
            quantity=2,
            unit_cost=80.0,
            supplier_id=1,
            received_date="2026-10-25"
        )

        # Count prior invoices and movements
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM sales_invoices")
            inv_count_before = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM stock_movements")
            mov_count_before = c.fetchone()[0]

        # Attempt sale: Item A has plenty (10 >= 3), but Item B has only 2 (< 8)
        with self.assertRaises(InsufficientStockError):
            create_sales_invoice(
                customer_id=self.test_customer_id,
                payment_mode="CASH",
                items=[
                    {"product_id": prod_a, "quantity": 3, "selling_price": 100.0},
                    {"product_id": prod_b, "quantity": 8, "selling_price": 150.0}
                ]
            )

        # Verify strict ACID rollback
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT COUNT(*) FROM sales_invoices")
            self.assertEqual(c.fetchone()[0], inv_count_before)
            c.execute("SELECT COUNT(*) FROM stock_movements")
            self.assertEqual(c.fetchone()[0], mov_count_before)

        # Batches for Item A must remain exactly 10
        self.assertEqual(InventoryRepository.get_batch_by_id(b_a)["quantity_available"], 10)

    def test_18_safe_correction_workflow_reversal_and_reissue(self):
        """
        Verify safe correction / re-issuance workflow:
        1. Original invoice is cancelled with audit notes referencing the replacement.
        2. Inventory from original invoice is restored (SALE_CANCEL movements).
        3. Replacement invoice is created with status COMPLETED and references original.
        4. Neither invoice is ever deleted from database.
        """
        prod_id = ProductRepository.create_product({
            "sku": "SKU-CORR-01",
            "product_name": "Correction Workflow Sweet Pack",
            "category_id": 1,
            "unit_of_measure": "box",
            "cost_price": 100.0,
            "selling_price": 200.0,
            "gst_rate": 5.0
        })
        b_id = InventoryRepository.create_batch(
            product_id=prod_id,
            batch_number="BATCH-CORR-01",
            quantity=10,
            unit_cost=100.0,
            supplier_id=1,
            received_date="2026-10-25"
        )

        # Create original sale: 4 units @ Rs. 200.00
        orig_id, orig_num = create_sales_invoice(
            customer_id=self.test_customer_id,
            payment_mode="CASH",
            items=[{"product_id": prod_id, "quantity": 4, "selling_price": 200.0}],
            transaction_reference="REF-CORR-ORIG-123"
        )
        # Remaining stock = 6 units
        self.assertEqual(InventoryRepository.get_batch_by_id(b_id)["quantity_available"], 6)

        # Perform safe correction: customer wanted only 2 units instead of 4
        new_id, new_num = correct_sales_invoice(
            original_invoice_id=orig_id,
            new_items=[{"product_id": prod_id, "quantity": 2, "selling_price": 200.0}],
            payment_mode="CASH",
            reason="Customer requested correction: reduced quantity from 4 to 2"
        )

        # Verify original invoice status
        orig_inv = SalesRepository.get_invoice_by_id(orig_id)
        self.assertEqual(orig_inv["status"], "CANCELLED")
        self.assertIn("replaced by", orig_inv["notes"])
        self.assertIn(new_num, orig_inv["notes"])

        # Verify replacement invoice status
        new_inv = SalesRepository.get_invoice_by_id(new_id)
        self.assertEqual(new_inv["status"], "COMPLETED")
        self.assertIn("Corrected replacement", new_inv["notes"])
        self.assertIn(orig_num, new_inv["notes"])
        self.assertEqual(new_inv["items"][0]["quantity"], 2)

        # Stock must now be: 10 - 4 (orig) + 4 (cancelled) - 2 (reissued) = 8
        self.assertEqual(InventoryRepository.get_batch_by_id(b_id)["quantity_available"], 8)

        # Check stock movements ledger contains SALE_CANCEL for original
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute(
                "SELECT movement_type, quantity FROM stock_movements WHERE reference_id = ? ORDER BY movement_id ASC",
                (orig_num,)
            )
            movements = c.fetchall()
            # Original sale (-4) + cancellation (+4)
            types = [m[0] for m in movements]
            self.assertIn("SALE", types)
            self.assertIn("SALE_CANCEL", types)

    def test_19_safe_correction_rollback_on_insufficient_stock(self):
        """
        Verify that if the replacement invoice fails (e.g. requested quantity exceeds available stock),
        the safe correction rolls back completely:
        - Original invoice remains COMPLETED (cancellation is rolled back)
        - Inventory remains unchanged
        """
        prod_id = ProductRepository.create_product({
            "sku": "SKU-CORR-FAIL",
            "product_name": "Correction Rollback Item",
            "category_id": 1,
            "unit_of_measure": "box",
            "cost_price": 100.0,
            "selling_price": 200.0,
            "gst_rate": 5.0
        })
        b_id = InventoryRepository.create_batch(
            product_id=prod_id,
            batch_number="BATCH-CORR-F1",
            quantity=5,
            unit_cost=100.0,
            supplier_id=1,
            received_date="2026-10-25"
        )

        orig_id, _ = create_sales_invoice(
            customer_id=self.test_customer_id,
            payment_mode="CASH",
            items=[{"product_id": prod_id, "quantity": 2, "selling_price": 200.0}]
        )
        # 3 units left in stock
        self.assertEqual(InventoryRepository.get_batch_by_id(b_id)["quantity_available"], 3)

        # Attempt correction requesting 100 units (far exceeds 3 + 2 = 5)
        with self.assertRaises(InsufficientStockError):
            correct_sales_invoice(
                original_invoice_id=orig_id,
                new_items=[{"product_id": prod_id, "quantity": 100, "selling_price": 200.0}],
                reason="Trying to add 100 units"
            )

        # Original invoice MUST still be COMPLETED
        orig_inv = SalesRepository.get_invoice_by_id(orig_id)
        self.assertEqual(orig_inv["status"], "COMPLETED")

        # Stock must remain 3
        self.assertEqual(InventoryRepository.get_batch_by_id(b_id)["quantity_available"], 3)

    def test_20_duplicate_transaction_reference_whitespace_and_case(self):
        """
        Verify duplicate transaction reference check trims whitespace and is case-insensitive.
        """
        inv_id, _ = create_sales_invoice(
            customer_id=self.test_customer_id,
            payment_mode="UPI",
            items=[{"product_id": 1, "quantity": 1, "selling_price": 500.0}],
            transaction_reference="UPI-REF-CASE-TEST-123"
        )
        self.assertGreater(inv_id, 0)

        # Attempt duplicate with leading/trailing whitespace and lowercase
        with self.assertRaises(DuplicateTransactionError) as ctx:
            create_sales_invoice(
                customer_id=self.test_customer_id,
                payment_mode="UPI",
                items=[{"product_id": 1, "quantity": 1, "selling_price": 500.0}],
                transaction_reference="  upi-ref-case-test-123  "
            )
        self.assertIn("has already been processed", str(ctx.exception))

    def test_21_revenue_adjustments_after_returns(self):
        """
        Verify get_sales_kpis accurately adjusts net revenue after sales returns:
        net_revenue = gross_revenue - refund_amount
        """
        today_str = date.today().strftime("%Y-%m-%d")
        prod_id = ProductRepository.create_product({
            "sku": "SKU-KPI-RET",
            "product_name": "KPI Return Adjust Test",
            "category_id": 1,
            "unit_of_measure": "box",
            "cost_price": 200.0,
            "selling_price": 500.0,
            "gst_rate": 0.0
        })
        InventoryRepository.create_batch(
            product_id=prod_id,
            batch_number="BATCH-KPI-RET",
            quantity=10,
            unit_cost=200.0,
            supplier_id=1,
            received_date="2026-10-25"
        )

        # Initial KPIs
        initial_kpis = get_sales_kpis(start_date=today_str, end_date=today_str)
        init_revenue = initial_kpis["total_revenue"]
        init_refund = initial_kpis["refund_amount"]

        # Sale: 2 units @ Rs. 500 = Rs. 1,000
        inv_id, _ = create_sales_invoice(
            customer_id=self.test_customer_id,
            payment_mode="CASH",
            items=[{"product_id": prod_id, "quantity": 2, "selling_price": 500.0}]
        )
        inv = SalesRepository.get_invoice_by_id(inv_id)
        item_id = inv["items"][0]["item_id"]

        # Return 1 unit (Refund = Rs. 500)
        ret_id, ret_num, refund_amt = process_sales_return(
            invoice_id=inv_id,
            returned_items=[{"item_id": item_id, "quantity": 1, "reason": "Not needed"}]
        )
        self.assertEqual(refund_amt, 500.0)

        # Updated KPIs
        updated_kpis = get_sales_kpis(start_date=today_str, end_date=today_str)
        self.assertAlmostEqual(updated_kpis["refund_amount"], init_refund + 500.0, places=2)
        # Net revenue should reflect the deduction
        expected_net = updated_kpis["gross_revenue"] - updated_kpis["refund_amount"]
        self.assertAlmostEqual(updated_kpis["total_revenue"], expected_net, places=2)

    def test_22_product_and_sku_search_and_line_items_export(self):
        """
        Verify:
        1. Invoices can be searched by product SKU and product name.
        2. get_sales_line_items_df exports comprehensive line item details.
        """
        prod_id = ProductRepository.create_product({
            "sku": "SKU-DIWALI-SPECIAL-99",
            "product_name": "Diwali Special Handcrafted Diya Set",
            "category_id": 1,
            "unit_of_measure": "set",
            "cost_price": 150.0,
            "selling_price": 350.0,
            "gst_rate": 12.0
        })
        InventoryRepository.create_batch(
            product_id=prod_id,
            batch_number="BATCH-DIWALI-99",
            quantity=10,
            unit_cost=150.0,
            supplier_id=1,
            received_date="2026-10-25"
        )
        inv_id, inv_num = create_sales_invoice(
            customer_id=self.test_customer_id,
            payment_mode="UPI",
            items=[{"product_id": prod_id, "quantity": 2, "selling_price": 350.0}]
        )

        # Search by SKU
        sku_results = SalesRepository.get_invoices(search="SKU-DIWALI-SPECIAL-99")
        matching_nums = [r["invoice_number"] for r in sku_results]
        self.assertIn(inv_num, matching_nums)

        # Search by product name keyword
        name_results = SalesRepository.get_invoices(search="Handcrafted Diya Set")
        matching_nums_2 = [r["invoice_number"] for r in name_results]
        self.assertIn(inv_num, matching_nums_2)

        # Export detailed line items dataframe
        lines_df = get_sales_line_items_df()
        self.assertFalse(lines_df.empty)
        self.assertIn("sku", lines_df.columns)
        self.assertIn("product_name", lines_df.columns)
        self.assertIn("total_item_amount", lines_df.columns)
        self.assertIn("taxable_value", lines_df.columns)
        matching_lines = lines_df[lines_df["sku"] == "SKU-DIWALI-SPECIAL-99"]
        self.assertFalse(matching_lines.empty)
        self.assertEqual(matching_lines.iloc[0]["quantity"], 2)


if __name__ == "__main__":
    unittest.main()
