"""
FestivePulse — Complete Product Repository & Business Safeguards
CRUD, duplicate SKU handling, history-referencing protection, and validation.
"""

import json
import sqlite3
from typing import List, Dict, Any, Optional
from database.connection import get_db_connection, db_session


class DuplicateSkuError(ValueError):
    """Raised when an attempt is made to create or update a product with an existing SKU."""
    pass


class ProductReferencedError(Exception):
    """Raised when attempting to delete a product that has historical sales or inventory records."""
    pass


class ProductValidationError(ValueError):
    """Raised when field validations (prices, negative quantities, mandatory fields) fail."""
    pass


class ProductRepository:

    @staticmethod
    def validate_product_payload(data: Dict[str, Any], is_update: bool = False) -> None:
        """
        Validates required fields, non-negative quantities, and price relationships.
        """
        # Required fields
        p_name = str(data.get("product_name", "")).strip()
        sku = str(data.get("sku", "")).strip().upper()
        if not p_name:
            raise ProductValidationError("Product name is mandatory.")
        if not sku:
            raise ProductValidationError("SKU code is mandatory.")

        if "category_id" not in data or not data["category_id"]:
            raise ProductValidationError("Category is mandatory.")

        # Non-negative prices and costs
        try:
            cost_price = float(data.get("cost_price", 0.0))
            selling_price = float(data.get("selling_price", 0.0))
        except (ValueError, TypeError):
            raise ProductValidationError("Cost price and selling price must be valid numbers.")

        if cost_price < 0:
            raise ProductValidationError("Purchase cost cannot be negative.")
        if selling_price < 0:
            raise ProductValidationError("Selling price cannot be negative.")
        if selling_price < cost_price:
            raise ProductValidationError(
                f"Selling price (₹{selling_price:.2f}) cannot be less than purchase cost (₹{cost_price:.2f})."
            )

        mrp_raw = data.get("mrp")
        if mrp_raw is not None and str(mrp_raw).strip() != "":
            try:
                mrp = float(mrp_raw)
                if mrp < selling_price:
                    raise ProductValidationError(
                        f"MRP (₹{mrp:.2f}) cannot be less than selling price (₹{selling_price:.2f})."
                    )
            except ValueError:
                raise ProductValidationError("MRP must be a valid number.")

        # Non-negative stock levels
        safety_stock = int(data.get("min_safety_stock", 10))
        reorder_qty = int(data.get("reorder_quantity", 50))
        if safety_stock < 0:
            raise ProductValidationError("Min safety stock (reorder level) cannot be negative.")
        if reorder_qty <= 0:
            raise ProductValidationError("Reorder pack quantity must be greater than zero.")

        # Unit of measure
        from config import UNITS_OF_MEASURE
        uom = str(data.get("unit_of_measure", "pcs")).strip().lower()
        if uom not in UNITS_OF_MEASURE:
            raise ProductValidationError(f"Invalid unit of measure '{uom}'. Allowed: {', '.join(UNITS_OF_MEASURE)}")

        # GST Slab validation
        from config import GST_SLABS
        try:
            gst_rate = float(data.get("gst_rate", 5.0))
            if gst_rate not in GST_SLABS:
                raise ProductValidationError(f"Invalid GST slab: {gst_rate}%. Must be in {GST_SLABS}.")
        except ValueError:
            raise ProductValidationError("GST slab must be a valid percentage.")

    @staticmethod
    def is_sku_available(sku: str, exclude_product_id: Optional[int] = None) -> bool:
        """
        Checks whether the SKU is available or already in use.
        """
        sku_clean = sku.strip().upper()
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            if exclude_product_id:
                cursor.execute("SELECT product_id FROM products WHERE sku = ? AND product_id != ?", (sku_clean, exclude_product_id))
            else:
                cursor.execute("SELECT product_id FROM products WHERE sku = ?", (sku_clean,))
            return cursor.fetchone() is None
        finally:
            conn.close()

    @staticmethod
    def create_product(
        data: Dict[str, Any],
        initial_stock: int = 0,
        initial_storage_location: str = "Main Store",
        supplier_id: Optional[int] = None
    ) -> int:
        """
        Creates a new product with full validation, unique SKU enforcement,
        and optional initial opening stock creation inside an atomic transaction.
        """
        ProductRepository.validate_product_payload(data)

        sku_clean = data["sku"].strip().upper()
        if not ProductRepository.is_sku_available(sku_clean):
            raise DuplicateSkuError(f"A product with SKU '{sku_clean}' already exists in the catalog.")

        tags_json = json.dumps(data.get("festival_tags", []))
        regions_json = json.dumps(data.get("region_tags", []))

        sql_product = """
            INSERT INTO products (
                sku, barcode, product_name, category_id, unit_of_measure,
                cost_price, selling_price, mrp, gst_rate, hsn_code,
                min_safety_stock, reorder_quantity, is_perishable, shelf_life_days,
                festival_tags, region_tags, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """
        params = (
            sku_clean,
            data.get("barcode", "").strip() or None,
            data["product_name"].strip(),
            int(data["category_id"]),
            data["unit_of_measure"].strip().lower(),
            float(data["cost_price"]),
            float(data["selling_price"]),
            float(data.get("mrp") or data["selling_price"]),
            float(data["gst_rate"]),
            data.get("hsn_code", "").strip() or None,
            int(data.get("min_safety_stock", 10)),
            int(data.get("reorder_quantity", 50)),
            1 if data.get("is_perishable") else 0,
            int(data["shelf_life_days"]) if data.get("is_perishable") and data.get("shelf_life_days") else None,
            tags_json,
            regions_json
        )

        with db_session() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(sql_product, params)
                new_product_id = cursor.lastrowid
            except sqlite3.IntegrityError as err:
                if "UNIQUE constraint failed: products.sku" in str(err):
                    raise DuplicateSkuError(f"A product with SKU '{sku_clean}' already exists.")
                raise

            # If opening stock specified, create initial batch atomically
            if initial_stock > 0:
                from datetime import date
                batch_number = f"OPENING-{sku_clean}"
                cursor.execute("""
                    INSERT INTO inventory_batches (
                        product_id, batch_number, supplier_id, received_date,
                        expiry_date, quantity_received, quantity_available, unit_cost, storage_location
                    ) VALUES (?, ?, ?, DATE('now'), ?, ?, ?, ?, ?)
                """, (
                    new_product_id,
                    batch_number,
                    supplier_id,
                    data.get("expiry_date"),
                    initial_stock,
                    initial_stock,
                    float(data["cost_price"]),
                    initial_storage_location
                ))
                opening_batch_id = cursor.lastrowid
                cursor.execute("""
                    INSERT INTO stock_movements (
                        product_id, batch_id, movement_type, quantity, unit_cost,
                        total_cost_impact, reference_type, reference_id, reason
                    ) VALUES (?, ?, 'OPENING_STOCK', ?, ?, ?, 'OPENING_STOCK', ?, ?)
                """, (
                    new_product_id,
                    opening_batch_id,
                    initial_stock,
                    float(data["cost_price"]),
                    round(initial_stock * float(data["cost_price"]), 2),
                    batch_number,
                    f"Opening stock balance initialized for {sku_clean}"
                ))

            return new_product_id

    @staticmethod
    def get_product_by_id(product_id: int) -> Optional[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT p.*, c.category_name,
                       COALESCE(SUM(b.quantity_available), 0) AS current_stock
                FROM products p
                JOIN product_categories c ON p.category_id = c.category_id
                LEFT JOIN inventory_batches b ON p.product_id = b.product_id AND (b.expiry_date IS NULL OR b.expiry_date >= DATE('now'))
                WHERE p.product_id = ?
                GROUP BY p.product_id
            """, (product_id,))
            row = cursor.fetchone()
            if row:
                res = dict(row)
                try:
                    res["festival_tags"] = json.loads(res["festival_tags"]) if res["festival_tags"] else []
                except Exception:
                    res["festival_tags"] = []
                try:
                    res["region_tags"] = json.loads(res["region_tags"]) if res["region_tags"] else []
                except Exception:
                    res["region_tags"] = []
                return res
            return None
        finally:
            conn.close()

    @staticmethod
    def get_product_by_sku(sku: str) -> Optional[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT p.*, c.category_name,
                       COALESCE(SUM(b.quantity_available), 0) AS current_stock
                FROM products p
                JOIN product_categories c ON p.category_id = c.category_id
                LEFT JOIN inventory_batches b ON p.product_id = b.product_id AND (b.expiry_date IS NULL OR b.expiry_date >= DATE('now'))
                WHERE p.sku = ?
                GROUP BY p.product_id
            """, (sku.strip().upper(),))
            row = cursor.fetchone()
            if row:
                res = dict(row)
                try:
                    res["festival_tags"] = json.loads(res["festival_tags"]) if res["festival_tags"] else []
                except Exception:
                    res["festival_tags"] = []
                try:
                    res["region_tags"] = json.loads(res["region_tags"]) if res["region_tags"] else []
                except Exception:
                    res["region_tags"] = []
                return res
            return None
        finally:
            conn.close()

    @staticmethod
    def get_all_products(
        category_id: Optional[int] = None,
        festival_tag: Optional[str] = None,
        region_tag: Optional[str] = None,
        search: Optional[str] = None,
        include_inactive: bool = False
    ) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            sql = """
                SELECT p.*, c.category_name,
                       COALESCE(SUM(b.quantity_available), 0) AS current_stock,
                       CASE 
                           WHEN p.is_active = 0 THEN 'DEACTIVATED'
                           WHEN COALESCE(SUM(b.quantity_available), 0) = 0 THEN 'OUT_OF_STOCK'
                           WHEN COALESCE(SUM(b.quantity_available), 0) <= p.min_safety_stock THEN 'CRITICAL'
                           WHEN COALESCE(SUM(b.quantity_available), 0) > (p.min_safety_stock + p.reorder_quantity * 2) THEN 'OVERSTOCKED'
                           ELSE 'ADEQUATE'
                       END AS stock_status
                FROM products p
                JOIN product_categories c ON p.category_id = c.category_id
                LEFT JOIN inventory_batches b ON p.product_id = b.product_id AND (b.expiry_date IS NULL OR b.expiry_date >= DATE('now'))
                WHERE 1=1
            """
            params = []
            if not include_inactive:
                sql += " AND p.is_active = 1"
            if category_id:
                sql += " AND p.category_id = ?"
                params.append(category_id)
            if search:
                sql += " AND (p.product_name LIKE ? OR p.sku LIKE ? OR p.barcode LIKE ?)"
                term = f"%{search.strip()}%"
                params.extend([term, term, term])

            sql += " GROUP BY p.product_id ORDER BY p.product_name ASC"
            cursor.execute(sql, params)
            rows = [dict(r) for r in cursor.fetchall()]

            # Decode JSON tags and filter if requested
            filtered = []
            for r in rows:
                try:
                    r["festival_tags"] = json.loads(r["festival_tags"]) if r["festival_tags"] else []
                except Exception:
                    r["festival_tags"] = []
                try:
                    r["region_tags"] = json.loads(r["region_tags"]) if r["region_tags"] else []
                except Exception:
                    r["region_tags"] = []

                if festival_tag and festival_tag not in r["festival_tags"]:
                    continue
                if region_tag and region_tag not in r["region_tags"]:
                    continue
                filtered.append(r)

            return filtered
        finally:
            conn.close()

    @staticmethod
    def update_product(product_id: int, data: Dict[str, Any]) -> bool:
        if "sku" not in data or not str(data["sku"]).strip():
            existing = ProductRepository.get_product_by_id(product_id)
            if existing:
                data["sku"] = existing["sku"]

        ProductRepository.validate_product_payload(data, is_update=True)

        sku_clean = data["sku"].strip().upper()
        if not ProductRepository.is_sku_available(sku_clean, exclude_product_id=product_id):
            raise DuplicateSkuError(f"SKU '{sku_clean}' is already assigned to another product.")

        tags_json = json.dumps(data.get("festival_tags", []))
        regions_json = json.dumps(data.get("region_tags", []))

        sql = """
            UPDATE products
            SET sku = ?, barcode = ?, product_name = ?, category_id = ?, unit_of_measure = ?,
                cost_price = ?, selling_price = ?, mrp = ?, gst_rate = ?, hsn_code = ?,
                min_safety_stock = ?, reorder_quantity = ?, is_perishable = ?,
                shelf_life_days = ?, festival_tags = ?, region_tags = ?, updated_at = CURRENT_TIMESTAMP
            WHERE product_id = ?
        """
        params = (
            sku_clean,
            data.get("barcode", "").strip() or None,
            data["product_name"].strip(),
            int(data["category_id"]),
            data["unit_of_measure"].strip().lower(),
            float(data["cost_price"]),
            float(data["selling_price"]),
            float(data.get("mrp") or data["selling_price"]),
            float(data["gst_rate"]),
            data.get("hsn_code", "").strip() or None,
            int(data.get("min_safety_stock", 10)),
            int(data.get("reorder_quantity", 50)),
            1 if data.get("is_perishable") else 0,
            int(data["shelf_life_days"]) if data.get("is_perishable") and data.get("shelf_life_days") else None,
            tags_json,
            regions_json,
            product_id
        )
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return cursor.rowcount > 0

    @staticmethod
    def deactivate_product(product_id: int) -> bool:
        """
        Deactivates a product so it no longer appears in POS counter billing or stock ordering,
        while maintaining full historical sales and ledger integrity.
        """
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE products SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE product_id = ?", (product_id,))
            return cursor.rowcount > 0

    @staticmethod
    def reactivate_product(product_id: int) -> bool:
        """
        Reactivates a previously deactivated product.
        """
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE products SET is_active = 1, updated_at = CURRENT_TIMESTAMP WHERE product_id = ?", (product_id,))
            return cursor.rowcount > 0

    @staticmethod
    def get_product_reference_counts(product_id: int) -> Dict[str, int]:
        """
        Checks how many historical records reference this product.
        """
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM sales_items WHERE product_id = ?", (product_id,))
            sales_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM inventory_batches WHERE product_id = ?", (product_id,))
            batch_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM stock_adjustments WHERE product_id = ?", (product_id,))
            adj_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM stock_movements WHERE product_id = ?", (product_id,))
            mov_count = cursor.fetchone()[0]

            return {
                "sales_items": sales_count,
                "inventory_batches": batch_count,
                "stock_adjustments": adj_count,
                "stock_movements": mov_count,
                "total_references": sales_count + batch_count + adj_count + mov_count
            }
        finally:
            conn.close()

    @staticmethod
    def delete_product(product_id: int, force: bool = False, hard_delete: bool = True) -> bool:
        """
        Safely deletes a product only if it has NO historical references.
        If hard_delete is False, deactivates the product instead.
        If it has sales, batches, or adjustments, raises ProductReferencedError.
        """
        if not hard_delete:
            return ProductRepository.deactivate_product(product_id)

        refs = ProductRepository.get_product_reference_counts(product_id)
        if refs["total_references"] > 0 and not force:
            raise ProductReferencedError(
                f"Cannot permanently delete this product: It has {refs['sales_items']} sales transaction(s), "
                f"{refs['inventory_batches']} inventory batch(es), {refs['stock_adjustments']} stock adjustment(s), "
                f"and {refs['stock_movements']} ledger movement(s). "
                f"Please deactivate it instead to maintain auditable accounting history."
            )

        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM products WHERE product_id = ?", (product_id,))
            return cursor.rowcount > 0

    @staticmethod
    def get_categories() -> List[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM product_categories ORDER BY category_name ASC")
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def create_category(name: str, default_gst_rate: float, description: str = "") -> int:
        sql = "INSERT INTO product_categories (category_name, default_gst_rate, description) VALUES (?, ?, ?)"
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (name.strip(), float(default_gst_rate), description.strip()))
            return cursor.lastrowid
