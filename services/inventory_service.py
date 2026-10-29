"""
FestivePulse — Inventory & Stock Management Service
Encapsulates business operations for catalog management, inbound batch receipts,
auditable stock adjustments, deterministic inventory reconciliation, and stock valuation.
"""

from typing import Dict, Any, Optional, List
import pandas as pd
from repositories.inventory_repository import InventoryRepository
from repositories.product_repository import ProductRepository
from database.connection import query_df


def add_product(data: Dict[str, Any]) -> int:
    """
    Adds a new product to the catalog with business validation and optional opening stock.
    Delegates to ProductRepository for consistent constraint enforcement.
    """
    initial_stock = int(data.get("initial_stock", 0))
    initial_location = data.get("initial_storage_location", "Main Store")
    supplier_id = int(data["supplier_id"]) if data.get("supplier_id") else None

    return ProductRepository.create_product(
        data=data,
        initial_stock=initial_stock,
        initial_storage_location=initial_location,
        supplier_id=supplier_id
    )


def update_product(product_id: int, data: Dict[str, Any]) -> bool:
    """
    Updates product specifications with price hierarchy and category validation.
    """
    return ProductRepository.update_product(product_id, data)


def receive_batch(
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
    Receives incoming stock batch into the warehouse.
    Atomically updates batch balances and logs a 'RECEIPT' in the movement ledger.
    """
    return InventoryRepository.create_batch(
        product_id=product_id,
        batch_number=batch_number,
        quantity=quantity,
        unit_cost=unit_cost,
        supplier_id=supplier_id,
        received_date=received_date,
        expiry_date=expiry_date,
        storage_location=storage_location,
        reason=reason
    )


def record_stock_adjustment(
    product_id: int,
    adjustment_type: str,
    quantity: int,
    reason: str,
    batch_id: Optional[int] = None,
    movement_date: Optional[str] = None,
    allow_negative: bool = False,
    authorized_by: Optional[str] = None
) -> int:
    """
    Records shrinkage, breakage, expired mithai, promotional samples, or count discrepancies.
    Atomically adjusts batch stock and records entries in stock_adjustments and stock_movements.
    """
    return InventoryRepository.record_stock_movement(
        product_id=product_id,
        movement_type=adjustment_type,
        quantity=quantity,
        reason=reason,
        batch_id=batch_id,
        movement_date=movement_date,
        allow_negative=allow_negative,
        authorized_by=authorized_by
    )


def get_inventory_valuation_metrics() -> Dict[str, Any]:
    """
    Calculates total stock on hand value at Cost Price, Selling Price, and health metrics.
    """
    return InventoryRepository.get_inventory_valuation()


def reconcile_product_inventory(product_id: int) -> Dict[str, Any]:
    """
    Verifies that sum of recorded movements matches current batch balance for a product.
    """
    return InventoryRepository.reconcile_product_stock(product_id)


def reconcile_all_inventory() -> List[Dict[str, Any]]:
    """
    Runs reconciliation across all active products in the store catalog.
    """
    active_prods = ProductRepository.get_all_products(include_inactive=False)
    results = []
    for p in active_prods:
        recon = InventoryRepository.reconcile_product_stock(p["product_id"])
        results.append(recon)
    return results


def perform_physical_count_reconciliation(
    product_id: int,
    physical_count: int,
    reason: str,
    authorized_by: str,
    batch_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Applies an authorized physical count adjustment to bring ledger and balances into sync.
    """
    return InventoryRepository.perform_stock_reconciliation(
        product_id=product_id,
        physical_count=physical_count,
        reason=reason,
        authorized_by=authorized_by,
        batch_id=batch_id
    )


def get_stock_movement_ledger(
    product_id: Optional[int] = None,
    movement_type: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 100
) -> pd.DataFrame:
    """
    Returns an auditable stock movement ledger as a pandas DataFrame for reporting and display.
    """
    movements = InventoryRepository.get_stock_movements(
        product_id=product_id,
        movement_type=movement_type,
        start_date=start_date,
        end_date=end_date,
        limit=limit
    )
    if not movements:
        return pd.DataFrame(columns=[
            "movement_id", "product_id", "product_name", "sku", "unit_of_measure",
            "batch_number", "movement_type", "quantity", "unit_cost", "total_cost_impact",
            "reference_type", "reference_id", "reason", "created_at"
        ])
    return pd.DataFrame(movements)


def get_low_stock_items(category_id: Optional[int] = None) -> pd.DataFrame:
    """
    Returns products below safety stock levels (critical stock).
    """
    items = InventoryRepository.get_low_stock_products(category_id=category_id)
    return pd.DataFrame(items) if items else pd.DataFrame()


def get_out_of_stock_items(category_id: Optional[int] = None) -> pd.DataFrame:
    """
    Returns products with zero stock on hand.
    """
    items = InventoryRepository.get_out_of_stock_products(category_id=category_id)
    return pd.DataFrame(items) if items else pd.DataFrame()
