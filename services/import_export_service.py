"""
FestivePulse — Reliable CSV Import & Export Service
Enterprise-grade data ingestion and export with downloadable templates,
comprehensive required-column documentation, strict date and numeric validation,
duplicate detection, preview staging, atomic rollback and safe row-level reporting.

INVARIANTS:
1. Never silently discard invalid rows or duplicate sales.
2. Inbound stock batches must never bypass the stock movement ledger (always record RECEIPT).
3. Full UTF-8 compatibility (with BOM for Excel) across Indian Rupee (₹) and regional scripts.
"""

import io
import csv
import json
import re
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from typing import Dict, Any, List, Optional, Tuple, Set, Union
import pandas as pd

from database.connection import get_db_connection, db_session, query_df
from config import GST_SLABS, UNITS_OF_MEASURE, EXPENSE_CATEGORIES
from repositories.product_repository import ProductRepository, DuplicateSkuError, ProductValidationError
from repositories.sales_repository import SalesRepository, DuplicateTransactionError, InsufficientStockError, InvalidSaleError
from repositories.inventory_repository import InventoryRepository, DuplicateBatchError, InvalidMovementError
from services.expense_service import record_expense, normalize_category
from services.security_service import sanitize_df_for_csv, DEFAULT_MAX_UPLOAD_SIZE_BYTES


# ==============================================================================
# 1. ENTITY SCHEMAS, TEMPLATES & DOCUMENTATION
# ==============================================================================

SCHEMAS: Dict[str, Dict[str, Any]] = {
    "products": {
        "title": "Products Catalog",
        "required_columns": ["sku", "product_name", "category", "unit_of_measure", "cost_price", "selling_price", "gst_rate"],
        "column_aliases": {
            "product_sku": "sku",
            "item_name": "product_name",
            "name": "product_name",
            "category_name": "category",
            "category_id": "category",
            "uom": "unit_of_measure",
            "unit": "unit_of_measure",
            "cost": "cost_price",
            "purchase_price": "cost_price",
            "price": "selling_price",
            "sale_price": "selling_price",
            "gst": "gst_rate",
            "tax_rate": "gst_rate"
        },
        "columns_doc": [
            {"name": "sku", "required": True, "type": "Text (Unique)", "format": "Alphanumeric (e.g. SKU-SWT-001)", "description": "Unique product stock keeping unit. Duplicates are rejected."},
            {"name": "product_name", "required": True, "type": "Text", "format": "Clean product name", "description": "Display name of the product."},
            {"name": "category", "required": True, "type": "Text or Integer", "format": "Category Name or ID", "description": "Existing category (e.g. 'Sweets / Mithai', 'Decorations', or category ID)."},
            {"name": "unit_of_measure", "required": True, "type": "Text", "format": "pcs, kg, grams, box, pack, meter, set, kit", "description": "Standard retail unit of measurement."},
            {"name": "cost_price", "required": True, "type": "Number", "format": ">= 0.00", "description": "Default purchase/manufacturing unit cost in ₹."},
            {"name": "selling_price", "required": True, "type": "Number", "format": ">= cost_price", "description": "Standard counter selling price in ₹."},
            {"name": "gst_rate", "required": True, "type": "Number", "format": "0.0, 5.0, 12.0, 18.0, 28.0", "description": "Standard Indian GST tax percentage slab."},
            {"name": "mrp", "required": False, "type": "Number", "format": ">= selling_price", "description": "Maximum Retail Price printed on packaging."},
            {"name": "barcode", "required": False, "type": "Text (Unique)", "format": "EAN-13 / UPC / Custom", "description": "Optional barcode for scanner lookup."},
            {"name": "hsn_code", "required": False, "type": "Text", "format": "4 to 8 digit HSN/SAC code", "description": "Harmonized System of Nomenclature code for GST billing."},
            {"name": "min_safety_stock", "required": False, "type": "Integer", "format": ">= 0 (Default: 10)", "description": "Threshold below which low-stock alert triggers."},
            {"name": "reorder_quantity", "required": False, "type": "Integer", "format": "> 0 (Default: 50)", "description": "Standard purchase replenishment batch size."},
            {"name": "is_perishable", "required": False, "type": "Integer", "format": "0 (No) or 1 (Yes)", "description": "Indicates perishable festive sweets/dairy."},
            {"name": "shelf_life_days", "required": False, "type": "Integer", "format": "> 0 if perishable", "description": "Shelf life in days before expiry."},
            {"name": "festival_tags", "required": False, "type": "Text", "format": "Comma-separated codes (e.g. DIWALI,PONGAL)", "description": "Tags linking item to festive campaigns."}
        ],
        "sample_rows": [
            {
                "sku": "SKU-MITH-001",
                "product_name": "Kaju Katli Gift Box 500g",
                "category": "Sweets / Mithai",
                "unit_of_measure": "box",
                "cost_price": 280.0,
                "selling_price": 450.0,
                "mrp": 500.0,
                "gst_rate": 5.0,
                "barcode": "890100100101",
                "hsn_code": "21069099",
                "min_safety_stock": 25,
                "reorder_quantity": 100,
                "is_perishable": 1,
                "shelf_life_days": 10,
                "festival_tags": "DIWALI,RAKHI,NEW_YEAR"
            },
            {
                "sku": "SKU-DIY-002",
                "product_name": "Terracotta Handpainted Diya (Set of 6)",
                "category": "Decorations & Diyas",
                "unit_of_measure": "set",
                "cost_price": 40.0,
                "selling_price": 99.0,
                "mrp": 120.0,
                "gst_rate": 12.0,
                "barcode": "890100100102",
                "hsn_code": "69139000",
                "min_safety_stock": 50,
                "reorder_quantity": 200,
                "is_perishable": 0,
                "shelf_life_days": "",
                "festival_tags": "DIWALI,GANESH_CHATURTHI"
            }
        ]
    },
    "sales": {
        "title": "Sales & Invoices",
        "required_columns": ["invoice_date", "sku", "quantity", "selling_price"],
        "column_aliases": {
            "bill_date": "invoice_date",
            "date": "invoice_date",
            "product_sku": "sku",
            "qty": "quantity",
            "unit_price": "selling_price",
            "rate": "selling_price",
            "bill_no": "invoice_number",
            "inv_no": "invoice_number",
            "discount": "discount_pct",
            "discount_percent": "discount_pct",
            "phone": "customer_phone",
            "mobile": "customer_phone",
            "customer": "customer_name",
            "festival": "festival_reference"
        },
        "columns_doc": [
            {"name": "invoice_date", "required": True, "type": "Date", "format": "YYYY-MM-DD", "description": "Date of transaction. Must be valid calendar date."},
            {"name": "sku", "required": True, "type": "Text", "format": "Existing SKU", "description": "Must match a product already in the catalog."},
            {"name": "quantity", "required": True, "type": "Integer", "format": "> 0", "description": "Units sold. Must not exceed available unexpired inventory."},
            {"name": "selling_price", "required": True, "type": "Number", "format": "> 0.00", "description": "Actual transaction unit price billed to customer."},
            {"name": "invoice_number", "required": False, "type": "Text (Unique)", "format": "INV-YYYY-XXXX", "description": "Custom invoice number. If empty, auto-generated sequentially."},
            {"name": "discount_pct", "required": False, "type": "Number", "format": "0.0 to 100.0", "description": "Line-level discount percentage."},
            {"name": "overall_discount", "required": False, "type": "Number", "format": ">= 0.00", "description": "Invoice-level fixed discount in ₹."},
            {"name": "payment_mode", "required": False, "type": "Text", "format": "UPI, CASH, CARD, CREDIT_KHATA, SPLIT", "description": "Payment tender (Default: CASH)."},
            {"name": "customer_phone", "required": False, "type": "Text", "format": "10-digit mobile number", "description": "Associated customer phone for credit or loyalty."},
            {"name": "customer_name", "required": False, "type": "Text", "format": "Customer Full Name", "description": "Customer name if phone is provided."},
            {"name": "festival_reference", "required": False, "type": "Text or Integer", "format": "Occurrence ID or Festival Code", "description": "Optional festival campaign linkage."},
            {"name": "transaction_reference", "required": False, "type": "Text (Unique)", "format": "UPI Ref / Bank UTR / Card Auth", "description": "Electronic transaction reference. Duplicates rejected."},
            {"name": "notes", "required": False, "type": "Text", "format": "Free text", "description": "Optional counter bill notes."}
        ],
        "sample_rows": [
            {
                "invoice_number": "INV-2026-9001",
                "invoice_date": "2026-10-18",
                "sku": "SKU-MITH-001",
                "quantity": 5,
                "selling_price": 450.0,
                "discount_pct": 5.0,
                "overall_discount": 0.0,
                "payment_mode": "UPI",
                "customer_phone": "9876543210",
                "customer_name": "Ramesh Kumar",
                "festival_reference": "DIWALI_2026",
                "transaction_reference": "UPI-TXN-984729104",
                "notes": "Festival gift purchase"
            }
        ]
    },
    "expenses": {
        "title": "Expenses & Overheads",
        "required_columns": ["expense_date", "category", "amount", "description"],
        "column_aliases": {
            "date": "expense_date",
            "expense_category": "category",
            "cost": "amount",
            "amt": "amount",
            "desc": "description",
            "purpose": "description",
            "receipt_no": "invoice_receipt_no",
            "receipt": "invoice_receipt_no",
            "voucher": "invoice_receipt_no",
            "vendor": "vendor_name",
            "festival": "festival_reference"
        },
        "columns_doc": [
            {"name": "expense_date", "required": True, "type": "Date", "format": "YYYY-MM-DD", "description": "Date expense was incurred."},
            {"name": "category", "required": True, "type": "Text", "format": "RENT, TRANSPORT, PACKAGING, WAGES, MARKETING, OTHER", "description": "Standard business expense classification."},
            {"name": "amount", "required": True, "type": "Number", "format": "> 0.00", "description": "Total expense amount paid or payable in ₹."},
            {"name": "description", "required": True, "type": "Text", "format": "Itemized purpose", "description": "Clear explanation of expenditure for audit trail."},
            {"name": "festival_reference", "required": False, "type": "Text or Integer", "format": "Occurrence ID or Festival Code", "description": "Optional festival campaign to tag."},
            {"name": "payment_mode", "required": False, "type": "Text", "format": "CASH, UPI, BANK_TRANSFER, CARD, OTHER", "description": "Tender used (Default: CASH)."},
            {"name": "vendor_name", "required": False, "type": "Text", "format": "Supplier / Contractor Name", "description": "Name of party paid."},
            {"name": "invoice_receipt_no", "required": False, "type": "Text (Unique)", "format": "Voucher / Bill No", "description": "Vendor receipt reference for auditing."}
        ],
        "sample_rows": [
            {
                "expense_date": "2026-10-15",
                "category": "PACKAGING",
                "amount": 7500.0,
                "description": "500 Embossed Sweet Gift Boxes",
                "festival_reference": "DIWALI_2026",
                "payment_mode": "BANK_TRANSFER",
                "vendor_name": "Sri Balaji Packaging",
                "invoice_receipt_no": "REC-PKG-2026-081"
            },
            {
                "expense_date": "2026-10-16",
                "category": "MARKETING",
                "amount": 12000.0,
                "description": "Street banners and newspaper flyer inserts",
                "festival_reference": "DIWALI_2026",
                "payment_mode": "UPI",
                "vendor_name": "City Outdoor Media",
                "invoice_receipt_no": "INV-MKT-991"
            }
        ]
    },
    "stock": {
        "title": "Stock Inward Batches",
        "required_columns": ["sku", "batch_number", "quantity", "unit_cost", "received_date"],
        "column_aliases": {
            "product_sku": "sku",
            "batch": "batch_number",
            "batch_no": "batch_number",
            "lot_number": "batch_number",
            "qty": "quantity",
            "cost": "unit_cost",
            "cost_price": "unit_cost",
            "date": "received_date",
            "inward_date": "received_date",
            "expiry": "expiry_date",
            "supplier": "supplier_name",
            "location": "storage_location"
        },
        "columns_doc": [
            {"name": "sku", "required": True, "type": "Text", "format": "Existing SKU", "description": "Catalog SKU for the incoming stock batch."},
            {"name": "batch_number", "required": True, "type": "Text (Unique per SKU)", "format": "Alphanumeric Batch Code", "description": "Manufacturing batch or supplier lot number."},
            {"name": "quantity", "required": True, "type": "Integer", "format": "> 0", "description": "Number of units received into warehouse."},
            {"name": "unit_cost", "required": True, "type": "Number", "format": ">= 0.00", "description": "Purchase cost per unit for this specific batch."},
            {"name": "received_date", "required": True, "type": "Date", "format": "YYYY-MM-DD", "description": "Date physical shipment was received."},
            {"name": "expiry_date", "required": False, "type": "Date", "format": "YYYY-MM-DD (>= received_date)", "description": "Expiry date. Mandatory for perishable items."},
            {"name": "supplier_name", "required": False, "type": "Text", "format": "Supplier Company Name", "description": "Name of vendor delivering the goods."},
            {"name": "storage_location", "required": False, "type": "Text", "format": "Shelf / Bin / Store Name", "description": "Warehouse location (Default: 'Main Store')."},
            {"name": "purchase_invoice_no", "required": False, "type": "Text", "format": "Vendor Bill Number", "description": "Inbound purchase invoice reference."},
            {"name": "reason", "required": False, "type": "Text", "format": "Free text", "description": "Auditable receipt reason (Default: 'Bulk Stock Inward Import')."}
        ],
        "sample_rows": [
            {
                "sku": "SKU-MITH-001",
                "batch_number": "BAT-2026-KJ-01",
                "quantity": 200,
                "unit_cost": 275.0,
                "received_date": "2026-10-15",
                "expiry_date": "2026-10-25",
                "supplier_name": "Royal Confectioners Pvt Ltd",
                "storage_location": "Refrigerated Bay A",
                "purchase_invoice_no": "RC-BILL-4019",
                "reason": "Diwali Festival Pre-stocking"
            }
        ]
    }
}


def get_template_csv(entity: str) -> str:
    """Generates standard downloadable CSV template with UTF-8 BOM."""
    if entity not in SCHEMAS:
        raise ValueError(f"Unknown entity '{entity}'. Allowed: {list(SCHEMAS.keys())}")
    
    schema = SCHEMAS[entity]
    sample_rows = schema["sample_rows"]
    df = pd.DataFrame(sample_rows)
    # Output UTF-8 with BOM for Excel compatibility
    return df.to_csv(index=False)


def get_column_documentation(entity: str) -> List[Dict[str, Any]]:
    """Returns documentation specifications for UI display."""
    if entity not in SCHEMAS:
        return []
    return SCHEMAS[entity]["columns_doc"]


# ==============================================================================
# 2. ROBUST CSV PARSING & SANITIZATION
# ==============================================================================

def parse_csv_file(file_or_content: Union[str, bytes, io.IOBase, Any]) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    """
    Parses CSV content from file path, raw bytes, string, or file-like object.
    Supports UTF-8, UTF-8-SIG (BOM), and Latin-1.
    Gracefully handles empty files and malformed syntax.
    """
    try:
        if isinstance(file_or_content, bytes):
            if not file_or_content.strip():
                return None, "Uploaded CSV file is completely empty or contains no data rows."
            if len(file_or_content) > DEFAULT_MAX_UPLOAD_SIZE_BYTES:
                mb = len(file_or_content) / (1024 * 1024)
                return None, f"File size ({mb:.2f} MB) exceeds maximum allowed limit (10 MB)."
            if b"\0" in file_or_content:
                return None, "Malformed CSV file rejected: Contains null bytes."
            buffer = io.BytesIO(file_or_content)
        elif isinstance(file_or_content, str):
            clean_str = file_or_content.strip()
            if not clean_str:
                return None, "Uploaded CSV file is completely empty or contains no data rows."
            if len(clean_str.encode("utf-8")) > DEFAULT_MAX_UPLOAD_SIZE_BYTES:
                mb = len(clean_str.encode("utf-8")) / (1024 * 1024)
                return None, f"File size ({mb:.2f} MB) exceeds maximum allowed limit (10 MB)."
            if "\0" in clean_str:
                return None, "Malformed CSV file rejected: Contains null bytes."
            # Could be a filepath or CSV text
            if "\n" in file_or_content or "," in file_or_content:
                buffer = io.StringIO(file_or_content)
            else:
                p = Path(file_or_content)
                if not p.exists() or p.is_dir():
                    return None, f"File not found or empty path: {file_or_content}"
                with open(p, "rb") as f:
                    content_bytes = f.read()
                    if not content_bytes.strip():
                        return None, "Uploaded CSV file is completely empty or contains no data rows."
                    buffer = io.BytesIO(content_bytes)
        elif hasattr(file_or_content, "read"):
            content = file_or_content.read()
            if not content:
                return None, "Uploaded CSV file is completely empty or contains no data rows."
            if isinstance(content, str):
                if not content.strip():
                    return None, "Uploaded CSV file is completely empty or contains no data rows."
                buffer = io.StringIO(content)
            else:
                if not content.strip():
                    return None, "Uploaded CSV file is completely empty or contains no data rows."
                buffer = io.BytesIO(content)
        else:
            return None, "Unsupported file format or empty input."

        # Attempt to read CSV with pandas
        try:
            df = pd.read_csv(buffer, dtype=str, skipinitialspace=True)
        except UnicodeDecodeError:
            buffer.seek(0)
            df = pd.read_csv(buffer, dtype=str, encoding="latin-1", skipinitialspace=True)

        if df.empty or len(df.columns) == 0:
            return None, "Uploaded CSV file is completely empty or contains no data rows."

        # Normalize column headers (strip whitespace, lower, and apply canonical aliases)
        df.columns = [str(c).strip().lower() for c in df.columns]
        return df, None

    except pd.errors.EmptyDataError:
        return None, "The uploaded file is empty."
    except pd.errors.ParserError as pe:
        return None, f"Malformed CSV syntax: {str(pe)}"
    except Exception as e:
        return None, f"Failed to read CSV: {str(e)}"


def standardize_columns(df: pd.DataFrame, entity: str) -> pd.DataFrame:
    """Maps vendor/user column aliases to canonical internal column names."""
    if entity not in SCHEMAS:
        return df
    
    aliases = SCHEMAS[entity].get("column_aliases", {})
    new_cols = []
    for c in df.columns:
        norm_c = c.strip().lower()
        new_cols.append(aliases.get(norm_c, norm_c))
    df.columns = new_cols
    return df


def validate_csv_headers(df: pd.DataFrame, entity: str) -> Tuple[bool, List[str]]:
    """Validates that all required columns are present in the dataframe headers."""
    if entity not in SCHEMAS:
        return False, [f"Unknown entity: {entity}"]
    
    required = SCHEMAS[entity]["required_columns"]
    missing = [c for c in required if c not in df.columns]
    return len(missing) == 0, missing


# ==============================================================================
# 3. DATE & VALUE VALIDATORS
# ==============================================================================

DATE_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}$")

def validate_date_str(val: Any) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Validates date string format YYYY-MM-DD and ensures valid calendar day (e.g. no 2026-02-31).
    """
    if val is None or pd.isna(val) or str(val).strip() == "":
        return False, None, "Date is required and cannot be blank."
    
    clean_str = str(val).strip()
    if not DATE_REGEX.match(clean_str):
        return False, None, f"Invalid date format '{clean_str}'. Must be YYYY-MM-DD (e.g. 2026-10-18)."
    
    try:
        parsed = datetime.strptime(clean_str, "%Y-%m-%d").date()
        # Ensure year is reasonable (between 2000 and 2099)
        if parsed.year < 2000 or parsed.year > 2099:
            return False, None, f"Year {parsed.year} out of reasonable business bounds (2000-2099)."
        return True, parsed.strftime("%Y-%m-%d"), None
    except ValueError as ve:
        return False, None, f"Invalid calendar date '{clean_str}': {str(ve)}"


def parse_float(val: Any, default: Optional[float] = None) -> Tuple[bool, Optional[float]]:
    """Safely parses float number."""
    if val is None or pd.isna(val) or str(val).strip() == "":
        return default is not None, default
    try:
        # Strip rupee symbol and commas if user put ₹ or 1,500.00
        clean_str = str(val).replace("₹", "").replace(",", "").strip()
        f_val = float(clean_str)
        return True, f_val
    except (ValueError, TypeError):
        return False, None


def parse_int(val: Any, default: Optional[int] = None) -> Tuple[bool, Optional[int]]:
    """Safely parses integer."""
    if val is None or pd.isna(val) or str(val).strip() == "":
        return default is not None, default
    try:
        clean_str = str(val).replace(",", "").strip()
        # Handle float strings like '10.0'
        i_val = int(float(clean_str))
        return True, i_val
    except (ValueError, TypeError):
        return False, None


# ==============================================================================
# 4. ROW-LEVEL VALIDATION BY ENTITY
# ==============================================================================

def validate_product_row(
    row: Dict[str, Any],
    row_idx: int,
    seen_skus: Set[str],
    seen_barcodes: Set[str],
    db_skus: Set[str],
    db_barcodes: Set[str],
    category_map: Dict[str, int]
) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """Validates single product row against all business rules and duplicate invariants."""
    sku = str(row.get("sku", "")).strip().upper()
    if not sku:
        return False, None, "SKU is required."
    
    # In-file duplicate check
    if sku in seen_skus:
        return False, None, f"Duplicate SKU '{sku}' found within uploaded CSV (Row {row_idx + 1})."
    
    # DB duplicate check
    if sku in db_skus:
        return False, None, f"SKU '{sku}' already exists in database catalog."

    p_name = str(row.get("product_name", "")).strip()
    if not p_name:
        return False, None, "Product name is required."

    # Category validation
    cat_raw = str(row.get("category", "")).strip()
    category_id = None
    if cat_raw.isdigit():
        c_int = int(cat_raw)
        if c_int in category_map.values():
            category_id = c_int
    else:
        # Match by name (case-insensitive)
        for name, cid in category_map.items():
            if name.lower() == cat_raw.lower():
                category_id = cid
                break
    
    if not category_id:
        return False, None, f"Category '{cat_raw}' does not exist. Must match an existing category in the system."

    # Unit of measure
    uom = str(row.get("unit_of_measure", "pcs")).strip().lower()
    if uom not in UNITS_OF_MEASURE:
        return False, None, f"Invalid unit of measure '{uom}'. Allowed: {', '.join(UNITS_OF_MEASURE)}."

    # Prices
    ok_cost, cost_price = parse_float(row.get("cost_price"))
    if not ok_cost or cost_price is None or cost_price < 0:
        return False, None, f"Cost price must be a non-negative number. Got: '{row.get('cost_price')}'."

    ok_sell, selling_price = parse_float(row.get("selling_price"))
    if not ok_sell or selling_price is None or selling_price < 0:
        return False, None, f"Selling price must be a non-negative number. Got: '{row.get('selling_price')}'."

    if selling_price < cost_price:
        return False, None, f"Selling price (₹{selling_price:.2f}) cannot be less than purchase cost (₹{cost_price:.2f})."

    # MRP
    ok_mrp, mrp = parse_float(row.get("mrp"), default=selling_price)
    if not ok_mrp or mrp is None:
        return False, None, f"Invalid MRP value: '{row.get('mrp')}'."
    if mrp < selling_price:
        return False, None, f"MRP (₹{mrp:.2f}) cannot be less than selling price (₹{selling_price:.2f})."

    # GST Rate
    ok_gst, gst_rate = parse_float(row.get("gst_rate"))
    if not ok_gst or gst_rate not in GST_SLABS:
        return False, None, f"Invalid GST rate: '{row.get('gst_rate')}'. Allowed Indian GST slabs: {GST_SLABS}."

    # Barcode
    barcode = str(row.get("barcode", "")).strip() or None
    if barcode:
        if barcode in seen_barcodes:
            return False, None, f"Duplicate barcode '{barcode}' found within uploaded CSV."
        if barcode in db_barcodes:
            return False, None, f"Barcode '{barcode}' already exists in database catalog."

    # Safety Stock & Reorder Qty
    ok_ss, safety_stock = parse_int(row.get("min_safety_stock"), default=10)
    if not ok_ss or safety_stock is None or safety_stock < 0:
        return False, None, "Min safety stock cannot be negative."

    ok_roq, reorder_qty = parse_int(row.get("reorder_quantity"), default=50)
    if not ok_roq or reorder_qty is None or reorder_qty <= 0:
        return False, None, "Reorder quantity must be greater than zero."

    # Perishable
    ok_perish, is_perishable = parse_int(row.get("is_perishable"), default=0)
    shelf_life = None
    if is_perishable == 1:
        ok_sl, shelf_life = parse_int(row.get("shelf_life_days"))
        if not ok_sl or shelf_life is None or shelf_life <= 0:
            return False, None, "Perishable products must specify shelf_life_days > 0."

    # Tags
    raw_tags = str(row.get("festival_tags", "")).split(",")
    cleaned_tags = [t.strip().upper() for t in raw_tags if t.strip()]

    parsed_row = {
        "sku": sku,
        "product_name": p_name,
        "category_id": category_id,
        "unit_of_measure": uom,
        "cost_price": cost_price,
        "selling_price": selling_price,
        "mrp": mrp,
        "gst_rate": gst_rate,
        "barcode": barcode,
        "hsn_code": str(row.get("hsn_code", "")).strip() or None,
        "min_safety_stock": safety_stock,
        "reorder_quantity": reorder_qty,
        "is_perishable": is_perishable,
        "shelf_life_days": shelf_life,
        "festival_tags": cleaned_tags
    }
    return True, parsed_row, None


def validate_sale_row(
    row: Dict[str, Any],
    row_idx: int,
    seen_invoices: Set[str],
    seen_txn_refs: Set[str],
    db_invoices: Set[str],
    db_txn_refs: Set[str],
    db_products_map: Dict[str, Dict[str, Any]],  # sku -> {product_id, selling_price, name, avail_stock}
    db_festivals_map: Dict[str, int]
) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """Validates single sale row with stock check, duplicate detection, and pricing rules."""
    # Invoice Date
    ok_date, inv_date, err_date = validate_date_str(row.get("invoice_date"))
    if not ok_date:
        return False, None, f"Date Error: {err_date}"

    # Invoice Number
    inv_num = str(row.get("invoice_number", "")).strip().upper() or None
    if inv_num:
        if inv_num in seen_invoices:
            return False, None, f"Duplicate invoice_number '{inv_num}' in uploaded CSV (Row {row_idx + 1})."
        if inv_num in db_invoices:
            return False, None, f"Invoice number '{inv_num}' already exists in database sales records."

    # SKU Lookup
    sku = str(row.get("sku", "")).strip().upper()
    if not sku:
        return False, None, "SKU is required."
    if sku not in db_products_map:
        return False, None, f"SKU '{sku}' does not exist in the product catalog."

    prod = db_products_map[sku]
    prod_id = prod["product_id"]

    # Quantity
    ok_qty, qty = parse_int(row.get("quantity"))
    if not ok_qty or qty is None or qty <= 0:
        return False, None, f"Quantity must be a positive integer (> 0). Got: '{row.get('quantity')}'."

    # Check available stock
    avail_qty = prod["avail_stock"]
    if avail_qty < qty:
        return False, None, (
            f"Insufficient inventory for '{prod['product_name']}' ({sku}): "
            f"Requested {qty} units, but only {avail_qty} units available in stock."
        )

    # Selling Price
    ok_sp, sell_price = parse_float(row.get("selling_price"))
    if not ok_sp or sell_price is None or sell_price <= 0:
        return False, None, f"Selling price must be a positive number (> 0). Got: '{row.get('selling_price')}'."

    # Discounts
    ok_disc_pct, disc_pct = parse_float(row.get("discount_pct"), default=0.0)
    if not ok_disc_pct or disc_pct is None or disc_pct < 0.0 or disc_pct > 100.0:
        return False, None, f"Discount percentage must be between 0.0 and 100.0%. Got: '{row.get('discount_pct')}'."

    ok_disc_amt, disc_amt = parse_float(row.get("overall_discount"), default=0.0)
    if not ok_disc_amt or disc_amt is None or disc_amt < 0.0:
        return False, None, f"Overall discount cannot be negative. Got: '{row.get('overall_discount')}'."

    # Payment mode
    pm = str(row.get("payment_mode", "CASH")).strip().upper()
    if pm not in ('UPI', 'CASH', 'CARD', 'CREDIT_KHATA', 'SPLIT'):
        return False, None, f"Invalid payment mode '{pm}'. Allowed: UPI, CASH, CARD, CREDIT_KHATA, SPLIT."

    # Transaction Reference
    txn_ref = str(row.get("transaction_reference", "")).strip() or None
    if txn_ref:
        if txn_ref.lower() in seen_txn_refs:
            return False, None, f"Duplicate transaction reference '{txn_ref}' in uploaded CSV."
        if txn_ref.lower() in db_txn_refs:
            return False, None, f"Transaction reference '{txn_ref}' has already been processed in database."

    # Festival Reference
    fest_ref = str(row.get("festival_reference", "")).strip() or None
    occurrence_id = None
    if fest_ref:
        if fest_ref.isdigit():
            occurrence_id = int(fest_ref)
        elif fest_ref in db_festivals_map:
            occurrence_id = db_festivals_map[fest_ref]

    # Customer Phone & Name
    phone = str(row.get("customer_phone", "")).strip() or None
    cust_name = str(row.get("customer_name", "")).strip() or None

    parsed_row = {
        "invoice_number": inv_num,
        "invoice_date": inv_date,
        "product_id": prod_id,
        "sku": sku,
        "quantity": qty,
        "selling_price": sell_price,
        "discount_pct": disc_pct,
        "overall_discount": disc_amt,
        "payment_mode": pm,
        "transaction_reference": txn_ref,
        "customer_phone": phone,
        "customer_name": cust_name,
        "occurrence_id": occurrence_id,
        "notes": str(row.get("notes", "")).strip() or None
    }
    return True, parsed_row, None


def validate_expense_row(
    row: Dict[str, Any],
    row_idx: int,
    seen_receipts: Set[str],
    db_receipts: Set[str],
    db_festivals_map: Dict[str, int]
) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """Validates single expense row with category normalization and audit rules."""
    # Date
    ok_date, exp_date, err_date = validate_date_str(row.get("expense_date"))
    if not ok_date:
        return False, None, f"Date Error: {err_date}"

    # Category
    cat_raw = str(row.get("category", "")).strip()
    if not cat_raw:
        return False, None, "Expense category is mandatory."
    
    cat_norm = normalize_category(cat_raw)
    valid_exp_codes = {c[0] for c in EXPENSE_CATEGORIES}
    if cat_norm not in valid_exp_codes:
        return False, None, f"Invalid category '{cat_raw}'. Allowed: {', '.join(sorted(valid_exp_codes))}."

    # Amount
    ok_amt, amount = parse_float(row.get("amount"))
    if not ok_amt or amount is None or amount <= 0:
        return False, None, f"Expense amount must be a positive number (> 0). Got: '{row.get('amount')}'."

    # Description
    desc = str(row.get("description", "")).strip()
    if not desc:
        return False, None, "Description is mandatory for expense auditing."

    # Receipt / Invoice reference
    receipt_no = str(row.get("invoice_receipt_no", "")).strip() or None
    if receipt_no:
        if receipt_no.lower() in seen_receipts:
            return False, None, f"Duplicate invoice_receipt_no '{receipt_no}' found in uploaded CSV."
        if receipt_no.lower() in db_receipts:
            return False, None, f"Invoice/Receipt number '{receipt_no}' already exists in database expenses."

    # Festival Reference
    fest_ref = str(row.get("festival_reference", "")).strip() or None
    occurrence_id = None
    if fest_ref:
        if fest_ref.isdigit():
            occurrence_id = int(fest_ref)
        elif fest_ref in db_festivals_map:
            occurrence_id = db_festivals_map[fest_ref]

    # Payment Mode
    pm = str(row.get("payment_mode", "CASH")).strip().upper()
    if pm not in ('CASH', 'UPI', 'BANK_TRANSFER', 'CARD', 'OTHER'):
        pm = 'CASH'

    parsed_row = {
        "expense_date": exp_date,
        "category": cat_norm,
        "amount": amount,
        "description": desc,
        "occurrence_id": occurrence_id,
        "payment_mode": pm,
        "vendor_name": str(row.get("vendor_name", "")).strip() or None,
        "invoice_receipt_no": receipt_no
    }
    return True, parsed_row, None


def validate_stock_row(
    row: Dict[str, Any],
    row_idx: int,
    seen_batches: Set[Tuple[int, str]],  # (product_id, batch_number)
    db_batches: Set[Tuple[int, str]],
    db_products_map: Dict[str, Dict[str, Any]]
) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
    """Validates single stock inward row ensuring ledger compliance."""
    sku = str(row.get("sku", "")).strip().upper()
    if not sku:
        return False, None, "SKU is required."
    if sku not in db_products_map:
        return False, None, f"SKU '{sku}' does not exist in the product catalog."

    prod = db_products_map[sku]
    prod_id = prod["product_id"]

    # Batch Number
    batch_num = str(row.get("batch_number", "")).strip().upper()
    if not batch_num:
        return False, None, "Batch number is required."

    batch_key = (prod_id, batch_num)
    if batch_key in seen_batches:
        return False, None, f"Duplicate batch '{batch_num}' for SKU '{sku}' found within uploaded CSV."
    if batch_key in db_batches:
        return False, None, f"Batch '{batch_num}' already exists in database for SKU '{sku}'."

    # Quantity
    ok_qty, qty = parse_int(row.get("quantity"))
    if not ok_qty or qty is None or qty <= 0:
        return False, None, f"Received quantity must be a positive integer (> 0). Got: '{row.get('quantity')}'."

    # Unit Cost
    ok_cost, unit_cost = parse_float(row.get("unit_cost"))
    if not ok_cost or unit_cost is None or unit_cost < 0:
        return False, None, f"Unit cost cannot be negative. Got: '{row.get('unit_cost')}'."

    # Received Date
    ok_rcv_date, rcv_date, err_rcv = validate_date_str(row.get("received_date"))
    if not ok_rcv_date:
        return False, None, f"Received Date Error: {err_rcv}"

    # Expiry Date (mandatory for perishable)
    exp_date_str = str(row.get("expiry_date", "")).strip() or None
    exp_date = None
    if exp_date_str:
        ok_exp_date, exp_date, err_exp = validate_date_str(exp_date_str)
        if not ok_exp_date:
            return False, None, f"Expiry Date Error: {err_exp}"
        if exp_date < rcv_date:
            return False, None, f"Expiry date ({exp_date}) cannot be earlier than received date ({rcv_date})."
    elif prod.get("is_perishable") == 1:
        return False, None, f"Expiry date is mandatory for perishable product '{prod['product_name']}'."

    parsed_row = {
        "product_id": prod_id,
        "sku": sku,
        "batch_number": batch_num,
        "quantity": qty,
        "unit_cost": unit_cost,
        "received_date": rcv_date,
        "expiry_date": exp_date,
        "supplier_name": str(row.get("supplier_name", "")).strip() or None,
        "storage_location": str(row.get("storage_location", "Main Store")).strip() or "Main Store",
        "purchase_invoice_no": str(row.get("purchase_invoice_no", "")).strip() or None,
        "reason": str(row.get("reason", "Inward Batch Import")).strip() or "Inward Batch Import"
    }
    return True, parsed_row, None


# ==============================================================================
# 5. PREVIEW & STAGING ENGINE
# ==============================================================================

def preview_import(file_or_content: Any, entity: str) -> Dict[str, Any]:
    """
    Parses and validates CSV rows without modifying the database.
    Returns preview summary, header validation status, and row-by-row diagnostic table.
    """
    df, err = parse_csv_file(file_or_content)
    if err:
        return {
            "success": False,
            "error": err,
            "total_rows": 0,
            "valid_rows_count": 0,
            "invalid_rows_count": 0,
            "preview_data": [],
            "missing_columns": []
        }

    df = standardize_columns(df, entity)
    is_valid_header, missing_cols = validate_csv_headers(df, entity)
    if not is_valid_header:
        return {
            "success": False,
            "error": f"Missing required columns in CSV header: {', '.join(missing_cols)}",
            "missing_columns": missing_cols,
            "total_rows": len(df),
            "valid_rows_count": 0,
            "invalid_rows_count": len(df),
            "preview_data": []
        }

    # Gather database reference sets for validation
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        
        # Products reference maps
        cursor.execute("SELECT product_id, sku, barcode, product_name, cost_price, selling_price, is_perishable FROM products")
        p_rows = cursor.fetchall()
        db_skus = {r["sku"] for r in p_rows}
        db_barcodes = {r["barcode"] for r in p_rows if r["barcode"]}
        
        # Compute available stock per product
        cursor.execute("""
            SELECT product_id, COALESCE(SUM(quantity_available), 0) AS avail
            FROM inventory_batches
            WHERE quantity_available > 0
            GROUP BY product_id
        """)
        stock_map = {r["product_id"]: int(r["avail"]) for r in cursor.fetchall()}

        db_products_map = {}
        for r in p_rows:
            db_products_map[r["sku"]] = {
                "product_id": r["product_id"],
                "product_name": r["product_name"],
                "cost_price": float(r["cost_price"]),
                "selling_price": float(r["selling_price"]),
                "is_perishable": int(r["is_perishable"]),
                "avail_stock": stock_map.get(r["product_id"], 0)
            }

        # Categories map
        cursor.execute("SELECT category_id, category_name FROM product_categories")
        category_map = {r["category_name"]: r["category_id"] for r in cursor.fetchall()}

        # Sales invoices reference sets
        cursor.execute("SELECT invoice_number, transaction_reference FROM sales_invoices")
        inv_rows = cursor.fetchall()
        db_invoices = {r["invoice_number"].upper() for r in inv_rows if r["invoice_number"]}
        db_txn_refs = {r["transaction_reference"].lower() for r in inv_rows if r["transaction_reference"]}

        # Expenses reference sets
        cursor.execute("SELECT invoice_receipt_no FROM expenses WHERE invoice_receipt_no IS NOT NULL")
        db_receipts = {r["invoice_receipt_no"].lower() for r in cursor.fetchall() if r["invoice_receipt_no"]}

        # Stock batches reference sets
        cursor.execute("SELECT product_id, batch_number FROM inventory_batches")
        db_batches = {(r["product_id"], r["batch_number"].upper()) for r in cursor.fetchall()}

        # Festivals map
        cursor.execute("""
            SELECT fo.occurrence_id, f.festival_code, f.festival_name, fo.year
            FROM festival_occurrences fo
            JOIN festivals f ON fo.festival_id = f.festival_id
        """)
        db_festivals_map = {}
        for r in cursor.fetchall():
            db_festivals_map[str(r["occurrence_id"])] = r["occurrence_id"]
            db_festivals_map[f"{r['festival_code']}_{r['year']}"] = r["occurrence_id"]
            db_festivals_map[r["festival_code"]] = r["occurrence_id"]

    finally:
        conn.close()

    # Track duplicates within file
    seen_skus: Set[str] = set()
    seen_barcodes: Set[str] = set()
    seen_invoices: Set[str] = set()
    seen_txn_refs: Set[str] = set()
    seen_receipts: Set[str] = set()
    seen_batches: Set[Tuple[int, str]] = set()

    # Virtual stock tracking for multi-row sales imports in same file
    virtual_stock = {sku: data["avail_stock"] for sku, data in db_products_map.items()}

    preview_rows = []
    valid_count = 0
    invalid_count = 0

    for idx, raw_row in df.iterrows():
        row_dict = raw_row.to_dict()
        row_num = idx + 1
        is_row_valid = False
        parsed_row = None
        error_msg = None

        if entity == "products":
            is_row_valid, parsed_row, error_msg = validate_product_row(
                row_dict, idx, seen_skus, seen_barcodes, db_skus, db_barcodes, category_map
            )
            if is_row_valid and parsed_row:
                seen_skus.add(parsed_row["sku"])
                if parsed_row["barcode"]:
                    seen_barcodes.add(parsed_row["barcode"])

        elif entity == "sales":
            # Temporarily inject virtual stock balance into lookup
            sku = str(row_dict.get("sku", "")).strip().upper()
            temp_prod_map = dict(db_products_map)
            if sku in temp_prod_map:
                temp_prod_map[sku] = dict(temp_prod_map[sku])
                temp_prod_map[sku]["avail_stock"] = virtual_stock.get(sku, 0)

            is_row_valid, parsed_row, error_msg = validate_sale_row(
                row_dict, idx, seen_invoices, seen_txn_refs, db_invoices, db_txn_refs, temp_prod_map, db_festivals_map
            )
            if is_row_valid and parsed_row:
                if parsed_row["invoice_number"]:
                    seen_invoices.add(parsed_row["invoice_number"])
                if parsed_row["transaction_reference"]:
                    seen_txn_refs.add(parsed_row["transaction_reference"].lower())
                # Deduct from virtual stock for subsequent rows in this CSV
                virtual_stock[sku] = virtual_stock.get(sku, 0) - parsed_row["quantity"]

        elif entity == "expenses":
            is_row_valid, parsed_row, error_msg = validate_expense_row(
                row_dict, idx, seen_receipts, db_receipts, db_festivals_map
            )
            if is_row_valid and parsed_row:
                if parsed_row["invoice_receipt_no"]:
                    seen_receipts.add(parsed_row["invoice_receipt_no"].lower())

        elif entity == "stock":
            is_row_valid, parsed_row, error_msg = validate_stock_row(
                row_dict, idx, seen_batches, db_batches, db_products_map
            )
            if is_row_valid and parsed_row:
                seen_batches.add((parsed_row["product_id"], parsed_row["batch_number"]))

        if is_row_valid:
            valid_count += 1
            status = "VALID"
        else:
            invalid_count += 1
            status = "INVALID"

        preview_entry = {
            "_row_num": row_num,
            "_status": status,
            "_error": error_msg or "",
            **row_dict
        }
        preview_rows.append(preview_entry)

    return {
        "success": True,
        "error": None,
        "total_rows": len(df),
        "valid_rows_count": valid_count,
        "invalid_rows_count": invalid_count,
        "can_import_atomic": (invalid_count == 0),
        "missing_columns": [],
        "preview_data": preview_rows
    }


# ==============================================================================
# 6. TRANSACTION-SAFE IMPORT EXECUTION ENGINE
# ==============================================================================

def execute_import(
    file_or_content: Any,
    entity: str,
    atomic: bool = True
) -> Dict[str, Any]:
    """
    Executes CSV import with strict validation and error handling.
    
    Modes:
      - atomic=True (Default): Runs as a single all-or-nothing transaction. If ANY row
        fails validation or constraint check, the entire batch rolls back.
      - atomic=False (Safe Row-by-Row): Validates and imports valid rows while isolating
        invalid rows into an explicit rejected report. Never silently discards rows.
    """
    preview = preview_import(file_or_content, entity)
    if not preview["success"]:
        return {
            "success": False,
            "error": preview["error"],
            "total_rows": 0,
            "accepted_count": 0,
            "rejected_count": 0,
            "accepted_rows": [],
            "rejected_rows": []
        }

    # If atomic mode is requested and there are validation errors, reject immediately without writing
    if atomic and preview["invalid_rows_count"] > 0:
        rejected_rows = [
            {"row_num": r["_row_num"], "reason": r["_error"], "raw_data": {k: v for k, v in r.items() if not k.startswith("_")}}
            for r in preview["preview_data"] if r["_status"] == "INVALID"
        ]
        return {
            "success": False,
            "error": f"Atomic import failed: {preview['invalid_rows_count']} invalid rows detected. Transaction rolled back with 0 changes applied.",
            "total_rows": preview["total_rows"],
            "accepted_count": 0,
            "rejected_count": len(rejected_rows),
            "accepted_rows": [],
            "rejected_rows": rejected_rows
        }

    accepted_rows: List[Dict[str, Any]] = []
    rejected_rows: List[Dict[str, Any]] = []

    # Execute DB insertions
    if atomic:
        # Single ACID transaction block
        with db_session() as conn:
            cursor = conn.cursor()
            try:
                for r in preview["preview_data"]:
                    row_data = {k: v for k, v in r.items() if not k.startswith("_")}
                    _import_single_row(cursor, entity, row_data, r["_row_num"], accepted_rows)
            except Exception as e:
                # Automatic rollback triggered by db_session() on exception
                return {
                    "success": False,
                    "error": f"Database transaction failed and was rolled back: {str(e)}",
                    "total_rows": preview["total_rows"],
                    "accepted_count": 0,
                    "rejected_count": preview["total_rows"],
                    "accepted_rows": [],
                    "rejected_rows": [{"row_num": "ALL", "reason": str(e), "raw_data": {}}]
                }
    else:
        # Row-by-row safe processing
        for r in preview["preview_data"]:
            row_num = r["_row_num"]
            row_data = {k: v for k, v in r.items() if not k.startswith("_")}
            
            if r["_status"] == "INVALID":
                rejected_rows.append({
                    "row_num": row_num,
                    "reason": r["_error"],
                    "raw_data": row_data
                })
                continue

            try:
                with db_session() as conn:
                    cursor = conn.cursor()
                    _import_single_row(cursor, entity, row_data, row_num, accepted_rows)
            except Exception as e:
                rejected_rows.append({
                    "row_num": row_num,
                    "reason": str(e),
                    "raw_data": row_data
                })

    return {
        "success": True,
        "error": None,
        "total_rows": preview["total_rows"],
        "accepted_count": len(accepted_rows),
        "rejected_count": len(rejected_rows),
        "accepted_rows": accepted_rows,
        "rejected_rows": rejected_rows
    }


def _import_single_row(
    cursor: Any,
    entity: str,
    row: Dict[str, Any],
    row_num: int,
    accepted_rows: List[Dict[str, Any]]
) -> None:
    """Helper writing a single verified row into the database."""
    if entity == "products":
        # Resolve category
        cat_raw = str(row.get("category", "")).strip()
        cursor.execute("SELECT category_id FROM product_categories WHERE category_id = ? OR LOWER(category_name) = LOWER(?)", (cat_raw, cat_raw))
        c_row = cursor.fetchone()
        cat_id = c_row["category_id"] if c_row else 1

        raw_tags = str(row.get("festival_tags", "")).split(",")
        cleaned_tags = [t.strip().upper() for t in raw_tags if t.strip()]

        data = {
            "sku": str(row["sku"]).strip().upper(),
            "barcode": str(row.get("barcode", "")).strip() or None,
            "product_name": str(row["product_name"]).strip(),
            "category_id": cat_id,
            "unit_of_measure": str(row.get("unit_of_measure", "pcs")).strip().lower(),
            "cost_price": float(row["cost_price"]),
            "selling_price": float(row["selling_price"]),
            "mrp": float(row.get("mrp") or row["selling_price"]),
            "gst_rate": float(row["gst_rate"]),
            "hsn_code": str(row.get("hsn_code", "")).strip() or None,
            "min_safety_stock": int(row.get("min_safety_stock") or 10),
            "reorder_quantity": int(row.get("reorder_quantity") or 50),
            "is_perishable": 1 if int(row.get("is_perishable") or 0) == 1 else 0,
            "shelf_life_days": int(row["shelf_life_days"]) if row.get("shelf_life_days") and str(row["shelf_life_days"]).strip() else None,
            "festival_tags": cleaned_tags
        }
        
        # Use ProductRepository insertion SQL
        sql_product = """
            INSERT INTO products (
                sku, barcode, product_name, category_id, unit_of_measure,
                cost_price, selling_price, mrp, gst_rate, hsn_code,
                min_safety_stock, reorder_quantity, is_perishable, shelf_life_days,
                festival_tags, region_tags, is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """
        cursor.execute(sql_product, (
            data["sku"],
            data["barcode"],
            data["product_name"],
            data["category_id"],
            data["unit_of_measure"],
            data["cost_price"],
            data["selling_price"],
            data["mrp"],
            data["gst_rate"],
            data["hsn_code"],
            data["min_safety_stock"],
            data["reorder_quantity"],
            data["is_perishable"],
            data["shelf_life_days"],
            json.dumps(data["festival_tags"]),
            json.dumps(["Pan-India"])
        ))
        p_id = cursor.lastrowid
        accepted_rows.append({"row_num": row_num, "identifier": data["sku"], "detail": f"Product '{data['product_name']}' created (ID #{p_id})"})

    elif entity == "sales":
        # Resolve product_id
        sku = str(row["sku"]).strip().upper()
        cursor.execute("SELECT product_id FROM products WHERE sku = ?", (sku,))
        p_row = cursor.fetchone()
        prod_id = p_row["product_id"]

        # Customer handling
        phone = str(row.get("customer_phone", "")).strip() or None
        cust_id = None
        if phone:
            cursor.execute("SELECT customer_id FROM customers WHERE phone = ?", (phone,))
            c_row = cursor.fetchone()
            if c_row:
                cust_id = c_row["customer_id"]
            else:
                c_name = str(row.get("customer_name", "Walk-in Customer")).strip() or "Walk-in Customer"
                cursor.execute("INSERT INTO customers (customer_name, phone) VALUES (?, ?)", (c_name, phone))
                cust_id = cursor.lastrowid

        # Occurrence handling
        occ_id = None
        fest_ref = str(row.get("festival_reference", "")).strip() or None
        if fest_ref:
            if fest_ref.isdigit():
                occ_id = int(fest_ref)
            else:
                cursor.execute("""
                    SELECT fo.occurrence_id FROM festival_occurrences fo
                    JOIN festivals f ON fo.festival_id = f.festival_id
                    WHERE f.festival_code = ? OR f.festival_code || '_' || fo.year = ?
                    LIMIT 1
                """, (fest_ref, fest_ref))
                f_row = cursor.fetchone()
                if f_row:
                    occ_id = f_row["occurrence_id"]

        items = [{
            "product_id": prod_id,
            "quantity": int(row["quantity"]),
            "selling_price": float(row["selling_price"]),
            "discount_percent": float(row.get("discount_pct") or 0.0)
        }]

        inv_id, inv_num = SalesRepository._execute_sale_in_cursor(
            cursor=cursor,
            items=items,
            payment_mode=str(row.get("payment_mode", "CASH")).strip().upper(),
            customer_id=cust_id,
            occurrence_id=occ_id,
            overall_discount=float(row.get("overall_discount") or 0.0),
            transaction_reference=str(row.get("transaction_reference", "")).strip() or None,
            notes=str(row.get("notes", "")).strip() or None,
            sale_date=str(row["invoice_date"]).strip(),
            custom_invoice_number=str(row.get("invoice_number", "")).strip().upper() or None
        )
        accepted_rows.append({"row_num": row_num, "identifier": inv_num, "detail": f"Sales Invoice {inv_num} recorded for {sku} (Qty: {row['quantity']})"})

    elif entity == "expenses":
        # Resolve occurrence
        occ_id = None
        fest_ref = str(row.get("festival_reference", "")).strip() or None
        if fest_ref:
            if fest_ref.isdigit():
                occ_id = int(fest_ref)
            else:
                cursor.execute("""
                    SELECT fo.occurrence_id FROM festival_occurrences fo
                    JOIN festivals f ON fo.festival_id = f.festival_id
                    WHERE f.festival_code = ? OR f.festival_code || '_' || fo.year = ?
                    LIMIT 1
                """, (fest_ref, fest_ref))
                f_row = cursor.fetchone()
                if f_row:
                    occ_id = f_row["occurrence_id"]

        # Insert expense
        amt = float(row["amount"])
        exp_date = str(row["expense_date"]).strip()
        cat = normalize_category(row["category"])
        desc = str(row["description"]).strip()
        pm = str(row.get("payment_mode", "CASH")).strip().upper()
        vendor = str(row.get("vendor_name", "")).strip() or None
        receipt = str(row.get("invoice_receipt_no", "")).strip() or None

        cursor.execute("""
            INSERT INTO expenses (
                occurrence_id, expense_category, amount, expense_date,
                payment_mode, vendor_name, invoice_receipt_no, notes, description, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE')
        """, (occ_id, cat, amt, exp_date, pm, vendor, receipt, desc, desc))
        exp_id = cursor.lastrowid

        # Insert audit log for expense
        cursor.execute("""
            INSERT INTO expense_audit_logs (
                expense_id, action, changed_by, previous_values, new_values, reason
            ) VALUES (?, 'CREATE', 'CSV_IMPORT', NULL, ?, 'Bulk CSV expense import')
        """, (exp_id, json.dumps({"amount": amt, "category": cat, "date": exp_date, "description": desc})))

        accepted_rows.append({"row_num": row_num, "identifier": f"EXP-#{exp_id}", "detail": f"Expense recorded: ₹{amt:,.2f} ({cat})"})

    elif entity == "stock":
        # Resolve product_id
        sku = str(row["sku"]).strip().upper()
        cursor.execute("SELECT product_id FROM products WHERE sku = ?", (sku,))
        p_row = cursor.fetchone()
        prod_id = p_row["product_id"]

        # Resolve supplier if name provided
        supp_name = str(row.get("supplier_name", "")).strip()
        supp_id = None
        if supp_name:
            cursor.execute("SELECT supplier_id FROM suppliers WHERE LOWER(supplier_name) = LOWER(?)", (supp_name,))
            s_row = cursor.fetchone()
            if s_row:
                supp_id = s_row["supplier_id"]
            else:
                cursor.execute("INSERT INTO suppliers (supplier_name, phone) VALUES (?, 'N/A')", (supp_name,))
                supp_id = cursor.lastrowid

        # Mandatory: Inbound batch creation MUST log in stock movement ledger!
        batch_clean = str(row["batch_number"]).strip().upper()
        qty = int(row["quantity"])
        unit_cost = float(row["unit_cost"])
        rcv_date = str(row["received_date"]).strip()
        exp_date = str(row.get("expiry_date", "")).strip() or None
        loc = str(row.get("storage_location", "Main Store")).strip() or "Main Store"
        reason = str(row.get("reason", "Inward Batch Import")).strip() or "Inward Batch Import"
        po_ref = str(row.get("purchase_invoice_no", "")).strip() or None

        cursor.execute("""
            INSERT INTO inventory_batches (
                product_id, batch_number, supplier_id, received_date,
                expiry_date, quantity_received, quantity_available, unit_cost, storage_location
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (prod_id, batch_clean, supp_id, rcv_date, exp_date, qty, qty, unit_cost, loc))
        batch_id = cursor.lastrowid

        # Write immutable RECEIPT entry into stock_movements ledger
        cursor.execute("""
            INSERT INTO stock_movements (
                product_id, batch_id, movement_type, quantity, unit_cost,
                total_cost_impact, reference_type, reference_id, reason, created_at
            ) VALUES (?, ?, 'RECEIPT', ?, ?, ?, 'PURCHASE_RECEIPT', ?, ?, ?)
        """, (
            prod_id,
            batch_id,
            qty,
            unit_cost,
            round(qty * unit_cost, 2),
            po_ref or f"BATCH-{batch_clean}",
            reason,
            f"{rcv_date} {datetime.now().strftime('%H:%M:%S')}"
        ))

        accepted_rows.append({"row_num": row_num, "identifier": batch_clean, "detail": f"Batch {batch_clean} received ({qty} units of {sku}) & recorded in movement ledger"})


# ==============================================================================
# 7. FILTERED EXPORTS WITH FULL UTF-8 COMPATIBILITY
# ==============================================================================

def export_products_to_csv(
    category_id: Optional[int] = None,
    is_active: Optional[int] = None,
    is_perishable: Optional[int] = None,
    search: Optional[str] = None
) -> str:
    """Exports products catalog with active filters and UTF-8 encoding."""
    sql = """
        SELECT 
            p.sku,
            p.barcode,
            p.product_name,
            pc.category_name AS category,
            p.unit_of_measure,
            p.cost_price,
            p.selling_price,
            p.mrp,
            p.gst_rate,
            p.hsn_code,
            p.min_safety_stock,
            p.reorder_quantity,
            p.is_perishable,
            p.shelf_life_days,
            p.festival_tags,
            p.is_active,
            COALESCE(SUM(b.quantity_available), 0) AS total_available_stock
        FROM products p
        LEFT JOIN product_categories pc ON p.category_id = pc.category_id
        LEFT JOIN inventory_batches b ON p.product_id = b.product_id AND b.quantity_available > 0
        WHERE 1=1
    """
    params: List[Any] = []
    if category_id:
        sql += " AND p.category_id = ?"
        params.append(category_id)
    if is_active is not None:
        sql += " AND p.is_active = ?"
        params.append(is_active)
    if is_perishable is not None:
        sql += " AND p.is_perishable = ?"
        params.append(is_perishable)
    if search and search.strip():
        sql += " AND (p.product_name LIKE ? OR p.sku LIKE ? OR p.barcode LIKE ?)"
        s_pat = f"%{search.strip()}%"
        params.extend([s_pat, s_pat, s_pat])

    sql += " GROUP BY p.product_id ORDER BY p.product_name ASC"
    df = query_df(sql, tuple(params))
    return sanitize_df_for_csv(df).to_csv(index=False)


def export_sales_to_csv(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    occurrence_id: Optional[int] = None,
    payment_mode: Optional[str] = None,
    status: Optional[str] = None
) -> str:
    """Exports sales invoice ledger with line items and active filters."""
    sql = """
        SELECT 
            inv.invoice_number,
            inv.invoice_date,
            inv.status,
            inv.payment_mode,
            c.customer_name,
            c.phone AS customer_phone,
            f.festival_name,
            p.sku,
            p.product_name,
            si.quantity,
            si.unit_selling_price,
            si.unit_cost_price,
            si.discount_percent,
            si.taxable_value,
            si.gst_rate,
            si.cgst_amount,
            si.sgst_amount,
            si.igst_amount,
            si.total_item_amount,
            si.gross_profit,
            inv.transaction_reference,
            inv.notes
        FROM sales_invoices inv
        JOIN sales_items si ON inv.invoice_id = si.invoice_id
        JOIN products p ON si.product_id = p.product_id
        LEFT JOIN customers c ON inv.customer_id = c.customer_id
        LEFT JOIN festival_occurrences fo ON inv.occurrence_id = fo.occurrence_id
        LEFT JOIN festivals f ON fo.festival_id = f.festival_id
        WHERE 1=1
    """
    params: List[Any] = []
    if start_date:
        sql += " AND inv.invoice_date >= ?"
        params.append(start_date)
    if end_date:
        sql += " AND inv.invoice_date <= ?"
        params.append(end_date)
    if occurrence_id:
        sql += " AND inv.occurrence_id = ?"
        params.append(occurrence_id)
    if payment_mode and payment_mode != "ALL":
        sql += " AND inv.payment_mode = ?"
        params.append(payment_mode)
    if status and status != "ALL":
        sql += " AND inv.status = ?"
        params.append(status)

    sql += " ORDER BY inv.invoice_date DESC, inv.invoice_id DESC"
    df = query_df(sql, tuple(params))
    return sanitize_df_for_csv(df).to_csv(index=False)


def export_expenses_to_csv(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    category: Optional[str] = None,
    occurrence_id: Optional[int] = None,
    status: Optional[str] = None
) -> str:
    """Exports expense records with active filters."""
    sql = """
        SELECT 
            e.expense_id,
            e.expense_date,
            e.expense_category AS category,
            e.amount,
            COALESCE(e.description, e.notes) AS description,
            e.status,
            e.payment_mode,
            e.vendor_name,
            e.invoice_receipt_no,
            f.festival_name,
            fo.year AS festival_year,
            e.created_at
        FROM expenses e
        LEFT JOIN festival_occurrences fo ON e.occurrence_id = fo.occurrence_id
        LEFT JOIN festivals f ON fo.festival_id = f.festival_id
        WHERE 1=1
    """
    params: List[Any] = []
    if start_date:
        sql += " AND e.expense_date >= ?"
        params.append(start_date)
    if end_date:
        sql += " AND e.expense_date <= ?"
        params.append(end_date)
    if category and category != "ALL":
        sql += " AND e.expense_category = ?"
        params.append(normalize_category(category))
    if occurrence_id:
        sql += " AND e.occurrence_id = ?"
        params.append(occurrence_id)
    if status and status != "ALL":
        sql += " AND e.status = ?"
        params.append(status)

    sql += " ORDER BY e.expense_date DESC, e.expense_id DESC"
    df = query_df(sql, tuple(params))
    return sanitize_df_for_csv(df).to_csv(index=False)


def export_stock_to_csv(
    category_id: Optional[int] = None,
    low_stock_only: bool = False,
    expiring_soon_days: Optional[int] = None,
    storage_location: Optional[str] = None
) -> str:
    """Exports active inventory stock batches with filters."""
    sql = """
        SELECT 
            p.sku,
            p.product_name,
            pc.category_name AS category,
            b.batch_number,
            b.quantity_available,
            b.quantity_received,
            b.unit_cost,
            (b.quantity_available * b.unit_cost) AS total_valuation,
            b.received_date,
            b.expiry_date,
            s.supplier_name,
            b.storage_location,
            p.min_safety_stock
        FROM inventory_batches b
        JOIN products p ON b.product_id = p.product_id
        LEFT JOIN product_categories pc ON p.category_id = pc.category_id
        LEFT JOIN suppliers s ON b.supplier_id = s.supplier_id
        WHERE b.quantity_available > 0
    """
    params: List[Any] = []
    if category_id:
        sql += " AND p.category_id = ?"
        params.append(category_id)
    if low_stock_only:
        sql += " AND p.min_safety_stock >= (SELECT COALESCE(SUM(b2.quantity_available), 0) FROM inventory_batches b2 WHERE b2.product_id = p.product_id)"
    if expiring_soon_days is not None:
        sql += f" AND b.expiry_date IS NOT NULL AND b.expiry_date <= date('now', '+{int(expiring_soon_days)} days')"
    if storage_location and storage_location != "ALL":
        sql += " AND b.storage_location = ?"
        params.append(storage_location)

    sql += " ORDER BY p.product_name ASC, b.received_date ASC"
    df = query_df(sql, tuple(params))
    return sanitize_df_for_csv(df).to_csv(index=False)
