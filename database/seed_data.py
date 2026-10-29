"""
FestivePulse — Comprehensive Seed Data
Pre-populates authentic Indian retail business profile, master festivals,
calendar occurrences, categories, suppliers, products, inventory batches,
and historical festival sales records for deterministic analytics.
"""

import json
from config import MASTER_FESTIVALS, DEFAULT_CATEGORIES
from database.connection import db_session


def seed_initial_data() -> None:
    # Ensure festival calendar is seeded even if main business data already exists
    from repositories.festival_calendar_repository import FestivalCalendarRepository
    FestivalCalendarRepository.seed_sample_festivals()

    with db_session() as conn:
        cursor = conn.cursor()

        # 1. Check if already seeded
        cursor.execute("SELECT COUNT(*) FROM business_settings")
        if cursor.fetchone()[0] > 0:
            return  # Already seeded

        # 2. Seed Business Settings
        cursor.execute("""
            INSERT INTO business_settings (
                setting_id, business_name, trade_name, gstin, phone, email,
                address_line1, address_line2, city, state, pincode, state_code,
                primary_region, currency_symbol, number_format, financial_year_start
            ) VALUES (
                1, 'Shree Ganesh Utsav Bhandar & Festive Emporium', 'FestivePulse Retailers',
                '27AAACR1234M1Z5', '9820112345', 'contact@festivepulse-retail.in',
                'Shop No. 12-14, Central Market Yard', 'Dadar West', 'Mumbai',
                'Maharashtra', '400028', '27', 'West', '₹', 'INR_LAKHS', '04-01'
            )
        """)

        # 3. Seed Master Festivals
        for fest in MASTER_FESTIVALS:
            cursor.execute("""
                INSERT INTO festivals (
                    festival_code, festival_name, primary_regions,
                    typical_surge_multiplier, preparation_lead_days, is_active
                ) VALUES (?, ?, ?, ?, ?, 1)
            """, (
                fest["code"],
                fest["name"],
                json.dumps(fest["primary_regions"]),
                fest["typical_surge_multiplier"],
                fest["preparation_lead_days"]
            ))

        # Get festival IDs mapping
        cursor.execute("SELECT festival_code, festival_id FROM festivals")
        fest_ids = {row["festival_code"]: row["festival_id"] for row in cursor.fetchall()}

        # 4. Seed Festival Occurrences (2025 Historical + 2026 Current/Upcoming)
        occurrences = [
            # 2025 Historical for demand benchmarking
            (fest_ids["GANESH_CHATURTHI"], 2025, "2025-08-05", "2025-08-18", "2025-08-25", "2025-08-27", "2025-09-06", "Ganesh Utsav 2025 (10-day celebration)", 0),
            (fest_ids["DIWALI"], 2025, "2025-09-15", "2025-10-05", "2025-10-16", "2025-10-20", "2025-10-25", "Diwali & Dhanteras 2025 Peak Season", 0),
            (fest_ids["DURGA_PUJA"], 2025, "2025-09-01", "2025-09-15", "2025-09-25", "2025-09-29", "2025-10-04", "Sharad Navratri & Durga Puja 2025", 0),
            
            # 2026 Current and Upcoming Occurrences
            (fest_ids["PONGAL"], 2026, "2025-12-15", "2026-01-02", "2026-01-12", "2026-01-14", "2026-01-18", "Pongal & Makar Sankranti 2026", 0),
            (fest_ids["EID_FITR"], 2026, "2026-02-15", "2026-03-01", "2026-03-16", "2026-03-20", "2026-03-23", "Ramadan & Eid al-Fitr 2026", 0),
            (fest_ids["BAKRID"], 2026, "2026-05-01", "2026-05-12", "2026-05-24", "2026-05-27", "2026-05-30", "Eid al-Adha 2026", 0),
            (fest_ids["ONAM"], 2026, "2026-08-01", "2026-08-12", "2026-08-22", "2026-08-26", "2026-08-30", "Thiruvonam 2026", 0),
            (fest_ids["GANESH_CHATURTHI"], 2026, "2026-08-20", "2026-09-01", "2026-09-11", "2026-09-14", "2026-09-24", "Ganesh Utsav 2026", 0),
            (fest_ids["DURGA_PUJA"], 2026, "2026-09-15", "2026-10-01", "2026-10-12", "2026-10-15", "2026-10-20", "Durga Puja & Navratri 2026", 0),
            (fest_ids["DIWALI"], 2026, "2026-09-25", "2026-10-15", "2026-11-04", "2026-11-08", "2026-11-13", "Diwali & Dhanteras 2026 (Active/Upcoming Campaign)", 1),
            (fest_ids["CHRISTMAS"], 2026, "2026-11-20", "2026-12-05", "2026-12-20", "2026-12-25", "2026-12-31", "Christmas & Year End 2026", 0)
        ]

        cursor.executemany("""
            INSERT INTO festival_occurrences (
                festival_id, year, prep_start_date, campaign_start_date,
                peak_start_date, festival_date, campaign_end_date, notes, is_current_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, occurrences)

        # 5. Seed Product Categories
        for cat in DEFAULT_CATEGORIES:
            cursor.execute("""
                INSERT INTO product_categories (category_name, default_gst_rate, description)
                VALUES (?, ?, ?)
            """, (cat["name"], cat["gst_rate"], cat["description"]))

        cursor.execute("SELECT category_name, category_id FROM product_categories")
        cat_ids = {row["category_name"]: row["category_id"] for row in cursor.fetchall()}

        # 6. Seed Suppliers
        suppliers_data = [
            ("Haldiram Sweets & Savory Wholesale", "Ramesh Agarwal", "9821098765", "ramesh@haldiramsweets.in", "27AABCH1234F1Z1", "Mumbai", "Maharashtra", 4, "Net 15 Days"),
            ("Surat Ethnic Weaves & Garments", "Kishore Patel", "9825123456", "kishore@suratweaves.com", "24AABCS5678G1Z2", "Surat", "Gujarat", 7, "Immediate UPI / 50% Advance"),
            ("Jaipur Claycraft & Handicrafts", "Shyam Sundar Sharma", "9829034567", "shyam@jaipurclay.in", "08AABCJ9012H1Z3", "Jaipur", "Rajasthan", 10, "Net 30 Days"),
            ("Delhi Chandni Chowk Lights & Decor", "Vikas Malhotra", "9811045678", "vikas@chandnilights.in", "07AABCD3456K1Z4", "Delhi", "Delhi", 5, "Net 7 Days"),
            ("Kashmir Royal Dry Fruits Syndicate", "Bilal Ahmed", "9419056789", "bilal@kashmirdryfruits.com", "01AABCK7890L1Z5", "Srinagar", "Jammu & Kashmir", 8, "Advance Payment")
        ]

        cursor.executemany("""
            INSERT INTO suppliers (
                supplier_name, contact_person, phone, email, gstin, city, state, average_lead_time_days, payment_terms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, suppliers_data)

        # 7. Seed Initial Products
        products_data = [
            (
                "SKU-SWT-001", "890123450001", "Kaju Katli Silver Vark Gift Pack (500g)",
                cat_ids["Sweets, Dry Fruits & Mithai"], "box", 380.0, 550.0, 600.0, 5.0, "21069099",
                25, 100, 1, 12, json.dumps(["DIWALI", "GANESH_CHATURTHI", "EID_FITR", "PONGAL"]), json.dumps(["Pan-India", "North", "West"])
            ),
            (
                "SKU-SWT-002", "890123450002", "Pure Desi Ghee Motichoor Ladoo (1kg Box)",
                cat_ids["Sweets, Dry Fruits & Mithai"], "box", 320.0, 480.0, 520.0, 5.0, "21069099",
                30, 120, 1, 6, json.dumps(["DIWALI", "GANESH_CHATURTHI", "DURGA_PUJA"]), json.dumps(["North", "West", "Central"])
            ),
            (
                "SKU-DRF-001", "890123450003", "Royal 4-in-1 Dry Fruit Festive Box (Cashew, Almond, Pista, Raisin 1kg)",
                cat_ids["Gift Hampers & Specialty Packs"], "box", 750.0, 1150.0, 1299.0, 12.0, "08013200",
                40, 150, 0, None, json.dumps(["DIWALI", "EID_FITR", "CHRISTMAS", "PONGAL"]), json.dumps(["Pan-India"])
            ),
            (
                "SKU-PUJ-001", "890123450004", "Handmade Terracotta Diya Set with Cotton Wicks (Pack of 21)",
                cat_ids["Puja Samagri & Diyas"], "pack", 60.0, 120.0, 150.0, 0.0, "69139000",
                50, 200, 0, None, json.dumps(["DIWALI"]), json.dumps(["Pan-India", "North", "West"])
            ),
            (
                "SKU-PUJ-002", "890123450005", "Pure Brass Kuber Deepam Oil Lamp (Set of 2)",
                cat_ids["Puja Samagri & Diyas"], "set", 280.0, 499.0, 599.0, 0.0, "74181021",
                20, 60, 0, None, json.dumps(["DIWALI", "PONGAL", "DURGA_PUJA"]), json.dumps(["South", "West", "Pan-India"])
            ),
            (
                "SKU-DEC-001", "890123450006", "Warm White LED Rice Pixel Fairy Lights (40 Meters)",
                cat_ids["Home Decor & Festive Lighting"], "pcs", 140.0, 299.0, 399.0, 18.0, "94054090",
                35, 120, 0, None, json.dumps(["DIWALI", "CHRISTMAS", "GANESH_CHATURTHI"]), json.dumps(["Pan-India"])
            ),
            (
                "SKU-DEC-002", "890123450007", "Traditional Floral Rangoli Stencil & Colors Combo Kit",
                cat_ids["Home Decor & Festive Lighting"], "kit", 95.0, 220.0, 250.0, 18.0, "95051000",
                25, 80, 0, None, json.dumps(["DIWALI", "PONGAL", "ONAM"]), json.dumps(["West", "South"])
            ),
            (
                "SKU-APP-001", "890123450008", "Men's Jacquard Silk Kurta Churidar Set (Maroon & Gold)",
                cat_ids["Ethnic Apparel & Festive Wear"], "set", 850.0, 1699.0, 1999.0, 5.0, "62032900",
                15, 50, 0, None, json.dumps(["DIWALI", "EID_FITR", "DURGA_PUJA", "PONGAL"]), json.dumps(["Pan-India"])
            ),
            (
                "SKU-APP-002", "890123450009", "Women's Festive Chanderi Silk Saree with Blouse Piece",
                cat_ids["Ethnic Apparel & Festive Wear"], "pcs", 1100.0, 2250.0, 2699.0, 5.0, "50072010",
                15, 45, 0, None, json.dumps(["DIWALI", "DURGA_PUJA", "ONAM", "PONGAL"]), json.dumps(["East", "South", "Pan-India"])
            ),
            (
                "SKU-ELC-001", "890123450010", "Multi-Utility 750W 3-Jar Mixer Grinder (Festival Edition)",
                cat_ids["Electronics & Appliances"], "pcs", 1650.0, 2699.0, 3499.0, 18.0, "85094010",
                10, 30, 0, None, json.dumps(["DIWALI", "DURGA_PUJA", "PONGAL"]), json.dumps(["Pan-India"])
            )
        ]

        cursor.executemany("""
            INSERT INTO products (
                sku, barcode, product_name, category_id, unit_of_measure,
                cost_price, selling_price, mrp, gst_rate, hsn_code,
                min_safety_stock, reorder_quantity, is_perishable, shelf_life_days, festival_tags, region_tags
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, products_data)

        # 8. Seed Inventory Batches for Current Products
        cursor.execute("SELECT product_id, sku, cost_price, is_perishable, shelf_life_days FROM products")
        prods = {row["sku"]: row for row in cursor.fetchall()}

        # Supplier IDs
        cursor.execute("SELECT supplier_id, supplier_name FROM suppliers")
        sups = [r["supplier_id"] for r in cursor.fetchall()]

        batches = [
            # Sweets (perishable with upcoming expiry)
            (prods["SKU-SWT-001"]["product_id"], "BATCH-2026-OCT-01", sups[0], "2026-10-25", "2026-11-06", 80, 65, 380.0, "Aisle A1"),
            (prods["SKU-SWT-002"]["product_id"], "BATCH-2026-OCT-02", sups[0], "2026-10-27", "2026-11-02", 100, 75, 320.0, "Cold Counter C1"),
            # Dry fruits (long shelf life)
            (prods["SKU-DRF-001"]["product_id"], "BATCH-2026-SEP-01", sups[4], "2026-09-20", "2027-03-20", 120, 95, 750.0, "Aisle B2"),
            # Diyas
            (prods["SKU-PUJ-001"]["product_id"], "BATCH-2026-OCT-03", sups[2], "2026-10-10", None, 300, 240, 60.0, "Warehouse Row 4"),
            (prods["SKU-PUJ-002"]["product_id"], "BATCH-2026-OCT-04", sups[2], "2026-10-12", None, 60, 45, 280.0, "Showcase S2"),
            # LED lights
            (prods["SKU-DEC-001"]["product_id"], "BATCH-2026-OCT-05", sups[3], "2026-10-08", None, 150, 110, 140.0, "Aisle D1"),
            (prods["SKU-DEC-002"]["product_id"], "BATCH-2026-OCT-06", sups[3], "2026-10-14", None, 90, 70, 95.0, "Aisle D2"),
            # Apparel
            (prods["SKU-APP-001"]["product_id"], "BATCH-2026-SEP-02", sups[1], "2026-09-28", None, 40, 28, 850.0, "Garment Rack G1"),
            (prods["SKU-APP-002"]["product_id"], "BATCH-2026-SEP-03", sups[1], "2026-09-28", None, 35, 24, 1100.0, "Garment Rack G2"),
            # Appliances
            (prods["SKU-ELC-001"]["product_id"], "BATCH-2026-OCT-07", sups[0], "2026-10-05", None, 25, 18, 1650.0, "Appliances Zone")
        ]

        for b_item in batches:
            cursor.execute("""
                INSERT INTO inventory_batches (
                    product_id, batch_number, supplier_id, received_date,
                    expiry_date, quantity_received, quantity_available, unit_cost, storage_location
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, b_item)
            b_id = cursor.lastrowid
            # Seed corresponding Inbound Receipt Movement in Stock Movement Ledger
            cursor.execute("""
                INSERT INTO stock_movements (
                    product_id, batch_id, movement_type, quantity, unit_cost,
                    total_cost_impact, reference_type, reference_id, reason, created_at
                ) VALUES (?, ?, 'RECEIPT', ?, ?, ?, 'PURCHASE_RECEIPT', ?, ?, ?)
            """, (
                b_item[0], b_id, b_item[5], b_item[7], round(b_item[5] * b_item[7], 2),
                b_item[1], f"Initial stock receipt for batch {b_item[1]}", f"{b_item[3]} 09:00:00"
            ))

        # 9. Seed Sample Customers
        customers_data = [
            ("Aarav Mehta", "9820011122", "aarav.mehta@gmail.com", "27AAAAA1111A1Z1", "101, Sea View Apts, Dadar", "Mumbai", "Maharashtra", 0.0, 10000.0),
            ("Priya Sharma", "9820022233", "priya.sharma@yahoo.com", None, "B-4, Shivaji Park", "Mumbai", "Maharashtra", 0.0, 5000.0),
            ("Rajesh Iyer", "9840033344", "iyer.rajesh@outlook.com", "33BBBBB2222B1Z2", "12, TTK Road, Alwarpet", "Chennai", "Tamil Nadu", 0.0, 15000.0),
            ("Sunita Deshmukh", "9820044455", None, None, "402, Green Meadows", "Thane", "Maharashtra", 0.0, 5000.0),
            ("Vikram Singhania", "9810055566", "vikram@singhaniaexports.in", "07CCCCC3333C1Z3", "55, Barakhamba Road", "New Delhi", "Delhi", 0.0, 50000.0)
        ]

        cursor.executemany("""
            INSERT INTO customers (
                customer_name, phone, email, gstin, address, city, state, outstanding_credit, credit_limit
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, customers_data)

        # 10. Seed Historical 2025 Festival Sales (for Diwali 2025 & Ganesh Chaturthi 2025)
        # Fetch occurrence IDs
        cursor.execute("SELECT occurrence_id, festival_id, year FROM festival_occurrences WHERE year = 2025")
        occ_2025 = {row["festival_id"]: row["occurrence_id"] for row in cursor.fetchall()}
        diwali_occ_2025 = occ_2025.get(fest_ids["DIWALI"])
        ganesh_occ_2025 = occ_2025.get(fest_ids["GANESH_CHATURTHI"])

        # Fetch current 2026 Diwali occurrence for active targets
        cursor.execute("SELECT occurrence_id FROM festival_occurrences WHERE year = 2026 AND is_current_active = 1")
        current_diwali_occ = cursor.fetchone()["occurrence_id"]

        # Seed Sales Targets for Diwali 2026
        cursor.execute("""
            INSERT INTO festival_sales_targets (occurrence_id, category_id, target_revenue, target_profit, budgeted_expenses)
            VALUES (?, ?, 1500000.0, 520000.0, 85000.0)
        """, (current_diwali_occ, cat_ids["Sweets, Dry Fruits & Mithai"]))
        cursor.execute("""
            INSERT INTO festival_sales_targets (occurrence_id, category_id, target_revenue, target_profit, budgeted_expenses)
            VALUES (?, ?, 1000000.0, 450000.0, 40000.0)
        """, (current_diwali_occ, cat_ids["Gift Hampers & Specialty Packs"]))

        # Seed Historical 2025 Sales Invoices for Diwali 2025
        # 5 representative historical invoices
        hist_invoices = [
            ("INV-202526-0101", "2025-10-16", 1, diwali_occ_2025, "UPI", 7400.0, 200.0, 7200.0, 180.0, 180.0, 0.0, 0.0, 7560.0, 0),
            ("INV-202526-0102", "2025-10-17", 2, diwali_occ_2025, "CASH", 7400.0, 100.0, 7300.0, 182.5, 182.5, 0.0, 0.0, 7665.0, 0),
            ("INV-202526-0103", "2025-10-18", 3, diwali_occ_2025, "CARD", 7400.0, 300.0, 7100.0, 0.0, 0.0, 568.0, 0.0, 7668.0, 1),
            ("INV-202526-0104", "2025-10-19", 4, diwali_occ_2025, "UPI", 7400.0, 150.0, 7250.0, 181.25, 181.25, 0.0, 0.0, 7612.5, 0),
            ("INV-202526-0105", "2025-10-20", 5, diwali_occ_2025, "SPLIT", 7400.0, 200.0, 7200.0, 0.0, 0.0, 576.0, 0.0, 7776.0, 1)
        ]

        for inv in hist_invoices:
            cursor.execute("""
                INSERT INTO sales_invoices (
                    invoice_number, invoice_date, customer_id, occurrence_id,
                    payment_mode, subtotal_amount, discount_amount, total_taxable_amount,
                    cgst_amount, sgst_amount, igst_amount, roundoff_amount,
                    net_total_amount, is_interstate, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'COMPLETED')
            """, inv)
            inv_id = cursor.lastrowid

            # Add sales line items: 3 units Kaju Katli (80 received - 15 sold = 65 available)
            p_swt = prods["SKU-SWT-001"]
            cursor.execute("""
                INSERT INTO sales_items (
                    invoice_id, product_id, batch_id, quantity, unit_cost_price,
                    unit_selling_price, discount_percent, taxable_value, gst_rate,
                    cgst_rate, cgst_amount, sgst_rate, sgst_amount, igst_rate, igst_amount,
                    total_item_amount, gross_profit
                ) VALUES (?, ?, 1, 3, 380.0, 550.0, 0.0, 1650.0, 5.0, 2.5, 41.25, 2.5, 41.25, 0.0, 0.0, 1732.5, 510.0)
            """, (inv_id, p_swt["product_id"]))

            # Log stock movement for Kaju Katli sale
            cursor.execute("""
                INSERT INTO stock_movements (
                    product_id, batch_id, movement_type, quantity, unit_cost,
                    total_cost_impact, reference_type, reference_id, reason, created_at
                ) VALUES (?, 1, 'SALE', -3, 380.0, 1140.0, 'SALES_INVOICE', ?, ?, ?)
            """, (p_swt["product_id"], inv[0], f"Diwali 2025 Sale via {inv[0]}", f"{inv[1]} 12:00:00"))

            # Add sales line items: 5 units Dry Fruit Box (120 received - 25 sold = 95 available)
            p_drf = prods["SKU-DRF-001"]
            cursor.execute("""
                INSERT INTO sales_items (
                    invoice_id, product_id, batch_id, quantity, unit_cost_price,
                    unit_selling_price, discount_percent, taxable_value, gst_rate,
                    cgst_rate, cgst_amount, sgst_rate, sgst_amount, igst_rate, igst_amount,
                    total_item_amount, gross_profit
                ) VALUES (?, ?, 3, 5, 750.0, 1150.0, 0.0, 5750.0, 12.0, 6.0, 345.0, 6.0, 345.0, 0.0, 0.0, 6440.0, 2000.0)
            """, (inv_id, p_drf["product_id"]))

            # Log stock movement for Dry Fruits sale
            cursor.execute("""
                INSERT INTO stock_movements (
                    product_id, batch_id, movement_type, quantity, unit_cost,
                    total_cost_impact, reference_type, reference_id, reason, created_at
                ) VALUES (?, 3, 'SALE', -5, 750.0, 3750.0, 'SALES_INVOICE', ?, ?, ?)
            """, (p_drf["product_id"], inv[0], f"Diwali 2025 Sale via {inv[0]}", f"{inv[1]} 12:05:00"))

        # Seed adjustments and sales movements for the remaining products to reconcile them perfectly:
        # 1. Motichoor Ladoo (received 100, available 75 -> 5 damage, 20 promo samples)
        p_swt2 = prods["SKU-SWT-002"]
        cursor.execute("""
            INSERT INTO stock_adjustments (product_id, batch_id, adjustment_type, quantity, reason, cost_impact, adjustment_date)
            VALUES (?, 2, 'DAMAGE', -5, 'Damaged box packaging during handling', 1600.0, '2026-10-28')
        """, (p_swt2["product_id"],))
        cursor.execute("""
            INSERT INTO stock_movements (product_id, batch_id, movement_type, quantity, unit_cost, total_cost_impact, reference_type, reference_id, reason, created_at)
            VALUES (?, 2, 'DAMAGE', -5, 320.0, 1600.0, 'STOCK_ADJUSTMENT', 'ADJ-DMG-001', 'Damaged box packaging during handling', '2026-10-28 14:00:00')
        """, (p_swt2["product_id"],))

        cursor.execute("""
            INSERT INTO stock_adjustments (product_id, batch_id, adjustment_type, quantity, reason, cost_impact, adjustment_date)
            VALUES (?, 2, 'PROMOTIONAL_SAMPLE', -20, 'Corporate festival tasting gift samples', 6400.0, '2026-10-28')
        """, (p_swt2["product_id"],))
        cursor.execute("""
            INSERT INTO stock_movements (product_id, batch_id, movement_type, quantity, unit_cost, total_cost_impact, reference_type, reference_id, reason, created_at)
            VALUES (?, 2, 'PROMOTIONAL_SAMPLE', -20, 320.0, 6400.0, 'STOCK_ADJUSTMENT', 'ADJ-SMP-001', 'Corporate festival tasting gift samples', '2026-10-28 14:30:00')
        """, (p_swt2["product_id"],))

        # Remaining 7 products (retail counter sales reconciliation)
        retail_movements = [
            (prods["SKU-PUJ-001"]["product_id"], 4, -60, 60.0, "Diwali walk-in cash purchases"),
            (prods["SKU-PUJ-002"]["product_id"], 5, -15, 280.0, "Advance puja brass deepam bookings"),
            (prods["SKU-DEC-001"]["product_id"], 6, -40, 140.0, "Festive fairy light counter sales"),
            (prods["SKU-DEC-002"]["product_id"], 7, -20, 95.0, "Rangoli combo kit sales"),
            (prods["SKU-APP-001"]["product_id"], 8, -12, 850.0, "Men's festive silk kurta retail sales"),
            (prods["SKU-APP-002"]["product_id"], 9, -11, 1100.0, "Chanderi silk sarees retail sales"),
            (prods["SKU-ELC-001"]["product_id"], 10, -7, 1650.0, "Dhanteras appliance bookings")
        ]
        for p_id, b_id, q, u_c, rsn in retail_movements:
            cursor.execute("""
                INSERT INTO stock_movements (
                    product_id, batch_id, movement_type, quantity, unit_cost,
                    total_cost_impact, reference_type, reference_id, reason, created_at
                ) VALUES (?, ?, 'SALE', ?, ?, ?, 'SALES_INVOICE', 'RETAIL-PRE-DIWALI', ?, '2026-10-20 18:00:00')
            """, (p_id, b_id, q, u_c, round(abs(q) * u_c, 2), rsn))

        # 11. Seed 2026 Operating Expenses (Active Diwali Campaign)
        expenses_data = [
            ("FESTIVAL_DECORATION", current_diwali_occ, "2026-10-15", 18500.0, "UPI", "Shine Lighting & Decorators", "EXP-2026-001", "Festive facade LED lighting and flower torans"),
            ("PACKAGING_BOXES", current_diwali_occ, "2026-10-18", 32000.0, "BANK_TRANSFER", "PrintPack Offset Dadar", "EXP-2026-002", "500 Gold-foiled premium mithai and dry fruit gift boxes"),
            ("MARKETING_BANNERS_PAMPHLETS", current_diwali_occ, "2026-10-20", 12500.0, "UPI", "Express Digital Prints", "EXP-2026-003", "Market canopy banners and 5,000 neighborhood pamphlets"),
            ("STAFF_BONUS_OVERTIME", current_diwali_occ, "2026-10-25", 25000.0, "CASH", "Counter & Warehouse Staff", "EXP-2026-004", "Advance festive bonus for peak 10-day shifts")
        ]

        cursor.executemany("""
            INSERT INTO expenses (
                expense_category, occurrence_id, expense_date, amount,
                payment_mode, vendor_name, invoice_receipt_no, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, expenses_data)
