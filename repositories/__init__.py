"""
FestivePulse — Repositories Package
Provides parameterized SQL repository abstractions for data persistence.
"""

from repositories.settings_repository import SettingsRepository
from repositories.festival_repository import FestivalRepository
from repositories.product_repository import ProductRepository
from repositories.inventory_repository import (
    InventoryRepository,
    InsufficientStockError,
    DuplicateBatchError,
    InvalidMovementError,
    UnauthorizedNegativeStockError
)
from repositories.sales_repository import (
    SalesRepository,
    DuplicateTransactionError,
    InvalidSaleError,
    InvalidReturnError,
    CustomerCreditLimitExceededError
)
from repositories.expense_repository import ExpenseRepository

__all__ = [
    "SettingsRepository",
    "FestivalRepository",
    "ProductRepository",
    "InventoryRepository",
    "SalesRepository",
    "ExpenseRepository",
    "InsufficientStockError",
    "DuplicateBatchError",
    "InvalidMovementError",
    "UnauthorizedNegativeStockError",
    "DuplicateTransactionError",
    "InvalidSaleError",
    "InvalidReturnError",
    "CustomerCreditLimitExceededError",
]
