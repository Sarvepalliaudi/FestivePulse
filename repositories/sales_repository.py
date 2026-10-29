"""
FestivePulse — Sales Repository
Handles atomic sales invoice generation, Decimal monetary precision,
FIFO inventory depletion, duplicate transaction prevention, immutable stock movement logging,
safe cancellation reversals, and item-level returns.
"""

from decimal import Decimal, ROUND_HALF_UP
from datetime import date, datetime
from typing import List, Dict, Any, Optional, Tuple
import sqlite3
from database.connection import get_db_connection, db_session
from config import INDIAN_STATES


class DuplicateTransactionError(ValueError):
    """Raised when attempting to submit a sale with an already processed transaction reference."""
    pass


class InsufficientStockError(ValueError):
    """Raised when available stock is insufficient to fulfill a sale."""
    pass


class InvalidSaleError(ValueError):
    """Raised when a sale payload is invalid (e.g. non-positive quantity, invalid prices)."""
    pass


class InvalidReturnError(ValueError):
    """Raised when return quantities exceed original sold quantities or return payload is invalid."""
    pass


class CustomerCreditLimitExceededError(ValueError):
    """Raised when a Khata purchase exceeds the customer's authorized credit limit."""
    pass


TWO_PLACES = Decimal('0.01')
ZERO = Decimal('0.00')


def to_decimal(val: Any) -> Decimal:
    """Converts a value to Decimal with 2 decimal places using ROUND_HALF_UP."""
    if val is None:
        return ZERO
    if isinstance(val, Decimal):
        return val.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    return Decimal(str(val)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


class SalesRepository:

    @staticmethod
    def generate_invoice_number() -> str:
        """
        Generates sequential Indian FY Invoice Number:
        e.g. INV-202627-0001
        """
        today = date.today()
        if today.month >= 4:
            full_fy = f"{today.year}{today.year + 1}"
        else:
            full_fy = f"{today.year - 1}{today.year}"

        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT invoice_number FROM sales_invoices WHERE invoice_number LIKE ? ORDER BY invoice_id DESC LIMIT 1",
                (f"INV-{full_fy}-%",)
            )
            last = cursor.fetchone()
            if last and last["invoice_number"]:
                try:
                    num_part = int(last["invoice_number"].split("-")[-1])
                    next_seq = num_part + 1
                except Exception:
                    cursor.execute("SELECT COUNT(*) FROM sales_invoices")
                    next_seq = cursor.fetchone()[0] + 1
            else:
                next_seq = 1
            return f"INV-{full_fy}-{next_seq:04d}"
        finally:
            conn.close()

    @staticmethod
    def generate_return_number() -> str:
        """
        Generates sequential Sales Return Number:
        e.g. RET-202627-0001
        """
        today = date.today()
        if today.month >= 4:
            full_fy = f"{today.year}{today.year + 1}"
        else:
            full_fy = f"{today.year - 1}{today.year}"

        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT return_number FROM sales_returns WHERE return_number LIKE ? ORDER BY return_id DESC LIMIT 1",
                (f"RET-{full_fy}-%",)
            )
            last = cursor.fetchone()
            if last and last["return_number"]:
                try:
                    num_part = int(last["return_number"].split("-")[-1])
                    next_seq = num_part + 1
                except Exception:
                    cursor.execute("SELECT COUNT(*) FROM sales_returns")
                    next_seq = cursor.fetchone()[0] + 1
            else:
                next_seq = 1
            return f"RET-{full_fy}-{next_seq:04d}"
        finally:
            conn.close()

    @staticmethod
    def _execute_sale_in_cursor(
        cursor: sqlite3.Cursor,
        items: List[Dict[str, Any]],
        payment_mode: str,
        customer_id: Optional[int] = None,
        occurrence_id: Optional[int] = None,
        overall_discount: float = 0.0,
        transaction_reference: Optional[str] = None,
        notes: Optional[str] = None,
        sale_date: Optional[str] = None,
        is_correction: bool = False,
        custom_invoice_number: Optional[str] = None
    ) -> Tuple[int, str]:
        """
        Core atomic sale insertion and stock allocation logic running on an active database cursor:
        1. Validates inputs & quantities (> 0).
        2. Enforces non-duplicate transaction references within active invoices.
        3. Validates unexpired available stock across all line items per product.
        4. Depletes batches via FIFO order using in-memory tracking.
        5. Computes exact line totals, discounts, taxes (CGST/SGST/IGST), and roundoff using Decimal.
        6. Writes to sales_invoices and sales_items.
        7. Logs immutable SALE (-qty) movements in stock_movements.
        8. Updates customer Khata balance if CREDIT_KHATA.
        """
        if not items:
            raise InvalidSaleError("Cannot create a sale without line items.")

        if payment_mode not in ('UPI', 'CASH', 'CARD', 'CREDIT_KHATA', 'SPLIT'):
            raise InvalidSaleError(f"Invalid payment mode: '{payment_mode}'.")

        if not sale_date:
            sale_date = date.today().strftime("%Y-%m-%d")

        ref_clean = transaction_reference.strip() if transaction_reference and transaction_reference.strip() else None

        # Duplicate transaction check inside active transaction lock
        if ref_clean:
            cursor.execute(
                "SELECT invoice_number FROM sales_invoices WHERE LOWER(TRIM(transaction_reference)) = LOWER(?) AND status != 'CANCELLED'",
                (ref_clean,)
            )
            dup = cursor.fetchone()
            if dup:
                raise DuplicateTransactionError(
                    f"Transaction reference '{ref_clean}' has already been processed in Invoice {dup['invoice_number']}."
                )

        # Store state & inter-state calculation
        cursor.execute("SELECT state_code FROM business_settings WHERE setting_id = 1")
        s_row = cursor.fetchone()
        store_state_code = s_row["state_code"] if s_row else "27"

        is_interstate = False
        cust_row = None
        if customer_id:
            cursor.execute("SELECT * FROM customers WHERE customer_id = ?", (customer_id,))
            cust_row = cursor.fetchone()
            if cust_row and cust_row["state"]:
                c_state_lower = cust_row["state"].strip().lower()
                for code, s_name in INDIAN_STATES.items():
                    if s_name.lower() == c_state_lower and code != store_state_code:
                        is_interstate = True
                        break

        # 1. Validate line inputs and calculate aggregated requested quantity per product
        requested_by_prod: Dict[int, int] = {}
        for it in items:
            p_id = int(it["product_id"])
            qty_needed = int(it["quantity"])
            sell_rate = to_decimal(it["selling_price"])

            if qty_needed <= 0:
                raise InvalidSaleError(f"Quantity must be greater than zero for product ID {p_id}.")

            if sell_rate < ZERO:
                raise InvalidSaleError(f"Selling price cannot be negative for product ID {p_id}.")

            # Validate discount percentage if present
            if "discount_percent" in it or "discount_pct" in it or "discount" in it:
                d_val = to_decimal(it.get("discount_percent", it.get("discount_pct", it.get("discount", 0.0))))
                if "discount_amount" not in it and (d_val < ZERO or d_val > Decimal('100.00')):
                    raise InvalidSaleError("Discount percent must be between 0% and 100%.")

            if "discount_amount" in it and it["discount_amount"] is not None:
                d_amt = to_decimal(it["discount_amount"])
                if d_amt < ZERO:
                    raise InvalidSaleError("Discount amount cannot be negative.")

            requested_by_prod[p_id] = requested_by_prod.get(p_id, 0) + qty_needed

        # 2. Check catalog existence and aggregate stock availability per product
        for p_id, total_req in requested_by_prod.items():
            cursor.execute("SELECT product_name, sku FROM products WHERE product_id = ?", (p_id,))
            p_row = cursor.fetchone()
            if not p_row:
                raise InvalidSaleError(f"Product ID {p_id} not found in catalog.")

            cursor.execute("""
                SELECT COALESCE(SUM(quantity_available), 0) AS total_avail
                FROM inventory_batches
                WHERE product_id = ? AND quantity_available > 0
                  AND (expiry_date IS NULL OR expiry_date >= ?)
            """, (p_id, sale_date))
            avail_row = cursor.fetchone()
            avail = avail_row["total_avail"] if avail_row else 0
            if avail < total_req:
                raise InsufficientStockError(
                    f"Insufficient stock for '{p_row['product_name']}' ({p_row['sku']}): "
                    f"Requested {total_req} units, but only {avail} available in inventory."
                )

        dec_overall_disc = to_decimal(overall_discount)
        dec_subtotal = ZERO
        dec_line_taxable_sum = ZERO
        dec_cgst_sum = ZERO
        dec_sgst_sum = ZERO
        dec_igst_sum = ZERO

        prepared_lines = []
        batch_deductions_to_apply = []
        batch_avail_map: Dict[int, int] = {}

        # 3. Allocate batches in FIFO order and calculate exact Decimal amounts
        for item in items:
            prod_id = int(item["product_id"])
            qty_needed = int(item["quantity"])
            sell_rate = to_decimal(item["selling_price"])

            cursor.execute("SELECT product_name, sku, cost_price, gst_rate FROM products WHERE product_id = ?", (prod_id,))
            p_row = cursor.fetchone()
            p_gst = to_decimal(p_row["gst_rate"])

            # Query FIFO batches for product
            cursor.execute("""
                SELECT batch_id, batch_number, quantity_available, unit_cost
                FROM inventory_batches
                WHERE product_id = ? AND quantity_available > 0
                  AND (expiry_date IS NULL OR expiry_date >= ?)
                ORDER BY (expiry_date IS NULL), expiry_date ASC, received_date ASC
            """, (prod_id, sale_date))
            batches = cursor.fetchall()

            for b in batches:
                b_id = b["batch_id"]
                if b_id not in batch_avail_map:
                    batch_avail_map[b_id] = b["quantity_available"]

            remaining = qty_needed
            for b in batches:
                if remaining <= 0:
                    break
                b_id = b["batch_id"]
                b_avail = batch_avail_map.get(b_id, 0)
                if b_avail <= 0:
                    continue
                b_cost = to_decimal(b["unit_cost"])

                alloc_qty = min(remaining, b_avail)
                batch_avail_map[b_id] -= alloc_qty
                batch_deductions_to_apply.append((b_id, alloc_qty, prod_id, b_cost))

                # Exact Decimal pricing
                line_gross = (Decimal(alloc_qty) * sell_rate).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

                # Determine discount
                if "discount_amount" in item and item["discount_amount"] is not None and to_decimal(item["discount_amount"]) > ZERO:
                    fixed_disc = to_decimal(item["discount_amount"])
                    prorated_fixed_disc = (fixed_disc * (Decimal(alloc_qty) / Decimal(qty_needed))).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
                    line_disc = min(line_gross, prorated_fixed_disc)
                    disc_pct = ((line_disc / line_gross) * Decimal('100.00')).quantize(TWO_PLACES, rounding=ROUND_HALF_UP) if line_gross > ZERO else ZERO
                else:
                    disc_pct = to_decimal(item.get("discount_percent", item.get("discount_pct", item.get("discount", 0.0))))
                    if disc_pct < ZERO or disc_pct > Decimal('100.00'):
                        raise InvalidSaleError("Discount percent must be between 0% and 100%.")
                    line_disc = (line_gross * (disc_pct / Decimal('100.00'))).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

                line_taxable = line_gross - line_disc

                # GST Calculation
                if is_interstate:
                    line_cgst = ZERO
                    line_sgst = ZERO
                    line_igst = (line_taxable * (p_gst / Decimal('100.00'))).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
                    cgst_rate_val = ZERO
                    sgst_rate_val = ZERO
                    igst_rate_val = p_gst
                else:
                    half_rate = p_gst / Decimal('2.0')
                    line_cgst = (line_taxable * (half_rate / Decimal('100.00'))).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
                    line_sgst = (line_taxable * (half_rate / Decimal('100.00'))).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
                    line_igst = ZERO
                    cgst_rate_val = half_rate
                    sgst_rate_val = half_rate
                    igst_rate_val = ZERO

                line_total = line_taxable + line_cgst + line_sgst + line_igst
                line_cost_total = (Decimal(alloc_qty) * b_cost).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
                line_profit = line_taxable - line_cost_total

                prepared_lines.append({
                    "product_id": prod_id,
                    "batch_id": b_id,
                    "quantity": alloc_qty,
                    "unit_cost_price": float(b_cost),
                    "unit_selling_price": float(sell_rate),
                    "discount_percent": float(disc_pct),
                    "taxable_value": float(line_taxable),
                    "gst_rate": float(p_gst),
                    "cgst_rate": float(cgst_rate_val),
                    "cgst_amount": float(line_cgst),
                    "sgst_rate": float(sgst_rate_val),
                    "sgst_amount": float(line_sgst),
                    "igst_rate": float(igst_rate_val),
                    "igst_amount": float(line_igst),
                    "total_item_amount": float(line_total),
                    "gross_profit": float(line_profit)
                })

                dec_subtotal += line_gross
                dec_line_taxable_sum += line_taxable
                dec_cgst_sum += line_cgst
                dec_sgst_sum += line_sgst
                dec_igst_sum += line_igst

                remaining -= alloc_qty

        # Overall discount and net totals
        final_taxable = max(ZERO, dec_line_taxable_sum - dec_overall_disc)
        net_before_round = final_taxable + dec_cgst_sum + dec_sgst_sum + dec_igst_sum
        rounded_total = net_before_round.quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        roundoff = rounded_total - net_before_round
        float_rounded_total = float(rounded_total)

        # Customer Khata Credit Check
        if payment_mode == "CREDIT_KHATA":
            if not customer_id or not cust_row:
                raise InvalidSaleError("Credit Khata sales require selecting a registered customer.")
            cur_credit = float(cust_row["outstanding_credit"])
            credit_limit = float(cust_row["credit_limit"])
            if credit_limit > 0 and (cur_credit + float_rounded_total > credit_limit):
                raise CustomerCreditLimitExceededError(
                    f"Khata credit limit exceeded for {cust_row['customer_name']}. "
                    f"Current: ₹{cur_credit:,.2f}, New Bill: ₹{float_rounded_total:,.2f}, Limit: ₹{credit_limit:,.2f}."
                )

        if custom_invoice_number and str(custom_invoice_number).strip():
            inv_clean = str(custom_invoice_number).strip().upper()
            cursor.execute("SELECT invoice_id FROM sales_invoices WHERE invoice_number = ?", (inv_clean,))
            if cursor.fetchone():
                raise DuplicateTransactionError(f"Invoice number '{inv_clean}' already exists in the system.")
            invoice_number = inv_clean
        else:
            invoice_number = SalesRepository.generate_invoice_number()

        # Insert Invoice Header
        cursor.execute("""
            INSERT INTO sales_invoices (
                invoice_number, invoice_date, customer_id, occurrence_id,
                payment_mode, subtotal_amount, discount_amount, total_taxable_amount,
                cgst_amount, sgst_amount, igst_amount, roundoff_amount,
                net_total_amount, is_interstate, status, transaction_reference, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'COMPLETED', ?, ?)
        """, (
            invoice_number,
            sale_date,
            customer_id,
            occurrence_id,
            payment_mode,
            float(dec_subtotal),
            float(dec_overall_disc),
            float(final_taxable),
            float(dec_cgst_sum),
            float(dec_sgst_sum),
            float(dec_igst_sum),
            float(roundoff),
            float_rounded_total,
            1 if is_interstate else 0,
            ref_clean,
            notes
        ))
        invoice_id = cursor.lastrowid

        # Insert Line Items
        for item_row in prepared_lines:
            cursor.execute("""
                INSERT INTO sales_items (
                    invoice_id, product_id, batch_id, quantity, unit_cost_price,
                    unit_selling_price, discount_percent, taxable_value, gst_rate,
                    cgst_rate, cgst_amount, sgst_rate, sgst_amount, igst_rate, igst_amount,
                    total_item_amount, gross_profit
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                invoice_id,
                item_row["product_id"],
                item_row["batch_id"],
                item_row["quantity"],
                item_row["unit_cost_price"],
                item_row["unit_selling_price"],
                item_row["discount_percent"],
                item_row["taxable_value"],
                item_row["gst_rate"],
                item_row["cgst_rate"],
                item_row["cgst_amount"],
                item_row["sgst_rate"],
                item_row["sgst_amount"],
                item_row["igst_rate"],
                item_row["igst_amount"],
                item_row["total_item_amount"],
                item_row["gross_profit"]
            ))

        # Deduct inventory batch stock and record immutable SALE movements
        for b_id, alloc_q, p_id, b_cost in batch_deductions_to_apply:
            cursor.execute(
                "UPDATE inventory_batches SET quantity_available = quantity_available - ? WHERE batch_id = ?",
                (alloc_q, b_id)
            )
            cursor.execute("""
                INSERT INTO stock_movements (
                    product_id, batch_id, movement_type, quantity, unit_cost,
                    total_cost_impact, reference_type, reference_id, reason, created_at
                ) VALUES (?, ?, 'SALE', ?, ?, ?, 'SALES_INVOICE', ?, ?, ?)
            """, (
                p_id,
                b_id,
                -int(alloc_q),
                float(b_cost),
                float((Decimal(alloc_q) * b_cost).quantize(TWO_PLACES)),
                invoice_number,
                f"Sale via Invoice {invoice_number}",
                f"{sale_date} {datetime.now().strftime('%H:%M:%S')}"
            ))

        # Update Customer Khata balance if credit sale
        if customer_id and payment_mode == "CREDIT_KHATA":
            cursor.execute(
                "UPDATE customers SET outstanding_credit = outstanding_credit + ? WHERE customer_id = ?",
                (float_rounded_total, customer_id)
            )

        return invoice_id, invoice_number

    @staticmethod
    def create_sale_atomic(
        items: List[Dict[str, Any]],
        payment_mode: str,
        customer_id: Optional[int] = None,
        occurrence_id: Optional[int] = None,
        overall_discount: float = 0.0,
        transaction_reference: Optional[str] = None,
        notes: Optional[str] = None,
        sale_date: Optional[str] = None,
        invoice_number: Optional[str] = None
    ) -> Tuple[int, str]:
        """
        Atomically executes complete sale transaction using Decimal monetary precision:
        1. Validates inputs & quantities (> 0).
        2. Prevents duplicate transaction submissions (via transaction_reference).
        3. Validates unexpired stock availability per product across all line items.
        4. Depletes batches via FIFO order.
        5. Computes exact line totals, discounts, CGST/SGST/IGST, and roundoff using Decimal.
        6. Writes to sales_invoices and sales_items.
        7. Logs auditable SALE (-qty) movements in stock_movements.
        8. Updates customer Khata credit if CREDIT_KHATA.
        """
        with db_session() as conn:
            cursor = conn.cursor()
            return SalesRepository._execute_sale_in_cursor(
                cursor=cursor,
                items=items,
                payment_mode=payment_mode,
                customer_id=customer_id,
                occurrence_id=occurrence_id,
                overall_discount=overall_discount,
                transaction_reference=transaction_reference,
                notes=notes,
                sale_date=sale_date,
                custom_invoice_number=invoice_number
            )

    @staticmethod
    def correct_sale_atomic(
        original_invoice_id: int,
        new_items: List[Dict[str, Any]],
        payment_mode: Optional[str] = None,
        customer_id: Optional[int] = None,
        occurrence_id: Optional[int] = None,
        overall_discount: float = 0.0,
        transaction_reference: Optional[str] = None,
        reason: str = "Invoice correction and re-issuance",
        sale_date: Optional[str] = None
    ) -> Tuple[int, str]:
        """
        Atomically corrects an existing sales invoice by:
        1. Verifying original invoice is eligible (not already cancelled).
        2. Reversing inventory deductions and logging SALE_CANCEL in stock_movements.
        3. Reversing customer Khata credit if applicable.
        4. Marking original invoice as 'CANCELLED' with audit note linking to replacement invoice.
        5. Creating the corrected replacement invoice with revised items, batch allocations, and stock movements.
        6. Entire process is executed in a single atomic ACID transaction.
           If the new sale fails (e.g. insufficient stock or validation error), everything rolls back!
        Returns (new_invoice_id, new_invoice_number).
        """
        if not reason or not reason.strip():
            raise ValueError("A reason for invoice correction must be provided.")

        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sales_invoices WHERE invoice_id = ?", (original_invoice_id,))
            orig_inv = cursor.fetchone()
            if not orig_inv:
                raise ValueError(f"Original Invoice ID {original_invoice_id} not found.")

            if orig_inv["status"] == "CANCELLED":
                raise ValueError(f"Cannot correct Invoice {orig_inv['invoice_number']} because it is already cancelled.")

            orig_num = orig_inv["invoice_number"]

            # 1. Reverse inventory batches from the original invoice
            cursor.execute("""
                SELECT batch_id, quantity, product_id, unit_cost_price
                FROM sales_items
                WHERE invoice_id = ?
            """, (original_invoice_id,))
            orig_items = cursor.fetchall()

            reversal_date = sale_date or date.today().strftime("%Y-%m-%d")
            for it in orig_items:
                b_id = it["batch_id"]
                q = it["quantity"]
                p_id = it["product_id"]
                u_cost = float(it["unit_cost_price"])
                if b_id and q > 0:
                    cursor.execute(
                        "UPDATE inventory_batches SET quantity_available = quantity_available + ? WHERE batch_id = ?",
                        (q, b_id)
                    )
                    cursor.execute("""
                        INSERT INTO stock_movements (
                            product_id, batch_id, movement_type, quantity, unit_cost,
                            total_cost_impact, reference_type, reference_id, reason, created_at
                        ) VALUES (?, ?, 'SALE_CANCEL', ?, ?, ?, 'INVOICE_CANCEL', ?, ?, ?)
                    """, (
                        p_id, b_id, int(q), u_cost, round(q * u_cost, 2),
                        orig_num,
                        f"Reversal for correction of {orig_num}: {reason.strip()}",
                        f"{reversal_date} {datetime.now().strftime('%H:%M:%S')}"
                    ))

            # 2. Reverse Khata credit from original invoice if CREDIT_KHATA
            if orig_inv["payment_mode"] == "CREDIT_KHATA" and orig_inv["customer_id"]:
                cursor.execute(
                    "UPDATE customers SET outstanding_credit = MAX(0.0, outstanding_credit - ?) WHERE customer_id = ?",
                    (float(orig_inv["net_total_amount"]), orig_inv["customer_id"])
                )

            # 3. Mark original invoice CANCELLED with audit trail
            cancel_note = (orig_inv["notes"] or "") + f" [Cancelled & replaced by correction: {reason.strip()}]"
            cursor.execute(
                "UPDATE sales_invoices SET status = 'CANCELLED', notes = ? WHERE invoice_id = ?",
                (cancel_note.strip(), original_invoice_id)
            )

            # 4. Create the new corrected sale inside the same transaction
            eff_pay_mode = payment_mode or orig_inv["payment_mode"]
            eff_cust_id = customer_id if customer_id is not None else orig_inv["customer_id"]
            eff_occ_id = occurrence_id if occurrence_id is not None else orig_inv["occurrence_id"]
            eff_date = sale_date or orig_inv["invoice_date"]
            eff_notes = f"Corrected replacement for {orig_num}: {reason.strip()}"
            eff_ref = transaction_reference if transaction_reference is not None else orig_inv["transaction_reference"]

            new_id, new_num = SalesRepository._execute_sale_in_cursor(
                cursor=cursor,
                items=new_items,
                payment_mode=eff_pay_mode,
                customer_id=eff_cust_id,
                occurrence_id=eff_occ_id,
                overall_discount=overall_discount,
                transaction_reference=eff_ref,
                notes=eff_notes,
                sale_date=eff_date,
                is_correction=True
            )

            # Link new invoice number in original invoice's notes
            final_cancel_note = (orig_inv["notes"] or "") + f" [Cancelled & replaced by {new_num}: {reason.strip()}]"
            cursor.execute(
                "UPDATE sales_invoices SET notes = ? WHERE invoice_id = ?",
                (final_cancel_note.strip(), original_invoice_id)
            )

            return new_id, new_num

    @staticmethod
    def create_invoice_with_items_atomic(
        invoice_header: Dict[str, Any],
        line_items: List[Dict[str, Any]],
        batch_deductions: List[Tuple[int, int]],
        customer_credit_delta: float = 0.0
    ) -> Tuple[int, str]:
        """
        Legacy compatible method wrapping the transaction execution.
        """
        sql_header = """
            INSERT INTO sales_invoices (
                invoice_number, invoice_date, customer_id, occurrence_id,
                payment_mode, subtotal_amount, discount_amount, total_taxable_amount,
                cgst_amount, sgst_amount, igst_amount, roundoff_amount,
                net_total_amount, is_interstate, status, transaction_reference, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'COMPLETED', ?, ?)
        """
        header_params = (
            invoice_header["invoice_number"],
            invoice_header["invoice_date"],
            invoice_header.get("customer_id"),
            invoice_header.get("occurrence_id"),
            invoice_header["payment_mode"],
            float(invoice_header["subtotal_amount"]),
            float(invoice_header.get("discount_amount", 0.0)),
            float(invoice_header["total_taxable_amount"]),
            float(invoice_header.get("cgst_amount", 0.0)),
            float(invoice_header.get("sgst_amount", 0.0)),
            float(invoice_header.get("igst_amount", 0.0)),
            float(invoice_header.get("roundoff_amount", 0.0)),
            float(invoice_header["net_total_amount"]),
            1 if invoice_header.get("is_interstate") else 0,
            invoice_header.get("transaction_reference"),
            invoice_header.get("notes")
        )

        sql_item = """
            INSERT INTO sales_items (
                invoice_id, product_id, batch_id, quantity, unit_cost_price,
                unit_selling_price, discount_percent, taxable_value, gst_rate,
                cgst_rate, cgst_amount, sgst_rate, sgst_amount, igst_rate, igst_amount,
                total_item_amount, gross_profit
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute(sql_header, header_params)
            invoice_id = cursor.lastrowid

            for item in line_items:
                cursor.execute(sql_item, (
                    invoice_id,
                    item["product_id"],
                    item.get("batch_id"),
                    int(item["quantity"]),
                    float(item["unit_cost_price"]),
                    float(item["unit_selling_price"]),
                    float(item.get("discount_percent", 0.0)),
                    float(item["taxable_value"]),
                    float(item["gst_rate"]),
                    float(item.get("cgst_rate", 0.0)),
                    float(item.get("cgst_amount", 0.0)),
                    float(item.get("sgst_rate", 0.0)),
                    float(item.get("sgst_amount", 0.0)),
                    float(item.get("igst_rate", 0.0)),
                    float(item.get("igst_amount", 0.0)),
                    float(item["total_item_amount"]),
                    float(item["gross_profit"])
                ))

            for b_id, qty in batch_deductions:
                cursor.execute(
                    "UPDATE inventory_batches SET quantity_available = quantity_available - ? WHERE batch_id = ?",
                    (qty, b_id)
                )
                cursor.execute("SELECT product_id, unit_cost FROM inventory_batches WHERE batch_id = ?", (b_id,))
                b_info = cursor.fetchone()
                p_id = b_info["product_id"] if b_info else None
                u_cost = float(b_info["unit_cost"]) if b_info else 0.0
                if p_id:
                    cursor.execute("""
                        INSERT INTO stock_movements (
                            product_id, batch_id, movement_type, quantity, unit_cost,
                            total_cost_impact, reference_type, reference_id, reason
                        ) VALUES (?, ?, 'SALE', ?, ?, ?, 'SALES_INVOICE', ?, ?)
                    """, (
                        p_id, b_id, -int(qty), u_cost, round(qty * u_cost, 2),
                        invoice_header["invoice_number"],
                        f"POS Sale via Invoice {invoice_header['invoice_number']}"
                    ))

            if customer_credit_delta > 0 and invoice_header.get("customer_id"):
                cursor.execute(
                    "UPDATE customers SET outstanding_credit = outstanding_credit + ? WHERE customer_id = ?",
                    (customer_credit_delta, invoice_header["customer_id"])
                )

            return invoice_id, invoice_header["invoice_number"]

    @staticmethod
    def cancel_invoice_atomic(
        invoice_id: int,
        batch_restorations: Optional[List[Tuple[int, int]]] = None,
        khata_reversal: Optional[float] = None,
        customer_id: Optional[int] = None,
        reason: str = "Customer Order Cancellation"
    ) -> bool:
        """
        Executes a safe cancellation reversal workflow:
        - Sets invoice status to 'CANCELLED'.
        - Restores deducted stock to batches.
        - Records SALE_CANCEL (+qty) in stock_movements.
        - Reverses customer Khata credit if applicable.
        - Preserves complete audit history without deleting rows.
        """
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sales_invoices WHERE invoice_id = ?", (invoice_id,))
            inv = cursor.fetchone()
            if not inv:
                raise ValueError(f"Invoice ID {invoice_id} not found.")

            if inv["status"] == "CANCELLED":
                raise ValueError(f"Invoice {inv['invoice_number']} is already cancelled.")

            # If restorations not passed, dynamically inspect line items
            if batch_restorations is None:
                cursor.execute("SELECT batch_id, quantity, product_id, unit_cost_price FROM sales_items WHERE invoice_id = ?", (invoice_id,))
                items = cursor.fetchall()
                batch_restorations = [(it["batch_id"], it["quantity"]) for it in items if it["batch_id"]]

            # Restore batches and log reverse stock movements
            for b_id, qty in batch_restorations:
                cursor.execute(
                    "UPDATE inventory_batches SET quantity_available = quantity_available + ? WHERE batch_id = ?",
                    (qty, b_id)
                )
                cursor.execute("SELECT product_id, unit_cost FROM inventory_batches WHERE batch_id = ?", (b_id,))
                b_info = cursor.fetchone()
                p_id = b_info["product_id"] if b_info else None
                u_cost = float(b_info["unit_cost"]) if b_info else 0.0
                if p_id:
                    cursor.execute("""
                        INSERT INTO stock_movements (
                            product_id, batch_id, movement_type, quantity, unit_cost,
                            total_cost_impact, reference_type, reference_id, reason
                        ) VALUES (?, ?, 'SALE_CANCEL', ?, ?, ?, 'INVOICE_CANCEL', ?, ?)
                    """, (
                        p_id, b_id, int(qty), u_cost, round(qty * u_cost, 2),
                        inv["invoice_number"],
                        f"Reversal of cancelled Invoice {inv['invoice_number']}: {reason}"
                    ))

            # Reverse Khata credit
            target_cust_id = customer_id or inv["customer_id"]
            if inv["payment_mode"] == "CREDIT_KHATA" and target_cust_id:
                rev_amt = khata_reversal if khata_reversal is not None else float(inv["net_total_amount"])
                cursor.execute(
                    "UPDATE customers SET outstanding_credit = MAX(0.0, outstanding_credit - ?) WHERE customer_id = ?",
                    (rev_amt, target_cust_id)
                )

            # Mark cancelled
            cursor.execute("UPDATE sales_invoices SET status = 'CANCELLED' WHERE invoice_id = ?", (invoice_id,))
            return True

    @staticmethod
    def process_sales_return_atomic(
        invoice_id: int,
        returned_items: List[Dict[str, Any]],  # [{"item_id": int, "quantity": int, "reason": str, "restock": bool}]
        return_date: Optional[str] = None
    ) -> Tuple[int, str, float]:
        """
        Processes item-level sales returns with prorated Decimal refunds and stock adjustments:
        - Validates return quantity against sold quantity and past returns.
        - Restocks undamaged goods to inventory and records SALE_CANCEL movement in ledger.
        - Records damaged returned goods as DAMAGE movement in ledger.
        - Decrements customer Khata balance if credit sale.
        - Inserts records into sales_returns.
        - Updates invoice status to 'RETURNED' or 'PARTIALLY_RETURNED'.
        """
        if not returned_items:
            raise InvalidReturnError("Must specify at least one item to return.")

        if not return_date:
            return_date = date.today().strftime("%Y-%m-%d")

        return_number = SalesRepository.generate_return_number()

        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sales_invoices WHERE invoice_id = ?", (invoice_id,))
            inv = cursor.fetchone()
            if not inv:
                raise ValueError(f"Invoice ID {invoice_id} not found.")

            if inv["status"] == "CANCELLED":
                raise InvalidReturnError(f"Cannot process return: Invoice {inv['invoice_number']} is cancelled.")

            total_refund_dec = ZERO
            total_items_in_inv = 0
            total_items_returned_so_far = 0

            for ret_req in returned_items:
                item_id = int(ret_req["item_id"])
                ret_qty = int(ret_req["quantity"])
                reason = ret_req.get("reason", "Customer Return / Exchange").strip()
                should_restock = bool(ret_req.get("restock", True))

                if ret_qty <= 0:
                    raise InvalidReturnError("Return quantity must be greater than zero.")

                # Fetch original sale item
                cursor.execute("SELECT * FROM sales_items WHERE item_id = ? AND invoice_id = ?", (item_id, invoice_id))
                item_row = cursor.fetchone()
                if not item_row:
                    raise InvalidReturnError(f"Line item ID {item_id} not found in invoice {inv['invoice_number']}.")

                sold_qty = item_row["quantity"]
                prod_id = item_row["product_id"]
                batch_id = item_row["batch_id"]

                # Check previous returns for this item
                cursor.execute("SELECT COALESCE(SUM(quantity), 0) AS previously_returned FROM sales_returns WHERE item_id = ?", (item_id,))
                prev_ret = cursor.fetchone()["previously_returned"]

                if prev_ret + ret_qty > sold_qty:
                    raise InvalidReturnError(
                        f"Cannot return {ret_qty} units of item ID {item_id}. "
                        f"Sold: {sold_qty}, Previously Returned: {prev_ret}, Maximum Returnable: {sold_qty - prev_ret}."
                    )

                # Calculate prorated refund amount using Decimal
                total_item_amt = to_decimal(item_row["total_item_amount"])
                unit_refund = (total_item_amt / Decimal(sold_qty)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
                line_refund = (unit_refund * Decimal(ret_qty)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
                total_refund_dec += line_refund

                # Record return entry
                cursor.execute("""
                    INSERT INTO sales_returns (
                        return_number, invoice_id, item_id, product_id, batch_id,
                        return_date, quantity, refund_amount, tax_refund_amount,
                        reason, restock_to_inventory
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0.0, ?, ?)
                """, (
                    return_number,
                    invoice_id,
                    item_id,
                    prod_id,
                    batch_id,
                    return_date,
                    ret_qty,
                    float(line_refund),
                    reason,
                    1 if should_restock else 0
                ))
                return_record_id = cursor.lastrowid

                # Handle stock movement
                u_cost = float(item_row["unit_cost_price"])
                if should_restock and batch_id:
                    cursor.execute(
                        "UPDATE inventory_batches SET quantity_available = quantity_available + ? WHERE batch_id = ?",
                        (ret_qty, batch_id)
                    )
                    cursor.execute("""
                        INSERT INTO stock_movements (
                            product_id, batch_id, movement_type, quantity, unit_cost,
                            total_cost_impact, reference_type, reference_id, reason, created_at
                        ) VALUES (?, ?, 'SALE_CANCEL', ?, ?, ?, 'SALES_RETURN', ?, ?, ?)
                    """, (
                        prod_id,
                        batch_id,
                        ret_qty,
                        u_cost,
                        round(ret_qty * u_cost, 2),
                        return_number,
                        f"Restock from Sales Return {return_number}: {reason}",
                        f"{return_date} {datetime.now().strftime('%H:%M:%S')}"
                    ))
                elif not should_restock and batch_id:
                    # Defective or expired return: record damage
                    cursor.execute("""
                        INSERT INTO stock_movements (
                            product_id, batch_id, movement_type, quantity, unit_cost,
                            total_cost_impact, reference_type, reference_id, reason, created_at
                        ) VALUES (?, ?, 'DAMAGE', 0, ?, ?, 'SALES_RETURN', ?, ?, ?)
                    """, (
                        prod_id,
                        batch_id,
                        u_cost,
                        round(ret_qty * u_cost, 2),
                        return_number,
                        f"Damaged customer return write-off {return_number}: {reason}",
                        f"{return_date} {datetime.now().strftime('%H:%M:%S')}"
                    ))

            # Reverse customer Khata balance if credit
            float_total_refund = float(total_refund_dec)
            if inv["payment_mode"] == "CREDIT_KHATA" and inv["customer_id"]:
                cursor.execute(
                    "UPDATE customers SET outstanding_credit = MAX(0.0, outstanding_credit - ?) WHERE customer_id = ?",
                    (float_total_refund, inv["customer_id"])
                )

            # Determine whether invoice is fully or partially returned
            cursor.execute("SELECT SUM(quantity) AS total_sold FROM sales_items WHERE invoice_id = ?", (invoice_id,))
            total_sold = cursor.fetchone()["total_sold"] or 0

            cursor.execute("SELECT SUM(quantity) AS total_ret FROM sales_returns WHERE invoice_id = ?", (invoice_id,))
            total_ret = cursor.fetchone()["total_ret"] or 0

            new_status = "RETURNED" if total_ret >= total_sold else "PARTIALLY_RETURNED"
            cursor.execute("UPDATE sales_invoices SET status = ? WHERE invoice_id = ?", (new_status, invoice_id))

            return return_record_id, return_number, float_total_refund

    @staticmethod
    def get_invoice_by_id(invoice_id: int) -> Optional[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT inv.*, cust.customer_name, cust.phone AS customer_phone, cust.gstin AS customer_gstin,
                       cust.address AS customer_address, cust.city AS customer_city, cust.state AS customer_state,
                       f.festival_name
                FROM sales_invoices inv
                LEFT JOIN customers cust ON inv.customer_id = cust.customer_id
                LEFT JOIN festival_occurrences occ ON inv.occurrence_id = occ.occurrence_id
                LEFT JOIN festivals f ON occ.festival_id = f.festival_id
                WHERE inv.invoice_id = ?
            """, (invoice_id,))
            row = cursor.fetchone()
            if not row:
                return None

            inv_dict = dict(row)
            cursor.execute("""
                SELECT si.*, p.product_name, p.sku, p.unit_of_measure, p.hsn_code, b.batch_number
                FROM sales_items si
                JOIN products p ON si.product_id = p.product_id
                LEFT JOIN inventory_batches b ON si.batch_id = b.batch_id
                WHERE si.invoice_id = ?
                ORDER BY si.item_id ASC
            """, (invoice_id,))
            inv_dict["items"] = [dict(r) for r in cursor.fetchall()]

            cursor.execute("""
                SELECT sr.*, p.product_name, p.sku
                FROM sales_returns sr
                JOIN products p ON sr.product_id = p.product_id
                WHERE sr.invoice_id = ?
                ORDER BY sr.return_id ASC
            """, (invoice_id,))
            inv_dict["returns"] = [dict(r) for r in cursor.fetchall()]

            return inv_dict
        finally:
            conn.close()

    @staticmethod
    def get_invoice_by_number(invoice_number: str) -> Optional[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT invoice_id FROM sales_invoices WHERE invoice_number = ?", (invoice_number.strip(),))
            row = cursor.fetchone()
            if not row:
                return None
            return SalesRepository.get_invoice_by_id(row["invoice_id"])
        finally:
            conn.close()

    @staticmethod
    def get_invoices(
        occurrence_id: Optional[int] = None,
        customer_id: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        payment_mode: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            sql = """
                SELECT inv.*, COALESCE(cust.customer_name, 'Cash / Walk-in') AS customer_name,
                       cust.phone AS customer_phone
                FROM sales_invoices inv
                LEFT JOIN customers cust ON inv.customer_id = cust.customer_id
                WHERE 1=1
            """
            params: List[Any] = []
            if occurrence_id:
                sql += " AND inv.occurrence_id = ?"
                params.append(occurrence_id)
            if customer_id:
                sql += " AND inv.customer_id = ?"
                params.append(customer_id)
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
                sql += """ AND (
                    inv.invoice_number LIKE ?
                    OR inv.transaction_reference LIKE ?
                    OR cust.customer_name LIKE ?
                    OR cust.phone LIKE ?
                    OR inv.invoice_id IN (
                        SELECT si.invoice_id FROM sales_items si
                        JOIN products p ON si.product_id = p.product_id
                        WHERE p.product_name LIKE ? OR p.sku LIKE ?
                    )
                )"""
                params.extend([term, term, term, term, term, term])

            sql += " ORDER BY inv.invoice_date DESC, inv.invoice_id DESC LIMIT ?"
            params.append(limit)

            cursor.execute(sql, tuple(params))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def get_sales_returns(invoice_id: Optional[int] = None, limit: int = 50) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            sql = """
                SELECT sr.*, inv.invoice_number, p.product_name, p.sku
                FROM sales_returns sr
                JOIN sales_invoices inv ON sr.invoice_id = inv.invoice_id
                JOIN products p ON sr.product_id = p.product_id
                WHERE 1=1
            """
            params: List[Any] = []
            if invoice_id:
                sql += " AND sr.invoice_id = ?"
                params.append(invoice_id)

            sql += " ORDER BY sr.return_id DESC LIMIT ?"
            params.append(limit)

            cursor.execute(sql, tuple(params))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def get_all_customers() -> List[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM customers ORDER BY customer_name ASC")
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def get_customer_by_id(customer_id: int) -> Optional[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM customers WHERE customer_id = ?", (customer_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def create_customer(
        name: str,
        phone: str,
        email: Optional[str] = None,
        gstin: Optional[str] = None,
        address: Optional[str] = None,
        city: Optional[str] = None,
        state: Optional[str] = None,
        credit_limit: float = 5000.0
    ) -> int:
        sql = """
            INSERT INTO customers (
                customer_name, phone, email, gstin, address, city, state, outstanding_credit, credit_limit
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 0.0, ?)
        """
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (name.strip(), phone.strip(), email, gstin, address, city, state, credit_limit))
            return cursor.lastrowid
