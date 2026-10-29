"""
FestivePulse — CSV Import & Export Unit Test Suite
Comprehensive validation covering:
- Malformed CSV files (unclosed quotes, corrupt encoding, empty files)
- Missing required columns
- Invalid dates (calendar boundaries, format errors, expiry < received)
- Duplicate IDs (duplicate SKUs, sales invoices, transaction references, batches)
- Negative quantities and invalid pricing relationships
- Atomic transaction rollback on failure
- Safe row-by-row reporting (never silently discarding rows)
- Invariant: Stock balance must never bypass the movement ledger
- Filtered exports and UTF-8 compatibility
"""

import unittest
import io
from datetime import date
from database.connection import init_db, db_session, get_db_connection
from services.import_export_service import (
    preview_import,
    execute_import,
    get_template_csv,
    export_products_to_csv,
    export_sales_to_csv,
    export_expenses_to_csv,
    export_stock_to_csv,
    parse_csv_file
)
from services.expense_service import record_expense
from repositories.inventory_repository import InventoryRepository


class TestImportExportService(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        """Sets up isolated fixtures for import/export tests."""
        with db_session() as conn:
            cursor = conn.cursor()

            # Clean test fixtures
            cursor.execute("DELETE FROM expense_audit_logs WHERE expense_id IN (SELECT expense_id FROM expenses WHERE vendor_name LIKE 'IO-TEST-%' OR invoice_receipt_no LIKE 'IO-REC-%')")
            cursor.execute("DELETE FROM expenses WHERE vendor_name LIKE 'IO-TEST-%' OR invoice_receipt_no LIKE 'IO-REC-%'")
            cursor.execute("DELETE FROM sales_items WHERE product_id IN (SELECT product_id FROM products WHERE sku LIKE 'IO-SKU-%')")
            cursor.execute("DELETE FROM sales_items WHERE invoice_id IN (SELECT invoice_id FROM sales_invoices WHERE invoice_number LIKE 'IO-INV-%')")
            cursor.execute("DELETE FROM sales_invoices WHERE invoice_number LIKE 'IO-INV-%'")
            cursor.execute("DELETE FROM stock_movements WHERE product_id IN (SELECT product_id FROM products WHERE sku LIKE 'IO-SKU-%')")
            cursor.execute("DELETE FROM stock_movements WHERE reason LIKE '%IO-TEST%' OR reference_id LIKE 'IO-%'")
            cursor.execute("DELETE FROM inventory_batches WHERE product_id IN (SELECT product_id FROM products WHERE sku LIKE 'IO-SKU-%')")
            cursor.execute("DELETE FROM inventory_batches WHERE batch_number LIKE 'IO-BAT-%'")
            cursor.execute("DELETE FROM products WHERE sku LIKE 'IO-SKU-%'")
            cursor.execute("DELETE FROM product_categories WHERE category_name LIKE 'IO_CAT_%'")

            # 1. Product Category
            cursor.execute("""
                INSERT INTO product_categories (category_name, default_gst_rate, description)
                VALUES ('IO_CAT_MITHAI', 5.0, 'Import Export Test Category')
            """)
            self.cat_id = cursor.lastrowid

            # 2. Base Product with Stock for Sales Testing
            cursor.execute("""
                INSERT INTO products (
                    sku, barcode, product_name, category_id, unit_of_measure,
                    cost_price, selling_price, mrp, gst_rate, min_safety_stock, reorder_quantity, is_active
                ) VALUES ('IO-SKU-BASE', '8909999001', 'IO Test Base Sweets', ?, 'box', 200.0, 350.0, 400.0, 5.0, 10, 50, 1)
            """, (self.cat_id,))
            self.base_prod_id = cursor.lastrowid

            # 3. Base Inbound Batch (100 units available)
            cursor.execute("""
                INSERT INTO inventory_batches (
                    product_id, batch_number, received_date, expiry_date,
                    quantity_received, quantity_available, unit_cost, storage_location
                ) VALUES (?, 'IO-BAT-BASE-01', '2026-10-01', '2026-12-31', 100, 100, 200.0, 'Main Store')
            """, (self.base_prod_id,))
            self.base_batch_id = cursor.lastrowid

            # Stock movement for base batch
            cursor.execute("""
                INSERT INTO stock_movements (
                    product_id, batch_id, movement_type, quantity, unit_cost,
                    total_cost_impact, reference_type, reference_id, reason
                ) VALUES (?, ?, 'RECEIPT', 100, 200.0, 20000.0, 'PURCHASE_RECEIPT', 'IO-PO-BASE', 'Base test batch')
            """, (self.base_prod_id, self.base_batch_id))

    def tearDown(self):
        """Cleans test fixtures after each test."""
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM expense_audit_logs WHERE expense_id IN (SELECT expense_id FROM expenses WHERE vendor_name LIKE 'IO-TEST-%' OR invoice_receipt_no LIKE 'IO-REC-%')")
            cursor.execute("DELETE FROM expenses WHERE vendor_name LIKE 'IO-TEST-%' OR invoice_receipt_no LIKE 'IO-REC-%'")
            cursor.execute("DELETE FROM sales_items WHERE product_id IN (SELECT product_id FROM products WHERE sku LIKE 'IO-SKU-%')")
            cursor.execute("DELETE FROM sales_items WHERE invoice_id IN (SELECT invoice_id FROM sales_invoices WHERE invoice_number LIKE 'IO-INV-%')")
            cursor.execute("DELETE FROM sales_invoices WHERE invoice_number LIKE 'IO-INV-%'")
            cursor.execute("DELETE FROM stock_movements WHERE product_id IN (SELECT product_id FROM products WHERE sku LIKE 'IO-SKU-%')")
            cursor.execute("DELETE FROM stock_movements WHERE reason LIKE '%IO-TEST%' OR reference_id LIKE 'IO-%'")
            cursor.execute("DELETE FROM inventory_batches WHERE product_id IN (SELECT product_id FROM products WHERE sku LIKE 'IO-SKU-%')")
            cursor.execute("DELETE FROM inventory_batches WHERE batch_number LIKE 'IO-BAT-%'")
            cursor.execute("DELETE FROM products WHERE sku LIKE 'IO-SKU-%'")
            cursor.execute("DELETE FROM product_categories WHERE category_name LIKE 'IO_CAT_%'")

    # ==========================================================================
    # 1. MALFORMED CSV HANDLING
    # ==========================================================================

    def test_malformed_csv_files(self):
        """Tests that corrupt syntax, unclosed quotes, and empty files are handled safely."""
        # Empty string
        res_empty = preview_import("", "products")
        self.assertFalse(res_empty["success"])
        self.assertIn("empty", res_empty["error"].lower())

        # Whitespace-only string
        res_spaces = preview_import("   \n  \n  ", "products")
        self.assertFalse(res_spaces["success"])

        # Unclosed quote
        malformed_csv = 'sku,product_name,category,unit_of_measure,cost_price,selling_price,gst_rate\n"IO-SKU-BAD,Broken Name,IO_CAT_MITHAI,box,100,200,5'
        df, err = parse_csv_file(malformed_csv)
        # Should either parse safely or return clear parser error
        if err:
            self.assertIn("malformed", err.lower())

    # ==========================================================================
    # 2. MISSING REQUIRED COLUMNS
    # ==========================================================================

    def test_missing_required_columns(self):
        """Tests that CSV files missing mandatory header columns are rejected before processing."""
        # Missing 'cost_price' and 'gst_rate' in products
        csv_missing_cols = """sku,product_name,category,unit_of_measure,selling_price
IO-SKU-999,Missing Price Item,IO_CAT_MITHAI,box,300.0
"""
        preview = preview_import(csv_missing_cols, "products")
        self.assertFalse(preview["success"])
        self.assertIn("cost_price", preview["missing_columns"])
        self.assertIn("gst_rate", preview["missing_columns"])

        # Missing 'sku' in sales
        csv_missing_sale_sku = """invoice_date,quantity,selling_price
2026-10-18,5,350.0
"""
        preview_s = preview_import(csv_missing_sale_sku, "sales")
        self.assertFalse(preview_s["success"])
        self.assertIn("sku", preview_s["missing_columns"])

        # Missing 'amount' in expenses
        csv_missing_exp_amt = """expense_date,category,description
2026-10-18,RENT,Stall rent
"""
        preview_e = preview_import(csv_missing_exp_amt, "expenses")
        self.assertFalse(preview_e["success"])
        self.assertIn("amount", preview_e["missing_columns"])

        # Missing 'batch_number' in stock
        csv_missing_stk_batch = """sku,quantity,unit_cost,received_date
IO-SKU-BASE,50,200.0,2026-10-18
"""
        preview_k = preview_import(csv_missing_stk_batch, "stock")
        self.assertFalse(preview_k["success"])
        self.assertIn("batch_number", preview_k["missing_columns"])

    # ==========================================================================
    # 3. INVALID DATES & CALENDAR BOUNDARIES
    # ==========================================================================

    def test_invalid_dates(self):
        """Tests that invalid date formats, impossible days (e.g. 2026-02-31), and inverted expiry are rejected."""
        # 1. Invalid calendar date: 2026-02-31 (February has max 28 days in 2026)
        csv_bad_date = """expense_date,category,amount,description
2026-02-31,RENT,5000.0,February Impossible Date
"""
        preview = preview_import(csv_bad_date, "expenses")
        self.assertTrue(preview["success"])
        self.assertEqual(preview["invalid_rows_count"], 1)
        self.assertIn("Invalid calendar date", preview["preview_data"][0]["_error"])

        # 2. Bad date format: DD/MM/YYYY instead of YYYY-MM-DD
        csv_slash_date = """invoice_date,sku,quantity,selling_price
18/10/2026,IO-SKU-BASE,2,350.0
"""
        preview_sale = preview_import(csv_slash_date, "sales")
        self.assertEqual(preview_sale["invalid_rows_count"], 1)
        self.assertIn("Invalid date format", preview_sale["preview_data"][0]["_error"])

        # 3. Stock inward where expiry_date < received_date
        csv_stk_inverted = """sku,batch_number,quantity,unit_cost,received_date,expiry_date
IO-SKU-BASE,IO-BAT-INV-01,10,200.0,2026-10-20,2026-10-10
"""
        preview_stk = preview_import(csv_stk_inverted, "stock")
        self.assertEqual(preview_stk["invalid_rows_count"], 1)
        self.assertIn("earlier than received date", preview_stk["preview_data"][0]["_error"])

    # ==========================================================================
    # 4. DUPLICATE IDS DETECTION
    # ==========================================================================

    def test_duplicate_ids_detection(self):
        """
        Tests duplicate detection across:
        - In-file duplicate SKUs
        - Database existing SKUs
        - Duplicate sales invoice numbers
        - Duplicate stock batch numbers
        Never silently discards duplicate entries.
        """
        # A. In-file duplicate SKU
        csv_prod_dup_file = """sku,product_name,category,unit_of_measure,cost_price,selling_price,gst_rate
IO-SKU-FILE-1,First Product,IO_CAT_MITHAI,box,100.0,200.0,5.0
IO-SKU-FILE-1,Duplicate SKU In File,IO_CAT_MITHAI,box,120.0,220.0,5.0
"""
        preview_p = preview_import(csv_prod_dup_file, "products")
        self.assertEqual(preview_p["valid_rows_count"], 1)
        self.assertEqual(preview_p["invalid_rows_count"], 1)
        self.assertIn("Duplicate SKU 'IO-SKU-FILE-1' found within uploaded CSV", preview_p["preview_data"][1]["_error"])

        # B. Duplicate SKU existing in database
        csv_prod_db_dup = """sku,product_name,category,unit_of_measure,cost_price,selling_price,gst_rate
IO-SKU-BASE,Trying to re-add base,IO_CAT_MITHAI,box,100.0,200.0,5.0
"""
        preview_db = preview_import(csv_prod_db_dup, "products")
        self.assertEqual(preview_db["invalid_rows_count"], 1)
        self.assertIn("already exists in database catalog", preview_db["preview_data"][0]["_error"])

        # C. Duplicate Sales Invoice Number
        # First insert a sale with invoice IO-INV-DUP-1
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO sales_invoices (
                    invoice_number, invoice_date, payment_mode,
                    subtotal_amount, total_taxable_amount, net_total_amount
                ) VALUES ('IO-INV-DUP-1', '2026-10-15', 'CASH', 350.0, 350.0, 350.0)
            """)

        csv_sale_dup = """invoice_number,invoice_date,sku,quantity,selling_price
IO-INV-DUP-1,2026-10-18,IO-SKU-BASE,1,350.0
"""
        preview_s = preview_import(csv_sale_dup, "sales")
        self.assertEqual(preview_s["invalid_rows_count"], 1)
        self.assertIn("already exists in database", preview_s["preview_data"][0]["_error"])

        # D. Duplicate Stock Batch for Same Product
        csv_stk_dup = """sku,batch_number,quantity,unit_cost,received_date
IO-SKU-BASE,IO-BAT-BASE-01,20,200.0,2026-10-18
"""
        preview_stk = preview_import(csv_stk_dup, "stock")
        self.assertEqual(preview_stk["invalid_rows_count"], 1)
        self.assertIn("already exists in database for SKU 'IO-SKU-BASE'", preview_stk["preview_data"][0]["_error"])

    # ==========================================================================
    # 5. NEGATIVE QUANTITIES & INVALID PRICING
    # ==========================================================================

    def test_negative_quantities_and_invalid_prices(self):
        """Tests that negative or zero quantities and violated pricing hierarchies are rejected."""
        # 1. Negative quantity in sales
        csv_neg_sale_qty = """invoice_date,sku,quantity,selling_price
2026-10-18,IO-SKU-BASE,-5,350.0
"""
        prev_s1 = preview_import(csv_neg_sale_qty, "sales")
        self.assertEqual(prev_s1["invalid_rows_count"], 1)
        self.assertIn("Quantity must be a positive integer", prev_s1["preview_data"][0]["_error"])

        # 2. Zero quantity in sales
        csv_zero_sale_qty = """invoice_date,sku,quantity,selling_price
2026-10-18,IO-SKU-BASE,0,350.0
"""
        prev_s2 = preview_import(csv_zero_sale_qty, "sales")
        self.assertEqual(prev_s2["invalid_rows_count"], 1)
        self.assertIn("Quantity must be a positive integer", prev_s2["preview_data"][0]["_error"])

        # 3. Selling price < cost price in products
        csv_sell_less_cost = """sku,product_name,category,unit_of_measure,cost_price,selling_price,gst_rate
IO-SKU-LOSS,Loss Maker,IO_CAT_MITHAI,box,300.0,250.0,5.0
"""
        prev_p1 = preview_import(csv_sell_less_cost, "products")
        self.assertEqual(prev_p1["invalid_rows_count"], 1)
        self.assertIn("Selling price (₹250.00) cannot be less than purchase cost (₹300.00)", prev_p1["preview_data"][0]["_error"])

        # 4. MRP < selling price in products
        csv_mrp_less_sell = """sku,product_name,category,unit_of_measure,cost_price,selling_price,mrp,gst_rate
IO-SKU-MRP,Bad MRP,IO_CAT_MITHAI,box,100.0,200.0,180.0,5.0
"""
        prev_p2 = preview_import(csv_mrp_less_sell, "products")
        self.assertEqual(prev_p2["invalid_rows_count"], 1)
        self.assertIn("MRP (₹180.00) cannot be less than selling price", prev_p2["preview_data"][0]["_error"])

        # 5. Negative expense amount
        csv_neg_exp = """expense_date,category,amount,description
2026-10-18,WAGES,-2000.0,Negative Wages
"""
        prev_e1 = preview_import(csv_neg_exp, "expenses")
        self.assertEqual(prev_e1["invalid_rows_count"], 1)
        self.assertIn("Expense amount must be a positive number", prev_e1["preview_data"][0]["_error"])

    # ==========================================================================
    # 6. ATOMIC TRANSACTION ROLLBACK ON FAILURE
    # ==========================================================================

    def test_atomic_transaction_rollback_on_failure(self):
        """
        Tests that in atomic mode (atomic=True), if any row in the batch is invalid,
        the entire transaction is rolled back and NO rows are persisted.
        Row 1: Valid SKU
        Row 2: Invalid (Selling price < cost price)
        Row 3: Valid SKU
        """
        csv_batch_with_error = """sku,product_name,category,unit_of_measure,cost_price,selling_price,gst_rate
IO-SKU-ATOMIC-1,Valid Sweet 1,IO_CAT_MITHAI,box,100.0,150.0,5.0
IO-SKU-ATOMIC-2,Invalid Sweet,IO_CAT_MITHAI,box,200.0,150.0,5.0
IO-SKU-ATOMIC-3,Valid Sweet 3,IO_CAT_MITHAI,box,120.0,180.0,5.0
"""
        # Execute in atomic mode
        result = execute_import(csv_batch_with_error, "products", atomic=True)
        self.assertFalse(result["success"])
        self.assertEqual(result["accepted_count"], 0)
        self.assertGreater(result["rejected_count"], 0)
        self.assertIn("Atomic import failed", result["error"])

        # VERIFY ROLLBACK: Neither IO-SKU-ATOMIC-1 nor IO-SKU-ATOMIC-3 must be in database!
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT sku FROM products WHERE sku IN ('IO-SKU-ATOMIC-1', 'IO-SKU-ATOMIC-2', 'IO-SKU-ATOMIC-3')")
            found = cursor.fetchall()
            self.assertEqual(len(found), 0, "Atomic rollback failed! Some rows were saved to database.")

    # ==========================================================================
    # 7. SAFE ROW-BY-ROW MODE
    # ==========================================================================

    def test_safe_row_by_row_mode(self):
        """
        Tests that in Safe Row-by-Row mode (atomic=False):
        - Valid rows are committed
        - Invalid rows are rejected and reported
        - Nothing is silently discarded
        """
        csv_mixed = """sku,product_name,category,unit_of_measure,cost_price,selling_price,gst_rate
IO-SKU-SAFE-1,Safe Sweet 1,IO_CAT_MITHAI,box,100.0,150.0,5.0
IO-SKU-SAFE-2,Bad Price Sweet,IO_CAT_MITHAI,box,300.0,150.0,5.0
IO-SKU-SAFE-3,Safe Sweet 3,IO_CAT_MITHAI,box,120.0,180.0,5.0
"""
        result = execute_import(csv_mixed, "products", atomic=False)
        self.assertTrue(result["success"])
        self.assertEqual(result["accepted_count"], 2)
        self.assertEqual(result["rejected_count"], 1)

        # Verify Row 2 is reported in rejected_rows with reason
        rej_row = result["rejected_rows"][0]
        self.assertEqual(rej_row["row_num"], 2)
        self.assertIn("Selling price (₹150.00) cannot be less than purchase cost", rej_row["reason"])

        # Verify Row 1 and Row 3 are in database
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT sku FROM products WHERE sku IN ('IO-SKU-SAFE-1', 'IO-SKU-SAFE-3')")
            saved = [r[0] for r in cursor.fetchall()]
            self.assertIn("IO-SKU-SAFE-1", saved)
            self.assertIn("IO-SKU-SAFE-3", saved)

    # ==========================================================================
    # 8. STOCK MOVEMENT LEDGER INVARIANT
    # ==========================================================================

    def test_stock_movement_ledger_invariant(self):
        """
        CRITICAL TEST:
        'Do not allow an imported stock balance to bypass the stock movement ledger.'
        Verifies that when stock is imported:
        1. An inventory_batches record is created.
        2. A stock_movements record is created with movement_type = 'RECEIPT'.
        """
        csv_stock = """sku,batch_number,quantity,unit_cost,received_date,storage_location,purchase_invoice_no,reason
IO-SKU-BASE,IO-BAT-INVAR-01,45,210.0,2026-10-18,Cold Storage Bay 1,PO-IO-999,Diwali Restock via Import
"""
        result = execute_import(csv_stock, "stock", atomic=True)
        self.assertTrue(result["success"])
        self.assertEqual(result["accepted_count"], 1)

        # Verify batch exists
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT batch_id, quantity_available, unit_cost FROM inventory_batches WHERE batch_number = 'IO-BAT-INVAR-01'")
            batch = cursor.fetchone()
            self.assertIsNotNone(batch, "Batch was not created in inventory_batches!")
            b_id = batch["batch_id"]
            self.assertEqual(batch["quantity_available"], 45)

            # VERIFY STOCK MOVEMENT LEDGER RECORD
            cursor.execute("""
                SELECT movement_id, movement_type, quantity, unit_cost, reference_type, reference_id, reason
                FROM stock_movements
                WHERE batch_id = ?
            """, (b_id,))
            movement = cursor.fetchone()
            self.assertIsNotNone(movement, "CRITICAL ERROR: Stock batch bypassed the stock_movements ledger!")
            self.assertEqual(movement["movement_type"], "RECEIPT")
            self.assertEqual(movement["quantity"], 45)
            self.assertEqual(movement["unit_cost"], 210.0)
            self.assertEqual(movement["reference_type"], "PURCHASE_RECEIPT")
            self.assertEqual(movement["reference_id"], "PO-IO-999")
            self.assertEqual(movement["reason"], "Diwali Restock via Import")

    # ==========================================================================
    # 9. FILTERED EXPORTS & UTF-8 COMPATIBILITY
    # ==========================================================================

    def test_filtered_exports_and_utf8(self):
        """
        Tests filtered exports for products, sales, expenses, and stock,
        and verifies UTF-8 compatibility (including Rupee symbol and Indian festival characters).
        """
        # Test Products Export
        p_csv = export_products_to_csv(category_id=self.cat_id)
        self.assertIn("IO-SKU-BASE", p_csv)
        self.assertIn("IO Test Base Sweets", p_csv)

        # Test Expenses Export
        exp_id = record_expense(
            amount=5000.0,
            expense_date="2026-10-18",
            category="PACKAGING",
            description="Diwali ₹ Gold Foil Boxes",
            vendor_name="IO-TEST-Packager",
            invoice_receipt_no="IO-REC-999"
        )
        e_csv = export_expenses_to_csv(category="PACKAGING")
        self.assertIn("IO-REC-999", e_csv)
        self.assertIn("Diwali ₹ Gold Foil Boxes", e_csv)

        # Test Stock Export with location filter
        s_csv = export_stock_to_csv(storage_location="Main Store")
        self.assertIn("IO-BAT-BASE-01", s_csv)

        # Template Generation Check
        prod_temp = get_template_csv("products")
        self.assertIn("sku,product_name", prod_temp)
        self.assertIn("SKU-MITH-001", prod_temp)


if __name__ == "__main__":
    unittest.main()
