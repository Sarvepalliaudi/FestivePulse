"""
FestivePulse — Currency & Number Formatting Utilities
Strict adherence to the Indian Numbering System (Lakhs & Crores).
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Union, Dict, Any

TWO_PLACES = Decimal('0.01')
PAISE_FACTOR = Decimal('100')


def format_inr(amount: Union[int, float], show_symbol: bool = True, show_decimals: bool = True) -> str:
    """
    Formats a numeric amount into Indian currency format:
    e.g.
    1000 -> ₹1,000.00
    150000 -> ₹1,50,000.00
    12500000 -> ₹1,25,00,000.00
    """
    if amount is None:
        return "₹0.00" if show_symbol else "0.00"

    try:
        val = float(amount)
    except (ValueError, TypeError):
        return "₹0.00" if show_symbol else "0.00"

    is_negative = val < 0
    val = abs(val)

    if show_decimals:
        formatted_dec = f"{val:.2f}"
        parts = formatted_dec.split(".")
        integer_part = parts[0]
        decimal_part = "." + parts[1]
    else:
        integer_part = str(int(round(val)))
        decimal_part = ""

    # Indian numbering: last 3 digits, then groups of 2
    if len(integer_part) <= 3:
        formatted_int = integer_part
    else:
        last3 = integer_part[-3:]
        remaining = integer_part[:-3]
        # Group remaining digits in pairs from right to left
        groups = []
        while len(remaining) > 2:
            groups.insert(0, remaining[-2:])
            remaining = remaining[:-2]
        if remaining:
            groups.insert(0, remaining)
        formatted_int = ",".join(groups) + "," + last3

    result = f"{formatted_int}{decimal_part}"
    if show_symbol:
        result = "₹" + result
    if is_negative:
        result = "-" + result

    return result


def format_compact_inr(amount: Union[int, float], show_symbol: bool = True) -> str:
    """
    Formats large numbers into compact Indian denominations:
    e.g.
    1500 -> ₹1.5 K
    250000 -> ₹2.50 L
    15000000 -> ₹1.50 Cr
    """
    if amount is None:
        return "₹0" if show_symbol else "0"

    try:
        val = float(amount)
    except (ValueError, TypeError):
        return "₹0" if show_symbol else "0"

    prefix = "₹" if show_symbol else ""
    sign = "-" if val < 0 else ""
    val = abs(val)

    if val >= 10000000:  # 1 Crore = 10,000,000
        return f"{sign}{prefix}{val / 10000000:.2f} Cr"
    elif val >= 100000:  # 1 Lakh = 100,000
        return f"{sign}{prefix}{val / 100000:.2f} L"
    elif val >= 1000:   # 1 Thousand
        return f"{sign}{prefix}{val / 1000:.1f} K"
    else:
        return f"{sign}{prefix}{val:.2f}"


def number_to_words_inr(amount: Union[int, float]) -> str:
    """
    Converts numeric amount to Indian Rupee Words for official tax invoices.
    e.g. 150250.50 -> "Rupees One Lakh Fifty Thousand Two Hundred Fifty and Fifty Paise Only"
    """
    if amount is None or amount == 0:
        return "Rupees Zero Only"

    val = round(float(amount), 2)
    integer_part = int(val)
    paise_part = int(round((val - integer_part) * 100))

    units = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
             "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
             "Seventeen", "Eighteen", "Nineteen"]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]

    def convert_below_thousand(n: int) -> str:
        res = []
        if n >= 100:
            res.append(units[n // 100] + " Hundred")
            n %= 100
        if n >= 20:
            res.append(tens[n // 10])
            n %= 10
        if n > 0:
            res.append(units[n])
        return " ".join(res)

    words = []
    # Crores (10,000,000)
    crores = integer_part // 10000000
    integer_part %= 10000000
    if crores > 0:
        words.append(convert_below_thousand(crores) + " Crore")

    # Lakhs (100,000)
    lakhs = integer_part // 100000
    integer_part %= 100000
    if lakhs > 0:
        words.append(convert_below_thousand(lakhs) + " Lakh")

    # Thousands (1,000)
    thousands = integer_part // 1000
    integer_part %= 1000
    if thousands > 0:
        words.append(convert_below_thousand(thousands) + " Thousand")

    # Remaining hundreds, tens, and units
    if integer_part > 0:
        words.append(convert_below_thousand(integer_part))

    result = "Rupees " + " ".join(words)
    if paise_part > 0:
        result += f" and {convert_below_thousand(paise_part)} Paise"
    result += " Only"

    return result


def rupees_to_paise(amount: Union[Decimal, float, int, str, None]) -> int:
    """
    Converts a Rupee monetary value into exact integer paise:
    e.g.
    Decimal('10.50') -> 1050
    10.555 -> 1056 (using standard ROUND_HALF_UP)
    """
    if amount is None:
        return 0
    if isinstance(amount, int):
        return amount * 100
    if isinstance(amount, Decimal):
        dec = amount
    else:
        dec = Decimal(str(amount))
    return int((dec * PAISE_FACTOR).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def paise_to_rupees(paise: Union[int, Decimal, float, str, None]) -> Decimal:
    """
    Converts integer paise into Decimal rupees with 2 decimal places:
    e.g. 1050 -> Decimal('10.50')
    """
    if paise is None:
        return Decimal('0.00')
    if isinstance(paise, Decimal):
        p_dec = paise
    else:
        p_dec = Decimal(str(int(paise)))
    return (p_dec / PAISE_FACTOR).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def calculate_monetary_line(
    quantity: int,
    unit_price: Union[Decimal, float, str],
    discount_pct: Union[Decimal, float, str] = 0,
    discount_amount: Union[Decimal, float, str] = 0,
    gst_rate: Union[Decimal, float, str] = 0,
    is_interstate: bool = False
) -> Dict[str, Any]:
    """
    Calculates exact line item totals using both Decimal and integer paise representation:
    - Gross = quantity * unit_price
    - Discount = percentage or fixed amount
    - Taxable = Gross - Discount
    - GST = CGST + SGST (intra) or IGST (inter)
    - Line Total = Taxable + GST
    Returns a dict with Decimal values, float equivalents, and integer paise equivalents.
    """
    qty_int = int(quantity)
    price_dec = Decimal(str(unit_price)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    gst_dec = Decimal(str(gst_rate)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

    gross_dec = (Decimal(qty_int) * price_dec).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

    # Calculate discount: flat amount takes precedence if provided and > 0, else percentage
    disc_amt_dec = Decimal(str(discount_amount or 0)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    disc_pct_dec = Decimal(str(discount_pct or 0)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

    if disc_amt_dec > Decimal('0.00'):
        disc_dec = min(gross_dec, disc_amt_dec)
        effective_pct = ((disc_dec / gross_dec) * Decimal('100.00')).quantize(TWO_PLACES, rounding=ROUND_HALF_UP) if gross_dec > Decimal('0.00') else Decimal('0.00')
    elif disc_pct_dec > Decimal('0.00'):
        effective_pct = min(Decimal('100.00'), disc_pct_dec)
        disc_dec = (gross_dec * (effective_pct / Decimal('100.00'))).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    else:
        disc_dec = Decimal('0.00')
        effective_pct = Decimal('0.00')

    taxable_dec = max(Decimal('0.00'), gross_dec - disc_dec)

    if is_interstate:
        cgst_rate = Decimal('0.00')
        sgst_rate = Decimal('0.00')
        igst_rate = gst_dec
        cgst_dec = Decimal('0.00')
        sgst_dec = Decimal('0.00')
        igst_dec = (taxable_dec * (gst_dec / Decimal('100.00'))).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    else:
        half_rate = (gst_dec / Decimal('2.0')).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        cgst_rate = half_rate
        sgst_rate = half_rate
        igst_rate = Decimal('0.00')
        cgst_dec = (taxable_dec * (half_rate / Decimal('100.00'))).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        sgst_dec = (taxable_dec * (half_rate / Decimal('100.00'))).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        igst_dec = Decimal('0.00')

    tax_total_dec = cgst_dec + sgst_dec + igst_dec
    line_total_dec = taxable_dec + tax_total_dec

    return {
        "quantity": qty_int,
        "unit_price": price_dec,
        "gross_amount": gross_dec,
        "discount_percent": effective_pct,
        "discount_amount": disc_dec,
        "taxable_amount": taxable_dec,
        "gst_rate": gst_dec,
        "cgst_rate": cgst_rate,
        "cgst_amount": cgst_dec,
        "sgst_rate": sgst_rate,
        "sgst_amount": sgst_dec,
        "igst_rate": igst_rate,
        "igst_amount": igst_dec,
        "tax_total": tax_total_dec,
        "line_total": line_total_dec,
        # Integer paise values for exact accounting ledger reconciliation
        "paise": {
            "unit_price": rupees_to_paise(price_dec),
            "gross_amount": rupees_to_paise(gross_dec),
            "discount_amount": rupees_to_paise(disc_dec),
            "taxable_amount": rupees_to_paise(taxable_dec),
            "cgst_amount": rupees_to_paise(cgst_dec),
            "sgst_amount": rupees_to_paise(sgst_dec),
            "igst_amount": rupees_to_paise(igst_dec),
            "tax_total": rupees_to_paise(tax_total_dec),
            "line_total": rupees_to_paise(line_total_dec),
        }
    }
