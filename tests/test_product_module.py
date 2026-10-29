"""
FestivePulse — Automated Tests for Complete Product Management Module
Covers CRUD, validations, duplicate SKUs, opening stock persistence, deactivation, and deletion protection.
"""

import unittest
from database.connection import init_db
from repositories.product_repository import (
    ProductRepository, DuplicateSkuError, ProductReferencedError, ProductValidationError
)
from repositories.inventory_repository import InventoryRepository


class TestProductManagementModule(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Fresh baseline database
        init_db(force_recreate=True)

    def test_01_create_product_and_persistence(self):
        """Tests complete product creation with all fields and SQLite persistence."""
        payload = {
            "sku": "SKU-TEST-SWEET-01",
            "barcode": "890123400001",
            "product_name": "Authentic Kaju Katli (250g)",
            "category_id": 1,
            "unit_of_measure": "box",
            "cost_price": 180.0,
            "selling_price": 280.0,
            "mrp": 300.0,
            "gst_rate": 5.0,
            "hsn_code": "21069099",
            "min_safety_stock": 25,
            "reorder_quantity": 60,
            "is_perishable": True,
            "shelf_life_days": 12,
            "festival_tags": ["DIWALI", "GANESH_CHATURTHI"],
            "region_tags": ["Pan-India", "West"]
        }
        prod_id = ProductRepository.create_product(payload)
        self.assertGreater(prod_id, 0)

        # Retrieve and verify persistence
        saved = ProductRepository.get_product_by_id(prod_id)
        self.assertIsNotNone(saved)
        self.assertEqual(saved["sku"], "SKU-TEST-SWEET-01")
        self.assertEqual(saved["product_name"], "Authentic Kaju Katli (250g)")
        self.assertEqual(saved["cost_price"], 180.0)
        self.assertEqual(saved["selling_price"], 280.0)
        self.assertEqual(saved["mrp"], 300.0)
        self.assertEqual(saved["min_safety_stock"], 25)
        self.assertEqual(saved["reorder_quantity"], 60)
        self.assertEqual(saved["unit_of_measure"], "box")
        self.assertIn("DIWALI", saved["festival_tags"])
        self.assertIn("West", saved["region_tags"])
        self.assertEqual(saved["is_active"], 1)

    def test_02_duplicate_sku_rejection(self):
        """Verifies that duplicate SKU creation is blocked with DuplicateSkuError."""
        payload = {
            "sku": "SKU-DUP-CHECK",
            "product_name": "First Instance Product",
            "category_id": 1,
            "unit_of_measure": "pcs",
            "cost_price": 50.0,
            "selling_price": 80.0,
            "gst_rate": 5.0
        }
        ProductRepository.create_product(payload)

        # Attempt duplicate
        dup_payload = {
            "sku": "SKU-DUP-CHECK",
            "product_name": "Second Instance Duplicate Product",
            "category_id": 1,
            "unit_of_measure": "pcs",
            "cost_price": 60.0,
            "selling_price": 90.0,
            "gst_rate": 5.0
        }
        with self.assertRaises(DuplicateSkuError) as ctx:
            ProductRepository.create_product(dup_payload)
        self.assertIn("already exists", str(ctx.exception))

    def test_03_price_validations(self):
        """Verifies non-negative prices and selling_price >= cost_price."""
        # Selling price < Cost price
        with self.assertRaises(ProductValidationError) as ctx:
            ProductRepository.create_product({
                "sku": "SKU-PRICE-VAL-1",
                "product_name": "Loss Making Item",
                "category_id": 1,
                "unit_of_measure": "pcs",
                "cost_price": 100.0,
                "selling_price": 80.0,
                "gst_rate": 5.0
            })
        self.assertIn("cannot be less than purchase cost", str(ctx.exception))

        # Negative cost price
        with self.assertRaises(ProductValidationError) as ctx:
            ProductRepository.create_product({
                "sku": "SKU-PRICE-VAL-2",
                "product_name": "Negative Cost Item",
                "category_id": 1,
                "unit_of_measure": "pcs",
                "cost_price": -20.0,
                "selling_price": 80.0,
                "gst_rate": 5.0
            })
        self.assertIn("cannot be negative", str(ctx.exception))

        # MRP < Selling price
        with self.assertRaises(ProductValidationError) as ctx:
            ProductRepository.create_product({
                "sku": "SKU-PRICE-VAL-3",
                "product_name": "Bad MRP Item",
                "category_id": 1,
                "unit_of_measure": "pcs",
                "cost_price": 50.0,
                "selling_price": 80.0,
                "mrp": 70.0,
                "gst_rate": 5.0
            })
        self.assertIn("MRP", str(ctx.exception))

    def test_04_quantity_and_required_field_validations(self):
        """Verifies non-negative quantities and mandatory fields."""
        # Empty Name
        with self.assertRaises(ProductValidationError) as ctx:
            ProductRepository.create_product({
                "sku": "SKU-NO-NAME",
                "product_name": "",
                "category_id": 1,
                "unit_of_measure": "pcs",
                "cost_price": 50.0,
                "selling_price": 80.0
            })
        self.assertIn("Product name is mandatory", str(ctx.exception))

        # Empty SKU
        with self.assertRaises(ProductValidationError) as ctx:
            ProductRepository.create_product({
                "sku": "   ",
                "product_name": "Valid Name",
                "category_id": 1,
                "unit_of_measure": "pcs",
                "cost_price": 50.0,
                "selling_price": 80.0
            })
        self.assertIn("SKU code is mandatory", str(ctx.exception))

        # Negative reorder level
        with self.assertRaises(ProductValidationError) as ctx:
            ProductRepository.create_product({
                "sku": "SKU-NEG-REORDER",
                "product_name": "Item Neg Reorder",
                "category_id": 1,
                "unit_of_measure": "pcs",
                "cost_price": 50.0,
                "selling_price": 80.0,
                "min_safety_stock": -5
            })
        self.assertIn("cannot be negative", str(ctx.exception))

    def test_05_opening_stock_batch_persistence(self):
        """Verifies that specifying initial_stock atomically creates an opening inventory batch."""
        p_id = ProductRepository.create_product(
            data={
                "sku": "SKU-OPENING-STOCK",
                "product_name": "Opening Stock Brass Diya",
                "category_id": 3,
                "unit_of_measure": "set",
                "cost_price": 250.0,
                "selling_price": 450.0,
                "gst_rate": 0.0,
                "min_safety_stock": 10,
                "reorder_quantity": 30
            },
            initial_stock=80,
            initial_storage_location="Warehouse Bay 4"
        )
        saved = ProductRepository.get_product_by_id(p_id)
        self.assertEqual(saved["current_stock"], 80)

        # Verify batch details
        batches = InventoryRepository.get_batches_for_product(p_id)
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0]["quantity_available"], 80)
        self.assertEqual(batches[0]["storage_location"], "Warehouse Bay 4")

    def test_06_product_update(self):
        """Tests updating product attributes with persistence."""
        p_id = ProductRepository.create_product({
            "sku": "SKU-UPDATE-ME",
            "product_name": "Original Name",
            "category_id": 2,
            "unit_of_measure": "pcs",
            "cost_price": 400.0,
            "selling_price": 700.0,
            "gst_rate": 5.0
        })

        success = ProductRepository.update_product(p_id, {
            "sku": "SKU-UPDATE-ME",
            "product_name": "Updated Festive Sherwani",
            "category_id": 2,
            "unit_of_measure": "set",
            "cost_price": 450.0,
            "selling_price": 850.0,
            "mrp": 999.0,
            "gst_rate": 5.0,
            "hsn_code": "62032900",
            "min_safety_stock": 15,
            "reorder_quantity": 40,
            "is_perishable": False,
            "shelf_life_days": None,
            "festival_tags": ["DIWALI", "EID_FITR"],
            "region_tags": ["North"]
        })
        self.assertTrue(success)

        refetched = ProductRepository.get_product_by_id(p_id)
        self.assertEqual(refetched["product_name"], "Updated Festive Sherwani")
        self.assertEqual(refetched["cost_price"], 450.0)
        self.assertEqual(refetched["selling_price"], 850.0)
        self.assertEqual(refetched["mrp"], 999.0)
        self.assertIn("EID_FITR", refetched["festival_tags"])

    def test_07_search_and_filters(self):
        """Tests catalog querying by category, festival, region, and search query."""
        all_prods = ProductRepository.get_all_products(search="Kaju Katli")
        self.assertGreaterEqual(len(all_prods), 1)
        self.assertTrue(any("Kaju Katli" in p["product_name"] for p in all_prods))

        diwali_prods = ProductRepository.get_all_products(festival_tag="DIWALI")
        self.assertGreaterEqual(len(diwali_prods), 1)

    def test_08_deactivate_and_reactivate(self):
        """Tests soft deactivation and reactivation lifecycle."""
        p_id = ProductRepository.create_product({
            "sku": "SKU-DEACT-TEST",
            "product_name": "Temporary Festive Banner",
            "category_id": 4,
            "unit_of_measure": "pcs",
            "cost_price": 50.0,
            "selling_price": 100.0,
            "gst_rate": 18.0
        })

        # Deactivate
        ProductRepository.deactivate_product(p_id)
        inactive_item = ProductRepository.get_product_by_id(p_id)
        self.assertEqual(inactive_item["is_active"], 0)

        # Verify excluded from default active list
        active_list = ProductRepository.get_all_products(include_inactive=False)
        self.assertFalse(any(p["product_id"] == p_id for p in active_list))

        # Reactivate
        ProductRepository.reactivate_product(p_id)
        reactivated_item = ProductRepository.get_product_by_id(p_id)
        self.assertEqual(reactivated_item["is_active"], 1)

    def test_09_deletion_protection_for_referenced_products(self):
        """Verifies that products with sales or stock history cannot be permanently deleted."""
        # Product 1 is seeded with inventory batches and historical sales
        refs = ProductRepository.get_product_reference_counts(1)
        self.assertGreater(refs["total_references"], 0)

        with self.assertRaises(ProductReferencedError) as ctx:
            ProductRepository.delete_product(1)
        self.assertIn("Cannot permanently delete", str(ctx.exception))

    def test_10_safe_permanent_deletion_of_unreferenced_product(self):
        """Verifies that a newly created product with zero history can be permanently deleted."""
        p_id = ProductRepository.create_product({
            "sku": "SKU-TO-BE-DELETED",
            "product_name": "Unsold Scratch Sample",
            "category_id": 4,
            "unit_of_measure": "pcs",
            "cost_price": 20.0,
            "selling_price": 40.0,
            "gst_rate": 18.0
        })
        # Verify it has zero references
        refs = ProductRepository.get_product_reference_counts(p_id)
        self.assertEqual(refs["total_references"], 0)

        deleted = ProductRepository.delete_product(p_id)
        self.assertTrue(deleted)
        self.assertIsNone(ProductRepository.get_product_by_id(p_id))


if __name__ == "__main__":
    unittest.main()
