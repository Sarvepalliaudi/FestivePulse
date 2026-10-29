"""
FestivePulse — Comprehensive CRUD & Transactional Unit Tests for Repositories
Verifies parameterized SQL, foreign key enforcement, ACID transactions, and error handling.
"""

import sqlite3
import unittest
from database.connection import init_db, get_db_connection
from repositories import (
    SettingsRepository,
    FestivalRepository,
    ProductRepository,
    InventoryRepository,
    SalesRepository,
    ExpenseRepository
)


class TestRepositoriesCRUD(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db(force_recreate=True)

    def test_01_settings_repository(self):
        settings = SettingsRepository.get_settings()
        self.assertIn("business_name", settings)
        self.assertEqual(settings["state_code"], "27")

        updated = SettingsRepository.update_settings({
            "business_name": "Updated Ganesh Bhandar",
            "phone": "9820999999",
            "address_line1": "New Yard Road",
            "city": "Mumbai",
            "pincode": "400028",
            "state": "Maharashtra",
            "state_code": "27",
            "primary_region": "West"
        })
        self.assertTrue(updated)

        refetched = SettingsRepository.get_settings()
        self.assertEqual(refetched["business_name"], "Updated Ganesh Bhandar")

    def test_02_product_crud_and_validation(self):
        # Create
        new_prod_id = ProductRepository.create_product({
            "sku": "SKU-TEST-001",
            "barcode": "890123499999",
            "product_name": "Test Festive Sweet Box",
            "category_id": 1,
            "unit_of_measure": "box",
            "cost_price": 200.0,
            "selling_price": 350.0,
            "mrp": 400.0,
            "gst_rate": 5.0,
            "hsn_code": "21069099",
            "min_safety_stock": 15,
            "reorder_quantity": 40,
            "is_perishable": True,
            "shelf_life_days": 10,
            "festival_tags": ["DIWALI"]
        })
        self.assertGreater(new_prod_id, 0)

        # Get by ID and SKU
        p_by_id = ProductRepository.get_product_by_id(new_prod_id)
        self.assertIsNotNone(p_by_id)
        self.assertEqual(p_by_id["sku"], "SKU-TEST-001")
        self.assertEqual(p_by_id["festival_tags"], ["DIWALI"])

        p_by_sku = ProductRepository.get_product_by_sku("SKU-TEST-001")
        self.assertEqual(p_by_sku["product_id"], new_prod_id)

        # Update
        updated = ProductRepository.update_product(new_prod_id, {
            "product_name": "Test Festive Sweet Box Premium",
            "category_id": 1,
            "unit_of_measure": "box",
            "cost_price": 220.0,
            "selling_price": 380.0,
            "mrp": 420.0,
            "gst_rate": 5.0,
            "hsn_code": "21069099",
            "min_safety_stock": 20,
            "reorder_quantity": 40,
            "is_perishable": True,
            "shelf_life_days": 10,
            "festival_tags": ["DIWALI", "PONGAL"]
        })
        self.assertTrue(updated)

        p_updated = ProductRepository.get_product_by_id(new_prod_id)
        self.assertEqual(p_updated["product_name"], "Test Festive Sweet Box Premium")

        # Soft Delete
        deleted = ProductRepository.delete_product(new_prod_id, hard_delete=False)
        self.assertTrue(deleted)
        p_soft_deleted = ProductRepository.get_product_by_id(new_prod_id)
        self.assertEqual(p_soft_deleted["is_active"], 0)

    def test_03_foreign_key_enforcement(self):
        # Attempting to insert product with non-existent category_id should fail
        with self.assertRaises(sqlite3.IntegrityError):
            ProductRepository.create_product({
                "sku": "SKU-INVALID-CAT",
                "product_name": "Bad Category Product",
                "category_id": 99999,  # Does not exist
                "unit_of_measure": "pcs",
                "cost_price": 100.0,
                "selling_price": 150.0,
                "mrp": 150.0,
                "gst_rate": 5.0
            })

    def test_04_inventory_batch_and_movements(self):
        # Create Batch for Product 2
        batch_id = InventoryRepository.create_batch(
            product_id=2,
            batch_number="BATCH-TEST-2026",
            quantity=50,
            unit_cost=320.0,
            supplier_id=1,
            received_date="2026-10-20",
            expiry_date="2026-11-20",
            storage_location="Rack T1"
        )
        self.assertGreater(batch_id, 0)

        # Fetch batches
        batches = InventoryRepository.get_batches_for_product(2, available_only=True)
        self.assertGreaterEqual(len(batches), 1)

        # Update batch quantity
        updated = InventoryRepository.update_batch_quantity(batch_id, -10)
        self.assertTrue(updated)
        b_after = InventoryRepository.get_batch_by_id(batch_id)
        self.assertEqual(b_after["quantity_available"], 40)

        # Record stock movement (Damage)
        mov_id = InventoryRepository.record_stock_movement(
            product_id=2,
            batch_id=batch_id,
            movement_type="DAMAGE",
            quantity=-2,
            reason="Damaged box packaging",
            cost_impact=640.0,
            movement_date="2026-10-25"
        )
        self.assertGreater(mov_id, 0)

        movements = InventoryRepository.get_stock_movements(product_id=2)
        self.assertGreaterEqual(len(movements), 1)

    def test_05_festival_management(self):
        # Create festival
        f_id = FestivalRepository.create_festival(
            festival_code="CHHATH_TEST",
            festival_name="Chhath Puja",
            primary_regions=["North", "East"],
            typical_surge_multiplier=3.20,
            preparation_lead_days=20
        )
        self.assertGreater(f_id, 0)

        # Create occurrence
        occ_id = FestivalRepository.create_occurrence({
            "festival_id": f_id,
            "year": 2026,
            "prep_start_date": "2026-10-25",
            "campaign_start_date": "2026-11-01",
            "peak_start_date": "2026-11-12",
            "festival_date": "2026-11-15",
            "campaign_end_date": "2026-11-18",
            "notes": "Chhath Mahaparv 2026",
            "is_current_active": False
        })
        self.assertGreater(occ_id, 0)

        # Activate occurrence
        activated = FestivalRepository.set_active_occurrence(occ_id)
        self.assertTrue(activated)

        active_occ = FestivalRepository.get_active_occurrence()
        self.assertEqual(active_occ["occurrence_id"], occ_id)

        # Set target
        target_set = FestivalRepository.upsert_target(
            occurrence_id=occ_id,
            category_id=1,
            target_revenue=600000.0,
            target_profit=200000.0,
            budgeted_expenses=30000.0
        )
        self.assertTrue(target_set)

    def test_06_sales_atomic_transaction_and_cancellation(self):
        # Create customer
        cust_id = SalesRepository.create_customer(
            name="Test Customer Khata",
            phone="9820088888",
            city="Mumbai",
            state="Maharashtra",
            credit_limit=20000.0
        )
        self.assertGreater(cust_id, 0)

        # Prepare line item for product 3
        # Ensure batch has stock
        b_list = InventoryRepository.get_batches_for_product(3, available_only=True)
        self.assertGreater(len(b_list), 0)
        target_batch = b_list[0]
        initial_batch_qty = target_batch["quantity_available"]

        inv_header = {
            "invoice_number": "INV-202627-TEST-999",
            "invoice_date": "2026-10-29",
            "customer_id": cust_id,
            "occurrence_id": 10,
            "payment_mode": "CREDIT_KHATA",
            "subtotal_amount": 2300.0,
            "discount_amount": 0.0,
            "total_taxable_amount": 2300.0,
            "cgst_amount": 138.0,
            "sgst_amount": 138.0,
            "igst_amount": 0.0,
            "roundoff_amount": 0.0,
            "net_total_amount": 2576.0,
            "is_interstate": False
        }

        line_items = [{
            "product_id": 3,
            "batch_id": target_batch["batch_id"],
            "quantity": 2,
            "unit_cost_price": 750.0,
            "unit_selling_price": 1150.0,
            "discount_percent": 0.0,
            "taxable_value": 2300.0,
            "gst_rate": 12.0,
            "cgst_rate": 6.0,
            "cgst_amount": 138.0,
            "sgst_rate": 6.0,
            "sgst_amount": 138.0,
            "igst_rate": 0.0,
            "igst_amount": 0.0,
            "total_item_amount": 2576.0,
            "gross_profit": 800.0
        }]

        batch_deductions = [(target_batch["batch_id"], 2)]

        inv_id, inv_num = SalesRepository.create_invoice_with_items_atomic(
            invoice_header=inv_header,
            line_items=line_items,
            batch_deductions=batch_deductions,
            customer_credit_delta=2576.0
        )
        self.assertGreater(inv_id, 0)
        self.assertEqual(inv_num, "INV-202627-TEST-999")

        # Verify batch stock was deducted
        b_after = InventoryRepository.get_batch_by_id(target_batch["batch_id"])
        self.assertEqual(b_after["quantity_available"], initial_batch_qty - 2)

        # Verify customer khata was updated
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT outstanding_credit FROM customers WHERE customer_id = ?", (cust_id,))
        credit_due = float(cursor.fetchone()["outstanding_credit"])
        conn.close()
        self.assertEqual(credit_due, 2576.0)

        # Test invoice cancellation & restock
        cancelled = SalesRepository.cancel_invoice_atomic(
            invoice_id=inv_id,
            batch_restorations=[(target_batch["batch_id"], 2)],
            khata_reversal=2576.0,
            customer_id=cust_id
        )
        self.assertTrue(cancelled)

        # Stock restored
        b_restored = InventoryRepository.get_batch_by_id(target_batch["batch_id"])
        self.assertEqual(b_restored["quantity_available"], initial_batch_qty)

    def test_07_expense_crud(self):
        exp_id = ExpenseRepository.create_expense(
            expense_category="TEMPORARY_STALL_RENT",
            expense_date="2026-10-25",
            amount=15000.0,
            payment_mode="UPI",
            occurrence_id=10,
            vendor_name="City Market Authority",
            invoice_receipt_no="RCP-9821",
            notes="10-day stall booking fee"
        )
        self.assertGreater(exp_id, 0)

        exp = ExpenseRepository.get_expense_by_id(exp_id)
        self.assertIsNotNone(exp)
        self.assertEqual(exp["amount"], 15000.0)

        deleted = ExpenseRepository.delete_expense(exp_id)
        self.assertTrue(deleted)
        self.assertIsNone(ExpenseRepository.get_expense_by_id(exp_id))


if __name__ == "__main__":
    unittest.main()
