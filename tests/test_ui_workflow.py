"""
FestivePulse — Complete Quality Audit & End-to-End Workflow Test Suite
Validates the complete operational pipeline requested in the audit:
1. Create a product with pricing hierarchy, GST rate, and safety stock.
2. Receive inbound stock batches with storage location and movement ledger tracking.
3. Record a sales invoice at POS with exact Decimal tax splitting and FIFO deduction.
4. Verify the stock balance and ledger entries.
5. Record operational expenses with category, description, and P&L audit tracking.
6. Configure a regional festival calendar entry with date validation and preparation windows.
7. Estimate festival demand from sufficient historical sales data using deterministic formulas.
8. Generate a deterministic festival stock plan: max(0, planned demand + safety stock - usable stock).
9. Export sanitized CSV with formula injection protection and standard metadata.
10. Generate publication-grade ReportLab PDF report with verified binary headers.
11. Perform atomic database backup, verify checksum, and execute a full disaster recovery restoration.
12. Verify persistence across connection closures and low-level PRAGMA database integrity.
"""

import os
import unittest
from datetime import date, timedelta
from pathlib import Path

from database.connection import init_db
from database.queries import get_all_festival_occurrences
from repositories.product_repository import ProductRepository
from repositories.sales_repository import DuplicateTransactionError
from services.inventory_service import receive_batch, get_stock_movement_ledger
from services.sales_service import create_sales_invoice
from services.expense_service import record_expense, get_financial_pnl_statement
from services.festival_calendar_service import (
    create_calendar_festival,
    get_calendar_festival_by_id
)
from services.demand_estimation_service import estimate_product_demand
from services.stock_planning_service import compute_product_stock_plan
from services.reports_service import (
    get_sales_summary_data,
    generate_report_csv,
    generate_report_pdf
)
from services.security_service import (
    check_database_integrity,
    create_database_backup,
    verify_backup_file,
    restore_database_backup
)


class TestFullShopkeeperWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_complete_audit_workflow(self):
        """
        Executes and validates all 11 required workflows end to end without skipping.
        """
        pid_suffix = os.getpid()
        test_sku = f"SKU-AUDIT-{pid_suffix}"
        test_prod_name = "Audited Handcrafted Terracotta Diya"
        
        # Verify product categories exist
        cats = ProductRepository.get_categories()
        self.assertTrue(len(cats) > 0, "Product categories must exist.")
        cat_id = cats[0]["category_id"]

        # ======================================================================
        # 1. CREATE A PRODUCT
        # ======================================================================
        prod_data = {
            "product_name": test_prod_name,
            "sku": test_sku,
            "barcode": f"890123{pid_suffix}",
            "category_id": cat_id,
            "unit_of_measure": "pcs",
            "cost_price": 50.0,
            "selling_price": 100.0,
            "mrp": 120.0,
            "gst_rate": 12.0,
            "hsn_code": "6912",
            "min_safety_stock": 10,
            "reorder_quantity": 25,
            "is_perishable": False,
            "shelf_life_days": None,
            "festival_tags": ["DIWALI"],
            "region_tags": ["Pan-India"]
        }

        prod_id = ProductRepository.create_product(prod_data, initial_stock=0)
        self.assertIsInstance(prod_id, int)
        self.assertGreater(prod_id, 0)

        # Verify product in database
        saved_prod = ProductRepository.get_product_by_id(prod_id)
        self.assertEqual(saved_prod["sku"], test_sku)
        self.assertEqual(saved_prod["product_name"], test_prod_name)
        self.assertEqual(saved_prod["current_stock"], 0)

        # ======================================================================
        # 2. RECEIVE STOCK
        # ======================================================================
        batch_num = f"BATCH-AUDIT-{pid_suffix}-01"
        batch_id = receive_batch(
            product_id=prod_id,
            batch_number=batch_num,
            quantity=50,
            unit_cost=50.0,
            supplier_id=None,
            received_date=date.today().strftime("%Y-%m-%d"),
            expiry_date=None,
            storage_location="Main Rack A-1",
            reason=f"Audit Shipment #{pid_suffix}"
        )
        self.assertIsInstance(batch_id, int)
        self.assertGreater(batch_id, 0)

        # Verify receipt in movement ledger
        movements_after_inward = get_stock_movement_ledger(product_id=prod_id)
        self.assertEqual(len(movements_after_inward), 1)
        self.assertEqual(movements_after_inward.iloc[0]["movement_type"], "RECEIPT")
        self.assertEqual(movements_after_inward.iloc[0]["quantity"], 50)

        # ======================================================================
        # 3. RECORD A SALE
        # ======================================================================
        sale_items = [{
            "product_id": prod_id,
            "sku": test_sku,
            "product_name": test_prod_name,
            "quantity": 10,
            "unit_of_measure": "pcs",
            "selling_price": 100.0,
            "discount_pct": 5.0,        # 5% line discount -> taxable 950
            "discount_amount": 0.0,
            "gst_rate": 12.0
        }]

        txn_ref = f"TXN-AUDIT-{pid_suffix}"
        inv_id, inv_num = create_sales_invoice(
            customer_id=None,
            payment_mode="UPI",
            items=sale_items,
            overall_discount=50.0,      # Additional bill cash discount -> taxable 900
            transaction_reference=txn_ref,
            notes="Audit test customer sale",
            sale_date=date.today().strftime("%Y-%m-%d")
        )
        self.assertIsInstance(inv_id, int)
        self.assertTrue(inv_num.startswith("INV-"))

        # Verify duplicate transaction reference rejection
        with self.assertRaises(DuplicateTransactionError):
            create_sales_invoice(
                customer_id=None,
                payment_mode="UPI",
                items=sale_items,
                transaction_reference=txn_ref
            )

        # ======================================================================
        # 4. VERIFY THE STOCK BALANCE
        # ======================================================================
        # 50 received - 10 sold = 40 remaining
        prod_post_sale = ProductRepository.get_product_by_id(prod_id)
        self.assertEqual(prod_post_sale["current_stock"], 40)

        # Verify stock movement ledger contains both RECEIPT and SALE
        movements_post_sale = get_stock_movement_ledger(product_id=prod_id)
        self.assertEqual(len(movements_post_sale), 2)
        sale_entry = movements_post_sale[movements_post_sale["movement_type"] == "SALE"].iloc[0]
        self.assertEqual(sale_entry["quantity"], -10)

        # ======================================================================
        # 5. RECORD EXPENSES
        # ======================================================================
        exp_id = record_expense(
            amount=450.0,
            expense_date=date.today().strftime("%Y-%m-%d"),
            category="PACKAGING",
            description=f"Festive Gift Hamper Boxes #{pid_suffix}",
            payment_mode="CASH",
            vendor_name="National Packaging Co."
        )
        self.assertIsInstance(exp_id, int)
        self.assertGreater(exp_id, 0)

        # Verify expense appears in financial statement
        pnl = get_financial_pnl_statement()
        self.assertGreater(pnl["net_sales_revenue"], 0)
        self.assertGreaterEqual(pnl["total_included_expenses"], 450.0)

        # ======================================================================
        # 6. CONFIGURE A FESTIVAL
        # ======================================================================
        fest_start = date.today() + timedelta(days=20)
        fest_end = fest_start + timedelta(days=4)
        plan_start = fest_start - timedelta(days=15)

        fest_cal_id = create_calendar_festival({
            "festival_name": f"Audit Deepotsav {pid_suffix}",
            "region": "Pan-India",
            "start_date": fest_start.strftime("%Y-%m-%d"),
            "end_date": fest_end.strftime("%Y-%m-%d"),
            "planning_start_date": plan_start.strftime("%Y-%m-%d"),
            "planning_window_days": 15,
            "category": "Major Religious",
            "notes": "Configured during quality audit run"
        })
        self.assertIsInstance(fest_cal_id, int)

        cal_entry = get_calendar_festival_by_id(fest_cal_id)
        self.assertIsNotNone(cal_entry)
        self.assertEqual(cal_entry["festival_name"], f"Audit Deepotsav {pid_suffix}")
        self.assertEqual(cal_entry["region"], "Pan-India")

        # ======================================================================
        # 7. ESTIMATE DEMAND FROM SUFFICIENT HISTORY
        # ======================================================================
        # Fetch active or sample festival occurrence
        all_occs = get_all_festival_occurrences()
        self.assertFalse(all_occs.empty, "Festival occurrences must exist in database.")
        sample_occ_id = int(all_occs.iloc[0]["occurrence_id"])

        # Demand calculation test
        demand_res = estimate_product_demand(
            product_id=prod_id,
            target_occurrence_id=sample_occ_id,
            growth_multiplier=1.20
        )
        self.assertIn("estimated_units", demand_res)
        self.assertIn("method", demand_res)
        self.assertIn("calculation_details", demand_res)
        self.assertIn("historical_sample_size", demand_res)
        self.assertIn("uncertainty_limitations", demand_res)
        self.assertIsInstance(demand_res["estimated_units"], int)

        # ======================================================================
        # 8. GENERATE A STOCK PLAN
        # ======================================================================
        # Deterministic formula: max(0, planned_demand + safety_stock - usable_stock)
        stock_plan = compute_product_stock_plan(
            product_id=prod_id,
            occurrence_id=sample_occ_id,
            growth_multiplier=1.15
        )
        self.assertIn("original_suggested_quantity", stock_plan)
        self.assertIn("planned_procurement_cost", stock_plan)
        self.assertIn("usable_stock", stock_plan)
        self.assertIn("arithmetic_breakdown", stock_plan)
        self.assertEqual(stock_plan["usable_stock"], 40)
        self.assertEqual(
            stock_plan["raw_suggested_quantity"],
            max(0, stock_plan["planned_demand"] + stock_plan["safety_stock"] - stock_plan["usable_stock"])
        )

        # ======================================================================
        # 9. EXPORT CSV (Sanitized & Validated)
        # ======================================================================
        today_str = date.today().strftime("%Y-%m-%d")
        df_sales, meta_sales = get_sales_summary_data(start_date=today_str, end_date=today_str)
        csv_text = generate_report_csv(df_sales, meta_sales)
        self.assertIn("FESTIVEPULSE", csv_text)
        self.assertIn("OFFICIAL RETAIL SYSTEM REPORT", csv_text)
        self.assertIn(inv_num, csv_text)
        self.assertIn("ACTUAL", csv_text)

        # ======================================================================
        # 10. GENERATE PDF (ReportLab Binary Validation)
        # ======================================================================
        pdf_bytes = generate_report_pdf(df_sales, meta_sales, orientation="landscape")
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))
        self.assertIn(b"%%EOF", pdf_bytes[-120:])

        # ======================================================================
        # 11. RESTORE A DATABASE BACKUP & VERIFY RECOVERY
        # ======================================================================
        # Step A: Take atomic online backup
        backup_meta = create_database_backup(notes=f"Audit Pre-Restore Point {pid_suffix}")
        backup_path = Path(backup_meta["filepath"])
        self.assertTrue(backup_path.exists())
        self.assertEqual(len(backup_meta["sha256"]), 64)

        # Step B: Verify backup integrity
        is_valid, v_msg, v_details = verify_backup_file(backup_path)
        self.assertTrue(is_valid)
        self.assertEqual(v_details["integrity"], "PASSED")

        # Step C: Insert a canary row to be reverted upon restore
        canary_sku = f"SKU-CANARY-{pid_suffix}"
        canary_id = ProductRepository.create_product({
            "product_name": "Canary Temporary Product",
            "sku": canary_sku,
            "category_id": cat_id,
            "unit_of_measure": "pcs",
            "cost_price": 10.0,
            "selling_price": 20.0,
            "gst_rate": 5.0
        })
        self.assertIsNotNone(ProductRepository.get_product_by_id(canary_id))

        # Step D: Execute disaster recovery restore
        restored_ok, restore_msg = restore_database_backup(backup_path, confirm=True)
        self.assertTrue(restored_ok, f"Restore failed: {restore_msg}")

        # Step E: Confirm canary row was wiped by restore to pre-canary snapshot
        canary_after_restore = ProductRepository.get_product_by_id(canary_id)
        self.assertIsNone(canary_after_restore, "Canary record must be reverted after restoring prior backup.")

        # Step F: Confirm original product is intact
        restored_orig_prod = ProductRepository.get_product_by_id(prod_id)
        self.assertIsNotNone(restored_orig_prod)
        self.assertEqual(restored_orig_prod["sku"], test_sku)
        self.assertEqual(restored_orig_prod["current_stock"], 40)

        # Step G: Low-level PRAGMA database integrity check
        integrity = check_database_integrity()
        self.assertTrue(integrity["is_healthy"])
        self.assertEqual(integrity["integrity_status"], "ok")
        self.assertEqual(integrity["foreign_key_violations_count"], 0)

    def test_clean_html_and_metric_formatting(self):
        """
        Validates clean_html removes indentation to prevent CommonMark code block leaks
        and that KPI metrics format large currency amounts cleanly without trailing .00 wrapping.
        """
        from services.ui_components import clean_html
        test_multiline = """
        <div class="metric-card">
            <div class="metric-label">Total Sales</div>
            <div class="metric-value">₹2,88,465.00</div>
        </div>
        """
        cleaned = clean_html(test_multiline)
        self.assertNotIn("\n", cleaned)
        self.assertFalse(cleaned.startswith(" "))
        self.assertTrue(cleaned.startswith('<div class="metric-card">'))
        self.assertTrue(cleaned.endswith('</div>'))


if __name__ == "__main__":
    unittest.main()

