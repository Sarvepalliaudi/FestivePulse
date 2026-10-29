"""
FestivePulse — Sales & Point of Sale (POS) Service
Handles rapid counter billing, Decimal monetary precision,
FIFO stock depletion, invoice generation, customer credit ledger, cancellations, and returns.
"""

from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from typing import List, Dict, Any, Tuple, Optional
import pandas as pd
from repositories.sales_repository import (
    SalesRepository,
    to_decimal,
    TWO_PLACES,
    ZERO,
    DuplicateTransactionError,
    InsufficientStockError,
    InvalidSaleError,
    InvalidReturnError,
    CustomerCreditLimitExceededError
)
from database.queries import get_business_settings, get_active_festival_occurrence


def calculate_line_gst(taxable_value: float, gst_rate: float, is_interstate: bool) -> Dict[str, float]:
    """
    Computes exact CGST, SGST, and IGST components using Decimal precision:
    - Intra-state: 50% CGST + 50% SGST
    - Inter-state: 100% IGST
    """
    dec_taxable = to_decimal(taxable_value)
    dec_gst = to_decimal(gst_rate)

    if is_interstate:
        cgst_rate = 0.0
        cgst_amount = ZERO
        sgst_rate = 0.0
        sgst_amount = ZERO
        igst_rate = float(dec_gst)
        igst_amount = (dec_taxable * (dec_gst / Decimal('100.00'))).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    else:
        half_rate = (dec_gst / Decimal('2.0')).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        cgst_rate = float(half_rate)
        cgst_amount = (dec_taxable * (half_rate / Decimal('100.00'))).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        sgst_rate = float(half_rate)
        sgst_amount = (dec_taxable * (half_rate / Decimal('100.00'))).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        igst_rate = 0.0
        igst_amount = ZERO

    total_line = dec_taxable + cgst_amount + sgst_amount + igst_amount

    return {
        "taxable_value": float(dec_taxable),
        "cgst_rate": cgst_rate,
        "cgst_amount": float(cgst_amount),
        "sgst_rate": sgst_rate,
        "sgst_amount": float(sgst_amount),
        "igst_rate": igst_rate,
        "igst_amount": float(igst_amount),
        "total_line_amount": float(total_line)
    }


def generate_invoice_number() -> str:
    """
    Generates sequential Indian FY Invoice Number.
    """
    return SalesRepository.generate_invoice_number()


def create_sales_invoice(
    customer_id: Any,
    payment_mode: str,
    items: List[Dict[str, Any]],  # [{"product_id": int, "quantity": int, "selling_price": float, "discount_pct": float}]
    overall_discount: float = 0.0,
    occurrence_id: Any = None,
    transaction_reference: Optional[str] = None,
    notes: Optional[str] = None,
    sale_date: Optional[str] = None,
    invoice_number: Optional[str] = None
) -> Tuple[int, str]:
    """
    Creates a complete sales invoice inside an atomic transaction:
    - Verifies stock availability
    - Depletes stock using FIFO batch selection
    - Exactly calculates GST & line profits using Decimal
    - Inserts invoice & line records
    - Updates customer Khata if credit
    - Logs auditable stock movement in ledger
    """
    c_id = int(customer_id) if customer_id else None
    occ_id = int(occurrence_id) if occurrence_id else None
    if occ_id is None:
        active_fest = get_active_festival_occurrence()
        if active_fest:
            occ_id = active_fest["occurrence_id"]

    return SalesRepository.create_sale_atomic(
        items=items,
        payment_mode=payment_mode,
        customer_id=c_id,
        occurrence_id=occ_id,
        overall_discount=overall_discount,
        transaction_reference=transaction_reference,
        notes=notes,
        sale_date=sale_date,
        invoice_number=invoice_number
    )


def cancel_sales_invoice(invoice_id: int, reason: str = "Customer Return / Order Cancellation") -> bool:
    """
    Cancels an invoice safely without deleting history:
    - Marks status as CANCELLED
    - Reverses inventory deductions back to batches
    - Logs reverse SALE_CANCEL stock movements
    - Reverses customer Khata credit if applicable
    """
    return SalesRepository.cancel_invoice_atomic(invoice_id=invoice_id, reason=reason)


def correct_sales_invoice(
    original_invoice_id: int,
    new_items: List[Dict[str, Any]],
    payment_mode: Optional[str] = None,
    customer_id: Optional[int] = None,
    overall_discount: float = 0.0,
    occurrence_id: Optional[int] = None,
    transaction_reference: Optional[str] = None,
    reason: str = "Invoice correction and re-issuance",
    sale_date: Optional[str] = None
) -> Tuple[int, str]:
    """
    Safely corrects an existing invoice by reversing original stock and customer credit,
    marking the original invoice as CANCELLED with an audit trail, and creating the corrected
    replacement invoice inside a single atomic ACID transaction. History is never deleted.
    """
    c_id = int(customer_id) if customer_id else None
    occ_id = int(occurrence_id) if occurrence_id else None
    return SalesRepository.correct_sale_atomic(
        original_invoice_id=original_invoice_id,
        new_items=new_items,
        payment_mode=payment_mode,
        customer_id=c_id,
        occurrence_id=occ_id,
        overall_discount=overall_discount,
        transaction_reference=transaction_reference,
        reason=reason,
        sale_date=sale_date
    )


def process_sales_return(
    invoice_id: int,
    returned_items: List[Dict[str, Any]],  # [{"item_id": int, "quantity": int, "reason": str, "restock": bool}]
    return_date: Optional[str] = None
) -> Tuple[int, str, float]:
    """
    Processes item-level sales returns with prorated Decimal refunds and stock adjustments.
    """
    return SalesRepository.process_sales_return_atomic(
        invoice_id=invoice_id,
        returned_items=returned_items,
        return_date=return_date
    )


def get_invoice_full_details(invoice_id: int) -> Dict[str, Any]:
    """
    Retrieves full invoice details including header, customer info, line items, and returns.
    """
    details = SalesRepository.get_invoice_by_id(invoice_id)
    if not details:
        raise ValueError(f"Invoice {invoice_id} not found.")
    return details


def get_sales_report_df(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    payment_mode: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    occurrence_id: Optional[int] = None,
    customer_id: Optional[int] = None,
    limit: int = 150
) -> pd.DataFrame:
    """
    Returns filtered sales invoice records as a pandas DataFrame.
    """
    invoices = SalesRepository.get_invoices(
        occurrence_id=occurrence_id,
        customer_id=customer_id,
        start_date=start_date,
        end_date=end_date,
        payment_mode=payment_mode,
        status=status,
        search=search,
        limit=limit
    )
    if not invoices:
        return pd.DataFrame(columns=[
            "invoice_id", "invoice_number", "invoice_date", "customer_name",
            "customer_phone", "payment_mode", "subtotal_amount", "discount_amount",
            "total_taxable_amount", "cgst_amount", "sgst_amount", "igst_amount",
            "roundoff_amount", "net_total_amount", "status", "transaction_reference", "notes"
        ])
    return pd.DataFrame(invoices)


def get_sales_line_items_df(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    payment_mode: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    occurrence_id: Optional[int] = None,
    limit: int = 500
) -> pd.DataFrame:
    """
    Returns detailed line-item level sales records including SKU, product name,
    batch, quantity, rate, discount, GST breakdown, line total, and gross profit.
    """
    from database.connection import get_db_connection
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        sql = """
            SELECT
                inv.invoice_number,
                inv.invoice_date,
                COALESCE(cust.customer_name, 'Cash / Walk-in') AS customer_name,
                inv.payment_mode,
                inv.status,
                inv.transaction_reference,
                p.sku,
                p.product_name,
                p.unit_of_measure,
                b.batch_number,
                si.quantity,
                si.unit_selling_price,
                si.discount_percent,
                si.taxable_value,
                si.gst_rate,
                si.cgst_amount,
                si.sgst_amount,
                si.igst_amount,
                si.total_item_amount,
                si.gross_profit
            FROM sales_items si
            JOIN sales_invoices inv ON si.invoice_id = inv.invoice_id
            JOIN products p ON si.product_id = p.product_id
            LEFT JOIN customers cust ON inv.customer_id = cust.customer_id
            LEFT JOIN inventory_batches b ON si.batch_id = b.batch_id
            WHERE 1=1
        """
        params: List[Any] = []
        if occurrence_id:
            sql += " AND inv.occurrence_id = ?"
            params.append(occurrence_id)
        if start_date:
            sql += " AND inv.invoice_date >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND inv.invoice_date <= ?"
            params.append(end_date)
        if payment_mode:
            sql += " AND inv.payment_mode = ?"
            params.append(payment_mode)
        if status:
            sql += " AND inv.status = ?"
            params.append(status)
        if search:
            term = f"%{search.strip()}%"
            sql += " AND (inv.invoice_number LIKE ? OR inv.transaction_reference LIKE ? OR cust.customer_name LIKE ? OR p.product_name LIKE ? OR p.sku LIKE ?)"
            params.extend([term, term, term, term, term])

        sql += " ORDER BY inv.invoice_date DESC, inv.invoice_id DESC, si.item_id ASC LIMIT ?"
        params.append(limit)

        cursor.execute(sql, tuple(params))
        rows = [dict(r) for r in cursor.fetchall()]
        if not rows:
            return pd.DataFrame(columns=[
                "invoice_number", "invoice_date", "customer_name", "payment_mode",
                "status", "transaction_reference", "sku", "product_name",
                "unit_of_measure", "batch_number", "quantity", "unit_selling_price",
                "discount_percent", "taxable_value", "gst_rate", "cgst_amount",
                "sgst_amount", "igst_amount", "total_item_amount", "gross_profit"
            ])
        return pd.DataFrame(rows)
    finally:
        conn.close()


def get_sales_returns_df(invoice_id: Optional[int] = None, limit: int = 50) -> pd.DataFrame:
    """
    Returns sales return records as a pandas DataFrame.
    """
    returns = SalesRepository.get_sales_returns(invoice_id=invoice_id, limit=limit)
    if not returns:
        return pd.DataFrame(columns=[
            "return_id", "return_number", "invoice_id", "invoice_number",
            "product_name", "sku", "return_date", "quantity", "refund_amount",
            "reason", "restock_to_inventory", "created_at"
        ])
    return pd.DataFrame(returns)


def get_sales_kpis(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    occurrence_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Computes key executive sales KPIs for the selected date range or festival,
    properly accounting for sales returns and refunds.
    """
    df = get_sales_report_df(start_date=start_date, end_date=end_date, occurrence_id=occurrence_id, limit=2000)
    returns_df = get_sales_returns_df(limit=2000)

    # Filter returns by date range if specified
    if not returns_df.empty:
        if start_date:
            returns_df = returns_df[returns_df["return_date"] >= start_date]
        if end_date:
            returns_df = returns_df[returns_df["return_date"] <= end_date]
        total_refunds = float(returns_df["refund_amount"].sum())
        total_returns_records = len(returns_df)
    else:
        total_refunds = 0.0
        total_returns_records = 0

    if df.empty:
        return {
            "total_revenue": 0.0,
            "gross_revenue": 0.0,
            "net_revenue": 0.0,
            "total_invoices": 0,
            "total_tax": 0.0,
            "completed_revenue": 0.0,
            "completed_count": 0,
            "cancelled_count": 0,
            "returns_count": total_returns_records,
            "refund_amount": 0.0
        }

    active_sales = df[df["status"].isin(["COMPLETED", "PARTIALLY_RETURNED", "RETURNED"])]
    gross_rev = float(active_sales["net_total_amount"].sum())
    completed = df[df["status"] == "COMPLETED"]
    completed_rev = float(completed["net_total_amount"].sum())

    total_tax = float((active_sales["cgst_amount"] + active_sales["sgst_amount"] + active_sales["igst_amount"]).sum())
    net_rev = max(0.0, round(gross_rev - total_refunds, 2))

    return {
        "total_revenue": net_rev,
        "gross_revenue": round(gross_rev, 2),
        "net_revenue": net_rev,
        "total_invoices": len(df),
        "total_tax": round(total_tax, 2),
        "completed_revenue": round(completed_rev, 2),
        "completed_count": len(completed),
        "cancelled_count": len(df[df["status"] == "CANCELLED"]),
        "returns_count": len(df[df["status"].isin(["RETURNED", "PARTIALLY_RETURNED"])]),
        "returns_records_count": total_returns_records,
        "refund_amount": round(total_refunds, 2)
    }
