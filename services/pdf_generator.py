"""
FestivePulse — Professional PDF Invoice & Report Generator using ReportLab
Produces GST-compliant tax invoices, cash receipts, and purchase orders.
"""

from pathlib import Path
from typing import Optional
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT

from config import REPORTS_DIR
from services.currency_utils import format_inr, number_to_words_inr
from services.sales_service import get_invoice_full_details
from database.queries import get_business_settings


def generate_invoice_pdf(invoice_id: int, output_path: Optional[Path] = None) -> Path:
    """
    Generates a high-quality GST-compliant Tax Invoice PDF.
    """
    inv = get_invoice_full_details(invoice_id)
    settings = get_business_settings()

    if output_path is None:
        filename = f"Invoice_{inv['invoice_number'].replace('-', '_')}.pdf"
        output_path = REPORTS_DIR / filename

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=12 * mm,
        leftMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm
    )

    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        "StoreTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=16,
        textColor=colors.HexColor("#B45309"),  # Rich festive marigold/gold
        alignment=TA_CENTER
    )
    subtitle_style = ParagraphStyle(
        "StoreSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=11,
        alignment=TA_CENTER
    )
    tax_inv_badge = ParagraphStyle(
        "TaxInvBadge",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=12,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#1E293B")
    )
    cell_style = ParagraphStyle(
        "CellNormal",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=10
    )
    cell_bold = ParagraphStyle(
        "CellBold",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10
    )
    cell_right = ParagraphStyle(
        "CellRight",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=10,
        alignment=TA_RIGHT
    )
    cell_right_bold = ParagraphStyle(
        "CellRightBold",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        alignment=TA_RIGHT
    )

    story = []

    # 1. Header Box: Store Info
    b_name = settings.get("business_name", "FestivePulse Store")
    t_name = settings.get("trade_name", "")
    addr = f"{settings.get('address_line1', '')}, {settings.get('city', '')}, {settings.get('state', '')} - {settings.get('pincode', '')}"
    phone = f"Phone: {settings.get('phone', '')} | Email: {settings.get('email', '')}"
    gstin = f"GSTIN: {settings.get('gstin', 'UNREGISTERED')}"

    story.append(Paragraph(b_name.upper(), title_style))
    if t_name:
        story.append(Paragraph(f"({t_name})", subtitle_style))
    story.append(Paragraph(addr, subtitle_style))
    story.append(Paragraph(phone, subtitle_style))
    story.append(Paragraph(f"<b>{gstin}</b> | State: {settings.get('state', '')} (Code: {settings.get('state_code', '')})", subtitle_style))
    story.append(Spacer(1, 4 * mm))

    # Badge
    story.append(Paragraph("TAX INVOICE / CASH MEMO", tax_inv_badge))
    story.append(Spacer(1, 3 * mm))

    # 2. Invoice & Customer Meta Grid
    is_interstate = bool(inv.get("is_interstate", 0))
    inv_type = "Inter-State Sale (IGST)" if is_interstate else "Intra-State Sale (CGST + SGST)"

    cust_name = inv.get("customer_name") or "Cash / Walk-in Customer"
    cust_phone = inv.get("customer_phone") or "N/A"
    cust_gstin = inv.get("customer_gstin") or "Unregistered"

    meta_data = [
        [
            Paragraph(f"<b>Invoice No:</b> {inv['invoice_number']}", cell_style),
            Paragraph(f"<b>Billed To:</b> {cust_name}", cell_style)
        ],
        [
            Paragraph(f"<b>Date:</b> {inv['invoice_date']}", cell_style),
            Paragraph(f"<b>Contact:</b> {cust_phone}", cell_style)
        ],
        [
            Paragraph(f"<b>Payment Mode:</b> {inv['payment_mode']}", cell_style),
            Paragraph(f"<b>Customer GSTIN:</b> {cust_gstin}", cell_style)
        ],
        [
            Paragraph(f"<b>Supply Type:</b> {inv_type}", cell_style),
            Paragraph(f"<b>Festival:</b> {inv.get('festival_name') or 'Regular Sale'}", cell_style)
        ]
    ]

    meta_table = Table(meta_data, colWidths=[90 * mm, 96 * mm])
    meta_table.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#F1F5F9")),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 4 * mm))

    # 3. Line Items Table
    headers = [
        Paragraph("<b>#</b>", cell_bold),
        Paragraph("<b>Item Description</b>", cell_bold),
        Paragraph("<b>HSN</b>", cell_bold),
        Paragraph("<b>Qty</b>", cell_right_bold),
        Paragraph("<b>Rate</b>", cell_right_bold),
        Paragraph("<b>Disc%</b>", cell_right_bold),
        Paragraph("<b>Taxable</b>", cell_right_bold),
        Paragraph("<b>GST%</b>", cell_right_bold),
        Paragraph("<b>Tax (₹)</b>", cell_right_bold),
        Paragraph("<b>Total (₹)</b>", cell_right_bold)
    ]
    items_rows = [headers]

    for idx, item in enumerate(inv["items"], start=1):
        line_tax = item["cgst_amount"] + item["sgst_amount"] + item["igst_amount"]
        desc = item["product_name"]
        if item.get("batch_number"):
            desc += f"<br/><font color='#64748B' size=6>Batch: {item['batch_number']}</font>"

        row = [
            Paragraph(str(idx), cell_style),
            Paragraph(desc, cell_style),
            Paragraph(str(item.get("hsn_code") or "-"), cell_style),
            Paragraph(f"{item['quantity']} {item.get('unit_of_measure', '')}", cell_right),
            Paragraph(f"{item['unit_selling_price']:.2f}", cell_right),
            Paragraph(f"{item.get('discount_percent', 0.0):.1f}%", cell_right),
            Paragraph(f"{item['taxable_value']:.2f}", cell_right),
            Paragraph(f"{item['gst_rate']:.1f}%", cell_right),
            Paragraph(f"{line_tax:.2f}", cell_right),
            Paragraph(f"{item['total_item_amount']:.2f}", cell_right_bold)
        ]
        items_rows.append(row)

    col_widths = [8 * mm, 50 * mm, 16 * mm, 15 * mm, 16 * mm, 12 * mm, 18 * mm, 13 * mm, 18 * mm, 20 * mm]
    items_table = Table(items_rows, colWidths=col_widths, repeatRows=1)
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#FEF3C7")),  # Soft festive gold
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('VALIGN', (0, 0), (-1, -1), 'TOP')
    ]))
    story.append(items_table)
    story.append(Spacer(1, 3 * mm))

    # 4. Summary & Tax Details
    tot_cgst = inv.get("cgst_amount", 0.0)
    tot_sgst = inv.get("sgst_amount", 0.0)
    tot_igst = inv.get("igst_amount", 0.0)
    roundoff = inv.get("roundoff_amount", 0.0)
    net_total = inv["net_total_amount"]

    summary_rows = [
        [Paragraph("Subtotal Gross:", cell_style), Paragraph(f"₹ {inv['subtotal_amount']:.2f}", cell_right)],
        [Paragraph("Trade Discount:", cell_style), Paragraph(f"- ₹ {inv.get('discount_amount', 0.0):.2f}", cell_right)],
        [Paragraph("Total Taxable Value:", cell_bold), Paragraph(f"₹ {inv['total_taxable_amount']:.2f}", cell_right_bold)],
    ]
    if not is_interstate:
        summary_rows.append([Paragraph("Central GST (CGST):", cell_style), Paragraph(f"₹ {tot_cgst:.2f}", cell_right)])
        summary_rows.append([Paragraph("State GST (SGST):", cell_style), Paragraph(f"₹ {tot_sgst:.2f}", cell_right)])
    else:
        summary_rows.append([Paragraph("Integrated GST (IGST):", cell_style), Paragraph(f"₹ {tot_igst:.2f}", cell_right)])

    if roundoff != 0.0:
        summary_rows.append([Paragraph("Round Off:", cell_style), Paragraph(f"₹ {roundoff:+.2f}", cell_right)])

    summary_rows.append([
        Paragraph("<b>NET INVOICE TOTAL:</b>", cell_bold),
        Paragraph(f"<b>{format_inr(net_total)}</b>", cell_right_bold)
    ])

    words_inr = number_to_words_inr(net_total)
    words_cell = Paragraph(f"<b>Amount in Words:</b><br/>{words_inr}", cell_style)

    combined_table_data = [
        [words_cell, Table(summary_rows, colWidths=[40 * mm, 40 * mm])]
    ]
    comb_table = Table(combined_table_data, colWidths=[106 * mm, 80 * mm])
    comb_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(comb_table)
    story.append(Spacer(1, 8 * mm))

    # 5. Signatory & Terms
    footer_data = [
        [
            Paragraph("<b>Terms & Conditions:</b><br/>"
                      "1. Goods once sold can only be exchanged within 7 days with invoice.<br/>"
                      "2. For perishable sweets, please store in refrigeration.<br/>"
                      "3. Subject to local city jurisdiction.", cell_style),
            Paragraph(f"For <b>{b_name}</b><br/><br/><br/><b>Authorised Signatory</b>", cell_right)
        ]
    ]
    foot_table = Table(footer_data, colWidths=[110 * mm, 76 * mm])
    foot_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM')
    ]))
    story.append(KeepTogether(foot_table))

    doc.build(story)
    return output_path


def generate_procurement_po_pdf(occurrence_id: int, output_path: Optional[Path] = None) -> Path:
    """
    Generates a formal Festival Stock Procurement Worksheet / Purchase Requisition PDF.
    """
    from services.stock_recommender import generate_festival_procurement_worksheet
    from database.queries import get_all_festival_occurrences

    settings = get_business_settings()
    df_recs = generate_festival_procurement_worksheet(occurrence_id, only_order_required=True)

    # Get festival occurrence title
    all_occ = get_all_festival_occurrences()
    occ_match = all_occ[all_occ["occurrence_id"] == occurrence_id]
    fest_title = occ_match.iloc[0]["festival_name"] if not occ_match.empty else "Festival Campaign"
    fest_year = occ_match.iloc[0]["year"] if not occ_match.empty else ""

    if output_path is None:
        filename = f"Procurement_PO_Festival_{occurrence_id}.pdf"
        output_path = REPORTS_DIR / filename

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=12 * mm,
        leftMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "PoTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=16,
        textColor=colors.HexColor("#B45309"),
        alignment=TA_CENTER
    )
    subtitle_style = ParagraphStyle(
        "PoSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        alignment=TA_CENTER
    )
    cell_style = ParagraphStyle(
        "CellNormal",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=10
    )
    cell_bold = ParagraphStyle(
        "CellBold",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10
    )
    cell_right = ParagraphStyle(
        "CellRight",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=10,
        alignment=TA_RIGHT
    )
    cell_right_bold = ParagraphStyle(
        "CellRightBold",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        alignment=TA_RIGHT
    )

    story = []

    b_name = settings.get("business_name", "FestivePulse Store")
    story.append(Paragraph(b_name.upper(), title_style))
    story.append(Paragraph(f"FESTIVAL PROCUREMENT REQUISITION & REORDER SHEET", subtitle_style))
    story.append(Paragraph(f"Target Campaign: <b>{fest_title} {fest_year}</b>", subtitle_style))
    story.append(Spacer(1, 4 * mm))

    headers = [
        Paragraph("<b>#</b>", cell_bold),
        Paragraph("<b>Product & SKU</b>", cell_bold),
        Paragraph("<b>Supplier</b>", cell_bold),
        Paragraph("<b>Stock</b>", cell_right_bold),
        Paragraph("<b>Fest Demand</b>", cell_right_bold),
        Paragraph("<b>Safety Stk</b>", cell_right_bold),
        Paragraph("<b>Order Qty</b>", cell_right_bold),
        Paragraph("<b>Est Rate</b>", cell_right_bold),
        Paragraph("<b>Est Cost (₹)</b>", cell_right_bold)
    ]
    table_rows = [headers]

    total_est_cost = 0.0
    total_units_to_order = 0

    if not df_recs.empty:
        for idx, r in df_recs.iterrows():
            item_cost = float(r["estimated_procurement_cost"])
            order_qty = int(r["recommended_order_quantity"])
            total_est_cost += item_cost
            total_units_to_order += order_qty

            p_desc = f"{r['product_name']}<br/><font color='#64748B' size=6>SKU: {r['sku']}</font>"
            if r.get("is_spoilage_risk"):
                p_desc += "<br/><font color='#DC2626' size=6>⚠️ Staggered Deliveries Required</font>"

            row = [
                Paragraph(str(idx + 1), cell_style),
                Paragraph(p_desc, cell_style),
                Paragraph(str(r["supplier_name"]), cell_style),
                Paragraph(str(r["stock_on_hand"]), cell_right),
                Paragraph(str(r["estimated_festival_demand"]), cell_right),
                Paragraph(str(r["safety_stock"]), cell_right),
                Paragraph(f"<b>{order_qty}</b>", cell_right_bold),
                Paragraph(f"₹{r['unit_cost']:.2f}", cell_right),
                Paragraph(f"₹{item_cost:,.2f}", cell_right_bold)
            ]
            table_rows.append(row)
    else:
        table_rows.append([
            Paragraph("-", cell_style),
            Paragraph("No items currently require procurement (stock levels adequate).", cell_style),
            Paragraph("-", cell_style), Paragraph("-", cell_style), Paragraph("-", cell_style),
            Paragraph("-", cell_style), Paragraph("-", cell_style), Paragraph("-", cell_style), Paragraph("-", cell_style)
        ])

    col_widths = [8 * mm, 52 * mm, 32 * mm, 14 * mm, 18 * mm, 16 * mm, 16 * mm, 16 * mm, 22 * mm]
    po_table = Table(table_rows, colWidths=col_widths, repeatRows=1)
    po_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#FEF3C7")),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('VALIGN', (0, 0), (-1, -1), 'TOP')
    ]))
    story.append(po_table)
    story.append(Spacer(1, 5 * mm))

    # Summary
    summary_data = [
        [
            Paragraph(f"<b>Total Units to Procure:</b> {total_units_to_order:,} units", cell_bold),
            Paragraph(f"<b>Total Estimated Capital Required:</b> {format_inr(total_est_cost)}", cell_right_bold)
        ]
    ]
    sum_table = Table(summary_data, colWidths=[90 * mm, 104 * mm])
    sum_table.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(sum_table)

    doc.build(story)
    return output_path

