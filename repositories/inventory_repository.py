"""
FestivePulse — Inventory Repository
Enterprise-grade stock management with an auditable stock movement ledger,
FIFO batch tracking, strict non-negative stock policies, duplicate batch protection,
and deterministic stock reconciliation.
"""

from datetime import date, datetime
import sqlite3
from typing import List, Dict, Any, Optional
from database.connection import get_db_connection, db_session


class InsufficientStockError(Exception):
    """Raised when an operation would cause batch or product stock to become negative."""
    pass


class DuplicateBatchError(Exception):
    """Raised when attempting to create a batch with a duplicate batch number for the same product."""
    pass


class InvalidMovementError(Exception):
    """Raised when a stock movement has invalid arguments (e.g. 0 quantity, invalid type, missing reason)."""
    pass


class UnauthorizedNegativeStockError(Exception):
    """Raised when a negative stock adjustment is attempted without authorized manager credentials."""
    pass


VALID_MOVEMENT_TYPES = {
    'RECEIPT',
    'SALE',
    'SALE_CANCEL',
    'DAMAGE',
    'EXPIRED',
    'THEFT_SHRINKAGE',
    'PROMOTIONAL_SAMPLE',
    'MANUAL_COUNT_RECONCILIATION',
    'OPENING_STOCK',
    'RETURN_TO_SUPPLIER'
}


class InventoryRepository:

    @staticmethod
    def create_batch(
        product_id: int,
        batch_number: str,
        quantity: int,
        unit_cost: float,
        supplier_id: Optional[int] = None,
        received_date: Optional[str] = None,
        expiry_date: Optional[str] = None,
        storage_location: Optional[str] = None,
        reason: Optional[str] = None
    ) -> int:
        """
        Receives an inbound batch and atomically records a 'RECEIPT' entry
        in the immutable stock movement ledger.
        """
        if not batch_number or not batch_number.strip():
            raise InvalidMovementError("Batch number is required and cannot be empty.")

        batch_clean = batch_number.strip().upper()

        if int(quantity) <= 0:
            raise InvalidMovementError(f"Received quantity must be positive (> 0). Got: {quantity}")

        if float(unit_cost) < 0:
            raise InvalidMovementError(f"Unit cost cannot be negative. Got: {unit_cost}")

        if not received_date:
            received_date = date.today().strftime("%Y-%m-%d")

        sql_check = "SELECT batch_id FROM inventory_batches WHERE product_id = ? AND batch_number = ?"
        sql_batch = """
            INSERT INTO inventory_batches (
                product_id, batch_number, supplier_id, received_date,
                expiry_date, quantity_received, quantity_available, unit_cost, storage_location
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        sql_movement = """
            INSERT INTO stock_movements (
                product_id, batch_id, movement_type, quantity, unit_cost,
                total_cost_impact, reference_type, reference_id, reason, created_at
            ) VALUES (?, ?, 'RECEIPT', ?, ?, ?, 'PURCHASE_RECEIPT', ?, ?, ?)
        """

        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute(sql_check, (product_id, batch_clean))
            if cursor.fetchone():
                raise DuplicateBatchError(
                    f"Batch '{batch_clean}' already exists for this product. Use replenishment or choose a distinct batch number."
                )

            params_batch = (
                product_id,
                batch_clean,
                supplier_id,
                received_date,
                expiry_date,
                int(quantity),
                int(quantity),
                float(unit_cost),
                storage_location
            )
            try:
                cursor.execute(sql_batch, params_batch)
                batch_id = cursor.lastrowid
            except sqlite3.IntegrityError as err:
                if "UNIQUE constraint failed: inventory_batches.product_id, inventory_batches.batch_number" in str(err):
                    raise DuplicateBatchError(f"Batch '{batch_clean}' already exists for this product.")
                raise

            cost_impact = round(int(quantity) * float(unit_cost), 2)
            ledger_reason = reason or f"Inbound stock receipt for batch {batch_clean}"
            created_at = f"{received_date} {datetime.now().strftime('%H:%M:%S')}"

            cursor.execute(sql_movement, (
                product_id,
                batch_id,
                int(quantity),
                float(unit_cost),
                cost_impact,
                batch_clean,
                ledger_reason,
                created_at
            ))

            return batch_id

    @staticmethod
    def get_batches_for_product(product_id: int, available_only: bool = False) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            sql = """
                SELECT b.*, s.supplier_name,
                       CASE 
                           WHEN b.expiry_date IS NULL THEN NULL
                           ELSE CAST(JULIANDAY(b.expiry_date) - JULIANDAY('now') AS INTEGER)
                       END AS days_to_expiry
                FROM inventory_batches b
                LEFT JOIN suppliers s ON b.supplier_id = s.supplier_id
                WHERE b.product_id = ?
            """
            if available_only:
                sql += " AND b.quantity_available > 0 AND (b.expiry_date IS NULL OR b.expiry_date >= DATE('now'))"

            sql += " ORDER BY b.expiry_date ASC, b.received_date ASC"
            cursor.execute(sql, (product_id,))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def get_batch_by_id(batch_id: int) -> Optional[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM inventory_batches WHERE batch_id = ?", (batch_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def update_batch_quantity(
        batch_id: int,
        delta: int,
        reason: Optional[str] = None,
        movement_type: str = "MANUAL_COUNT_RECONCILIATION",
        allow_negative: bool = False,
        authorized_by: Optional[str] = None
    ) -> bool:
        """
        Adjusts available stock in a batch (positive to add, negative to deduct).
        Transactions are strictly logged into stock_movements — no silent balance edits allowed.
        """
        if delta == 0:
            return True

        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM inventory_batches WHERE batch_id = ?", (batch_id,))
            b_row = cursor.fetchone()
            if not b_row:
                raise ValueError(f"Batch ID {batch_id} does not exist.")

            curr_avail = b_row["quantity_available"]
            new_avail = curr_avail + delta

            if new_avail < 0:
                if not allow_negative:
                    raise InsufficientStockError(
                        f"Insufficient stock in batch '{b_row['batch_number']}': "
                        f"Currently {curr_avail} available, cannot deduct {abs(delta)}."
                    )
                if not authorized_by:
                    raise UnauthorizedNegativeStockError(
                        "Negative stock balance requires explicit manager authorization credentials."
                    )

            cursor.execute(
                "UPDATE inventory_batches SET quantity_available = ? WHERE batch_id = ?",
                (new_avail, batch_id)
            )

            # Record in movement ledger
            prod_id = b_row["product_id"]
            u_cost = float(b_row["unit_cost"])
            cost_impact = round(abs(delta) * u_cost, 2)
            audit_reason = reason or (
                f"Batch {b_row['batch_number']} balance adjusted by {delta}"
                + (f" (Auth: {authorized_by})" if authorized_by else "")
            )

            cursor.execute("""
                INSERT INTO stock_movements (
                    product_id, batch_id, movement_type, quantity, unit_cost,
                    total_cost_impact, reference_type, reference_id, reason
                ) VALUES (?, ?, ?, ?, ?, ?, 'STOCK_ADJUSTMENT', ?, ?)
            """, (
                prod_id,
                batch_id,
                movement_type if movement_type in VALID_MOVEMENT_TYPES else 'MANUAL_COUNT_RECONCILIATION',
                int(delta),
                u_cost,
                cost_impact,
                b_row["batch_number"],
                audit_reason
            ))

            return True

    @staticmethod
    def record_stock_movement(
        product_id: int,
        movement_type: str,
        quantity: int,
        reason: str,
        cost_impact: Optional[float] = None,
        batch_id: Optional[int] = None,
        reference_type: Optional[str] = None,
        reference_id: Optional[str] = None,
        movement_date: Optional[str] = None,
        allow_negative: bool = False,
        authorized_by: Optional[str] = None
    ) -> int:
        """
        Authoritative transaction engine for stock movements:
        - Validates arguments
        - Validates stock sufficiency and enforces non-negative policy
        - Updates batch balance(s)
        - Inserts an immutable entry in stock_movements
        - Inserts into stock_adjustments if an adjustment category
        """
        if quantity == 0:
            raise InvalidMovementError("Movement quantity cannot be zero.")

        if not reason or not reason.strip():
            raise InvalidMovementError("An explicit audit reason is strictly required for stock movements.")

        if movement_type not in VALID_MOVEMENT_TYPES:
            raise InvalidMovementError(
                f"Invalid movement type '{movement_type}'. Allowed types: {sorted(list(VALID_MOVEMENT_TYPES))}"
            )

        if not movement_date:
            movement_date = date.today().strftime("%Y-%m-%d")

        with db_session() as conn:
            cursor = conn.cursor()

            # Verify product exists
            cursor.execute("SELECT product_id, sku, product_name, cost_price FROM products WHERE product_id = ?", (product_id,))
            p_row = cursor.fetchone()
            if not p_row:
                raise ValueError(f"Product ID {product_id} not found.")

            default_cost = float(p_row["cost_price"])

            if batch_id:
                # Target specific batch
                cursor.execute("SELECT * FROM inventory_batches WHERE batch_id = ?", (batch_id,))
                b_row = cursor.fetchone()
                if not b_row:
                    raise ValueError(f"Batch ID {batch_id} not found.")

                batch_avail = b_row["quantity_available"]
                unit_cost = float(b_row["unit_cost"])

                if quantity < 0 and (batch_avail + quantity < 0):
                    if not allow_negative:
                        raise InsufficientStockError(
                            f"Cannot deduct {abs(quantity)} units from batch '{b_row['batch_number']}'. "
                            f"Available stock is only {batch_avail} units."
                        )
                    if not authorized_by:
                        raise UnauthorizedNegativeStockError(
                            "Negative stock deduction requires manager authorization."
                        )

                cursor.execute(
                    "UPDATE inventory_batches SET quantity_available = quantity_available + ? WHERE batch_id = ?",
                    (quantity, batch_id)
                )

                calculated_cost = cost_impact if cost_impact is not None else round(abs(quantity) * unit_cost, 2)

                cursor.execute("""
                    INSERT INTO stock_movements (
                        product_id, batch_id, movement_type, quantity, unit_cost,
                        total_cost_impact, reference_type, reference_id, reason, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    product_id,
                    batch_id,
                    movement_type,
                    int(quantity),
                    unit_cost,
                    calculated_cost,
                    reference_type or "STOCK_ADJUSTMENT",
                    reference_id or b_row["batch_number"],
                    reason.strip(),
                    f"{movement_date} {datetime.now().strftime('%H:%M:%S')}"
                ))
                movement_id = cursor.lastrowid

            else:
                # No specific batch specified
                unit_cost = default_cost
                calculated_cost = cost_impact if cost_impact is not None else round(abs(quantity) * unit_cost, 2)

                if quantity < 0:
                    # Deduction: FIFO batch allocation
                    needed = abs(quantity)
                    cursor.execute("""
                        SELECT * FROM inventory_batches 
                        WHERE product_id = ? AND quantity_available > 0
                        ORDER BY (expiry_date IS NULL), expiry_date ASC, received_date ASC
                    """, (product_id,))
                    avail_batches = cursor.fetchall()
                    total_available = sum(b["quantity_available"] for b in avail_batches)

                    if total_available < needed:
                        if not allow_negative:
                            raise InsufficientStockError(
                                f"Insufficient stock for product '{p_row['sku']}': "
                                f"Requested {needed} units, but total available stock across all batches is only {total_available} units."
                            )
                        if not authorized_by:
                            raise UnauthorizedNegativeStockError(
                                "Negative stock balance requires manager authorization."
                            )

                    # Deduct via FIFO
                    remaining = needed
                    target_b_id = None
                    for b in avail_batches:
                        if remaining <= 0:
                            break
                        deduct = min(remaining, b["quantity_available"])
                        cursor.execute(
                            "UPDATE inventory_batches SET quantity_available = quantity_available - ? WHERE batch_id = ?",
                            (deduct, b["batch_id"])
                        )
                        remaining -= deduct
                        target_b_id = b["batch_id"]

                    cursor.execute("""
                        INSERT INTO stock_movements (
                            product_id, batch_id, movement_type, quantity, unit_cost,
                            total_cost_impact, reference_type, reference_id, reason, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        product_id,
                        target_b_id,
                        movement_type,
                        int(quantity),
                        unit_cost,
                        calculated_cost,
                        reference_type or "STOCK_ADJUSTMENT",
                        reference_id,
                        reason.strip(),
                        f"{movement_date} {datetime.now().strftime('%H:%M:%S')}"
                    ))
                    movement_id = cursor.lastrowid

                else:
                    # Inward addition without batch_id: add to latest batch or create general batch
                    cursor.execute("""
                        SELECT batch_id FROM inventory_batches 
                        WHERE product_id = ? 
                        ORDER BY received_date DESC, batch_id DESC LIMIT 1
                    """, (product_id,))
                    latest_b = cursor.fetchone()

                    if latest_b:
                        target_b_id = latest_b["batch_id"]
                        cursor.execute(
                            "UPDATE inventory_batches SET quantity_available = quantity_available + ? WHERE batch_id = ?",
                            (quantity, target_b_id)
                        )
                    else:
                        # Create an auto-batch
                        auto_batch_no = f"AUTO-{p_row['sku']}-{datetime.now().strftime('%Y%m%d')}"
                        cursor.execute("""
                            INSERT INTO inventory_batches (
                                product_id, batch_number, received_date,
                                quantity_received, quantity_available, unit_cost, storage_location
                            ) VALUES (?, ?, ?, ?, ?, ?, 'Main Warehouse')
                        """, (product_id, auto_batch_no, movement_date, quantity, quantity, unit_cost))
                        target_b_id = cursor.lastrowid

                    cursor.execute("""
                        INSERT INTO stock_movements (
                            product_id, batch_id, movement_type, quantity, unit_cost,
                            total_cost_impact, reference_type, reference_id, reason, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        product_id,
                        target_b_id,
                        movement_type,
                        int(quantity),
                        unit_cost,
                        calculated_cost,
                        reference_type or "STOCK_ADJUSTMENT",
                        reference_id or "GENERAL-ADJUSTMENT",
                        reason.strip(),
                        f"{movement_date} {datetime.now().strftime('%H:%M:%S')}"
                    ))
                    movement_id = cursor.lastrowid

            # Also maintain backward compatibility for stock_adjustments table
            if movement_type in ('DAMAGE', 'EXPIRED', 'THEFT_SHRINKAGE', 'PROMOTIONAL_SAMPLE', 'MANUAL_COUNT_RECONCILIATION'):
                cursor.execute("""
                    INSERT INTO stock_adjustments (
                        product_id, batch_id, adjustment_type, quantity, reason, cost_impact, adjustment_date
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    product_id,
                    batch_id,
                    movement_type,
                    int(quantity),
                    reason.strip(),
                    calculated_cost,
                    movement_date
                ))

            return movement_id

    @staticmethod
    def get_stock_movements(
        product_id: Optional[int] = None,
        movement_type: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Retrieves auditable stock movement ledger entries with joined product and batch metadata.
        """
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            sql = """
                SELECT sm.*, p.product_name, p.sku, p.unit_of_measure,
                       b.batch_number
                FROM stock_movements sm
                JOIN products p ON sm.product_id = p.product_id
                LEFT JOIN inventory_batches b ON sm.batch_id = b.batch_id
                WHERE 1=1
            """
            params: List[Any] = []
            if product_id:
                sql += " AND sm.product_id = ?"
                params.append(product_id)
            if movement_type:
                sql += " AND sm.movement_type = ?"
                params.append(movement_type)
            if start_date:
                sql += " AND DATE(sm.created_at) >= ?"
                params.append(start_date)
            if end_date:
                sql += " AND DATE(sm.created_at) <= ?"
                params.append(end_date)

            sql += " ORDER BY sm.created_at DESC, sm.movement_id DESC LIMIT ?"
            params.append(limit)

            cursor.execute(sql, tuple(params))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def reconcile_product_stock(product_id: int) -> Dict[str, Any]:
        """
        Calculates and verifies stock balance consistency:
        - Ledger Stock: sum of signed quantities in stock_movements
        - Batch Stock: sum of quantity_available in inventory_batches
        Returns full reconciliation breakdown and discrepancy status.
        """
        conn = get_db_connection()
        try:
            cursor = conn.cursor()

            # Product info
            cursor.execute("SELECT product_id, sku, product_name, min_safety_stock FROM products WHERE product_id = ?", (product_id,))
            p_row = cursor.fetchone()
            if not p_row:
                raise ValueError(f"Product ID {product_id} not found.")

            # 1. Batch Stock
            cursor.execute("""
                SELECT COALESCE(SUM(quantity_available), 0) AS batch_stock,
                       COUNT(batch_id) AS batch_count
                FROM inventory_batches 
                WHERE product_id = ?
            """, (product_id,))
            b_data = cursor.fetchone()
            batch_stock = int(b_data["batch_stock"])
            batch_count = int(b_data["batch_count"])

            # 2. Ledger Stock
            cursor.execute("""
                SELECT COALESCE(SUM(quantity), 0) AS ledger_stock,
                       COUNT(movement_id) AS movement_count
                FROM stock_movements 
                WHERE product_id = ?
            """, (product_id,))
            m_data = cursor.fetchone()
            ledger_stock = int(m_data["ledger_stock"])
            movement_count = int(m_data["movement_count"])

            discrepancy = batch_stock - ledger_stock

            return {
                "product_id": product_id,
                "sku": p_row["sku"],
                "product_name": p_row["product_name"],
                "min_safety_stock": p_row["min_safety_stock"],
                "batch_stock": batch_stock,
                "ledger_stock": ledger_stock,
                "discrepancy": discrepancy,
                "is_reconciled": (discrepancy == 0),
                "batch_count": batch_count,
                "movement_count": movement_count
            }
        finally:
            conn.close()

    @staticmethod
    def perform_stock_reconciliation(
        product_id: int,
        physical_count: int,
        reason: str,
        authorized_by: str,
        batch_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Executes an authorized physical count reconciliation.
        Calculates variance delta, adjusts batch stock, and writes an auditable
        'MANUAL_COUNT_RECONCILIATION' entry in the movement ledger.
        """
        if physical_count < 0:
            raise InvalidMovementError("Physical count cannot be negative.")

        if not authorized_by or not authorized_by.strip():
            raise UnauthorizedNegativeStockError("Manager authorization name/ID is required for reconciliation.")

        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            if batch_id:
                cursor.execute("SELECT quantity_available FROM inventory_batches WHERE batch_id = ?", (batch_id,))
                b_row = cursor.fetchone()
                if not b_row:
                    raise ValueError(f"Batch ID {batch_id} not found.")
                current_stock = int(b_row["quantity_available"])
            else:
                cursor.execute("SELECT COALESCE(SUM(quantity_available), 0) AS stock FROM inventory_batches WHERE product_id = ?", (product_id,))
                current_stock = int(cursor.fetchone()["stock"])
        finally:
            conn.close()

        delta = physical_count - current_stock

        if delta != 0:
            InventoryRepository.record_stock_movement(
                product_id=product_id,
                movement_type="MANUAL_COUNT_RECONCILIATION",
                quantity=delta,
                reason=f"Stocktake count reconciliation: Observed {physical_count}, system had {current_stock}. {reason.strip()}",
                batch_id=batch_id,
                reference_type="RECONCILIATION",
                reference_id=f"RECON-{date.today().strftime('%Y%m%d')}",
                authorized_by=authorized_by.strip()
            )

        return InventoryRepository.reconcile_product_stock(product_id)

    @staticmethod
    def get_low_stock_products(category_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Retrieves products where stock is critical (0 < current_stock <= min_safety_stock).
        """
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            sql = """
                SELECT p.*, c.category_name,
                       COALESCE(SUM(b.quantity_available), 0) AS current_stock
                FROM products p
                JOIN product_categories c ON p.category_id = c.category_id
                LEFT JOIN inventory_batches b ON p.product_id = b.product_id 
                     AND (b.expiry_date IS NULL OR b.expiry_date >= DATE('now'))
                WHERE p.is_active = 1
            """
            params: List[Any] = []
            if category_id:
                sql += " AND p.category_id = ?"
                params.append(category_id)

            sql += """
                GROUP BY p.product_id
                HAVING current_stock > 0 AND current_stock <= p.min_safety_stock
                ORDER BY current_stock ASC
            """
            cursor.execute(sql, tuple(params))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def get_out_of_stock_products(category_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Retrieves products with 0 available stock.
        """
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            sql = """
                SELECT p.*, c.category_name,
                       COALESCE(SUM(b.quantity_available), 0) AS current_stock
                FROM products p
                JOIN product_categories c ON p.category_id = c.category_id
                LEFT JOIN inventory_batches b ON p.product_id = b.product_id 
                     AND (b.expiry_date IS NULL OR b.expiry_date >= DATE('now'))
                WHERE p.is_active = 1
            """
            params: List[Any] = []
            if category_id:
                sql += " AND p.category_id = ?"
                params.append(category_id)

            sql += """
                GROUP BY p.product_id
                HAVING current_stock = 0
                ORDER BY p.product_name ASC
            """
            cursor.execute(sql, tuple(params))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def get_expiring_batches(within_days: int = 15) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            sql = """
                SELECT b.*, p.product_name, p.sku, p.unit_of_measure,
                       CAST(JULIANDAY(b.expiry_date) - JULIANDAY('now') AS INTEGER) AS days_to_expiry
                FROM inventory_batches b
                JOIN products p ON b.product_id = p.product_id
                WHERE b.expiry_date IS NOT NULL 
                  AND b.quantity_available > 0
                  AND b.expiry_date <= DATE('now', '+' || ? || ' days')
                ORDER BY b.expiry_date ASC
            """
            cursor.execute(sql, (within_days,))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def get_inventory_valuation() -> Dict[str, Any]:
        """
        Calculates complete inventory valuation metrics along with health counts.
        """
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            sql_val = """
                SELECT 
                    COALESCE(SUM(b.quantity_available * b.unit_cost), 0) AS total_cost_value,
                    COALESCE(SUM(b.quantity_available * p.selling_price), 0) AS total_retail_value,
                    COALESCE(SUM(b.quantity_available), 0) AS total_units_in_stock
                FROM inventory_batches b
                JOIN products p ON b.product_id = p.product_id
                WHERE b.quantity_available > 0
                  AND (b.expiry_date IS NULL OR b.expiry_date >= DATE('now'))
            """
            cursor.execute(sql_val)
            row = cursor.fetchone()
            c_val = float(row["total_cost_value"]) if row else 0.0
            r_val = float(row["total_retail_value"]) if row else 0.0
            u_stock = int(row["total_units_in_stock"]) if row else 0

            # Count out of stock and low stock
            cursor.execute("""
                SELECT 
                    COUNT(CASE WHEN stock = 0 THEN 1 END) AS out_of_stock_count,
                    COUNT(CASE WHEN stock > 0 AND stock <= min_safety_stock THEN 1 END) AS low_stock_count,
                    COUNT(product_id) AS total_products
                FROM (
                    SELECT p.product_id, p.min_safety_stock,
                           COALESCE(SUM(b.quantity_available), 0) AS stock
                    FROM products p
                    LEFT JOIN inventory_batches b ON p.product_id = b.product_id
                         AND (b.expiry_date IS NULL OR b.expiry_date >= DATE('now'))
                    WHERE p.is_active = 1
                    GROUP BY p.product_id
                )
            """)
            health = cursor.fetchone()

            return {
                "total_cost_value": c_val,
                "total_retail_value": r_val,
                "potential_margin": round(r_val - c_val, 2),
                "total_units_in_stock": u_stock,
                "out_of_stock_count": int(health["out_of_stock_count"]) if health else 0,
                "low_stock_count": int(health["low_stock_count"]) if health else 0,
                "total_products": int(health["total_products"]) if health else 0
            }
        finally:
            conn.close()
