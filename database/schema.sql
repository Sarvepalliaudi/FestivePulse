PRAGMA foreign_keys = ON;

-- 1. Business & Store Settings
CREATE TABLE IF NOT EXISTS business_settings (
    setting_id INTEGER PRIMARY KEY CHECK (setting_id = 1),
    business_name TEXT NOT NULL,
    trade_name TEXT,
    gstin TEXT,
    phone TEXT NOT NULL,
    email TEXT,
    address_line1 TEXT NOT NULL,
    address_line2 TEXT,
    city TEXT NOT NULL,
    state TEXT NOT NULL,
    pincode TEXT NOT NULL,
    state_code TEXT NOT NULL,
    primary_region TEXT NOT NULL CHECK (primary_region IN ('North', 'South', 'East', 'West', 'Central', 'North-East', 'Pan-India')),
    currency_symbol TEXT DEFAULT '₹',
    currency_display TEXT DEFAULT 'INR (₹)',
    number_format TEXT DEFAULT 'INR_LAKHS',
    financial_year_start TEXT DEFAULT '04-01',
    timezone TEXT DEFAULT 'Asia/Kolkata',
    report_footer_notes TEXT DEFAULT 'FestivePulse AI — Local SQLite Database System Record',
    report_page_orientation TEXT DEFAULT 'landscape',
    max_upload_size_mb INTEGER DEFAULT 10,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 2. Master Festival Definitions
CREATE TABLE IF NOT EXISTS festivals (
    festival_id INTEGER PRIMARY KEY AUTOINCREMENT,
    festival_code TEXT NOT NULL UNIQUE,
    festival_name TEXT NOT NULL,
    primary_regions TEXT NOT NULL, -- JSON array of strings
    typical_surge_multiplier REAL DEFAULT 2.50,
    preparation_lead_days INTEGER DEFAULT 30,
    is_active INTEGER DEFAULT 1 CHECK (is_active IN (0, 1))
);

-- 3. Festival Calendar Occurrences (Yearly Dates)
CREATE TABLE IF NOT EXISTS festival_occurrences (
    occurrence_id INTEGER PRIMARY KEY AUTOINCREMENT,
    festival_id INTEGER NOT NULL,
    year INTEGER NOT NULL,
    prep_start_date DATE NOT NULL,
    campaign_start_date DATE NOT NULL,
    peak_start_date DATE NOT NULL,
    festival_date DATE NOT NULL,
    campaign_end_date DATE NOT NULL,
    notes TEXT,
    is_current_active INTEGER DEFAULT 0 CHECK (is_current_active IN (0, 1)),
    FOREIGN KEY (festival_id) REFERENCES festivals(festival_id) ON DELETE CASCADE,
    UNIQUE (festival_id, year)
);

-- 3b. Configurable Festival Calendar
CREATE TABLE IF NOT EXISTS festival_calendar (
    calendar_id INTEGER PRIMARY KEY AUTOINCREMENT,
    festival_name TEXT NOT NULL,
    festival_code TEXT,
    region TEXT NOT NULL DEFAULT 'Pan-India',
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    category TEXT NOT NULL DEFAULT 'Traditional & Religious',
    planning_window_days INTEGER NOT NULL DEFAULT 30,
    planning_start_date DATE NOT NULL,
    notes TEXT,
    is_sample_date INTEGER DEFAULT 1 CHECK (is_sample_date IN (0, 1)),
    is_verified INTEGER DEFAULT 0 CHECK (is_verified IN (0, 1)),
    year INTEGER NOT NULL,
    is_active_campaign INTEGER DEFAULT 0 CHECK (is_active_campaign IN (0, 1)),
    occurrence_id INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (occurrence_id) REFERENCES festival_occurrences(occurrence_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_festival_calendar_dates ON festival_calendar(start_date, end_date);
CREATE INDEX IF NOT EXISTS idx_festival_calendar_region ON festival_calendar(region);
CREATE INDEX IF NOT EXISTS idx_festival_calendar_planning ON festival_calendar(planning_start_date);

-- 4. Product Categories
CREATE TABLE IF NOT EXISTS product_categories (
    category_id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_name TEXT NOT NULL UNIQUE,
    default_gst_rate REAL NOT NULL CHECK (default_gst_rate IN (0.0, 5.0, 12.0, 18.0, 28.0)),
    description TEXT
);

-- 5. Suppliers
CREATE TABLE IF NOT EXISTS suppliers (
    supplier_id INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_name TEXT NOT NULL,
    contact_person TEXT,
    phone TEXT NOT NULL,
    email TEXT,
    gstin TEXT,
    city TEXT,
    state TEXT,
    average_lead_time_days INTEGER DEFAULT 7,
    payment_terms TEXT,
    is_active INTEGER DEFAULT 1
);

-- 6. Products Master
CREATE TABLE IF NOT EXISTS products (
    product_id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT NOT NULL UNIQUE,
    barcode TEXT UNIQUE,
    product_name TEXT NOT NULL,
    category_id INTEGER NOT NULL,
    unit_of_measure TEXT NOT NULL CHECK (unit_of_measure IN ('pcs', 'kg', 'grams', 'box', 'pack', 'meter', 'set', 'kit')),
    cost_price REAL NOT NULL CHECK (cost_price >= 0),
    selling_price REAL NOT NULL CHECK (selling_price >= cost_price),
    mrp REAL CHECK (mrp >= selling_price),
    gst_rate REAL NOT NULL CHECK (gst_rate IN (0.0, 5.0, 12.0, 18.0, 28.0)),
    hsn_code TEXT,
    min_safety_stock INTEGER DEFAULT 10 CHECK (min_safety_stock >= 0),
    reorder_quantity INTEGER DEFAULT 50 CHECK (reorder_quantity > 0),
    is_perishable INTEGER DEFAULT 0 CHECK (is_perishable IN (0, 1)),
    shelf_life_days INTEGER DEFAULT NULL,
    festival_tags TEXT, -- JSON array of festival codes: ["DIWALI", "PONGAL"]
    region_tags TEXT, -- JSON array of regional tags: ["North", "West"]
    is_active INTEGER DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (category_id) REFERENCES product_categories(category_id)
);

-- 7. Inventory Stock Batches
CREATE TABLE IF NOT EXISTS inventory_batches (
    batch_id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    batch_number TEXT NOT NULL,
    supplier_id INTEGER,
    received_date DATE NOT NULL,
    expiry_date DATE,
    quantity_received INTEGER NOT NULL CHECK (quantity_received > 0),
    quantity_available INTEGER NOT NULL CHECK (quantity_available >= 0),
    unit_cost REAL NOT NULL CHECK (unit_cost >= 0),
    storage_location TEXT,
    FOREIGN KEY (product_id) REFERENCES products(product_id) ON DELETE RESTRICT,
    FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id) ON DELETE SET NULL,
    UNIQUE (product_id, batch_number)
);

-- 8. Stock Adjustments
CREATE TABLE IF NOT EXISTS stock_adjustments (
    adjustment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    batch_id INTEGER,
    adjustment_type TEXT NOT NULL CHECK (adjustment_type IN ('DAMAGE', 'EXPIRED', 'THEFT_SHRINKAGE', 'PROMOTIONAL_SAMPLE', 'MANUAL_COUNT_RECONCILIATION')),
    quantity INTEGER NOT NULL,
    reason TEXT NOT NULL,
    cost_impact REAL NOT NULL,
    adjustment_date DATE NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (product_id) REFERENCES products(product_id),
    FOREIGN KEY (batch_id) REFERENCES inventory_batches(batch_id)
);

-- 8b. Auditable Stock Movement Ledger
CREATE TABLE IF NOT EXISTS stock_movements (
    movement_id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    batch_id INTEGER,
    movement_type TEXT NOT NULL CHECK (movement_type IN (
        'RECEIPT', 'SALE', 'SALE_CANCEL', 'DAMAGE', 'EXPIRED', 
        'THEFT_SHRINKAGE', 'PROMOTIONAL_SAMPLE', 'MANUAL_COUNT_RECONCILIATION', 
        'OPENING_STOCK', 'RETURN_TO_SUPPLIER'
    )),
    quantity INTEGER NOT NULL,
    unit_cost REAL NOT NULL DEFAULT 0.0 CHECK (unit_cost >= 0),
    total_cost_impact REAL NOT NULL DEFAULT 0.0,
    reference_type TEXT CHECK (reference_type IN ('PURCHASE_RECEIPT', 'SALES_INVOICE', 'INVOICE_CANCEL', 'SALES_RETURN', 'STOCK_ADJUSTMENT', 'OPENING_STOCK', 'RECONCILIATION', 'OTHER')),
    reference_id TEXT,
    reason TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (product_id) REFERENCES products(product_id) ON DELETE RESTRICT,
    FOREIGN KEY (batch_id) REFERENCES inventory_batches(batch_id) ON DELETE SET NULL
);

-- 9. Customers
CREATE TABLE IF NOT EXISTS customers (
    customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_name TEXT NOT NULL,
    phone TEXT UNIQUE,
    email TEXT,
    gstin TEXT,
    address TEXT,
    city TEXT,
    state TEXT,
    outstanding_credit REAL DEFAULT 0.0 CHECK (outstanding_credit >= 0),
    credit_limit REAL DEFAULT 0.0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 10. Sales Invoices
CREATE TABLE IF NOT EXISTS sales_invoices (
    invoice_id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_number TEXT NOT NULL UNIQUE,
    invoice_date DATE NOT NULL,
    customer_id INTEGER,
    occurrence_id INTEGER,
    payment_mode TEXT NOT NULL CHECK (payment_mode IN ('UPI', 'CASH', 'CARD', 'CREDIT_KHATA', 'SPLIT')),
    subtotal_amount REAL NOT NULL CHECK (subtotal_amount >= 0),
    discount_amount REAL DEFAULT 0.0 CHECK (discount_amount >= 0),
    total_taxable_amount REAL NOT NULL CHECK (total_taxable_amount >= 0),
    cgst_amount REAL DEFAULT 0.0 CHECK (cgst_amount >= 0),
    sgst_amount REAL DEFAULT 0.0 CHECK (sgst_amount >= 0),
    igst_amount REAL DEFAULT 0.0 CHECK (igst_amount >= 0),
    roundoff_amount REAL DEFAULT 0.0,
    net_total_amount REAL NOT NULL CHECK (net_total_amount >= 0),
    is_interstate INTEGER DEFAULT 0 CHECK (is_interstate IN (0, 1)),
    status TEXT DEFAULT 'COMPLETED' CHECK (status IN ('COMPLETED', 'CANCELLED', 'REFUNDED', 'RETURNED', 'PARTIALLY_RETURNED')),
    transaction_reference TEXT,
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id),
    FOREIGN KEY (occurrence_id) REFERENCES festival_occurrences(occurrence_id)
);

-- 11. Sales Line Items
CREATE TABLE IF NOT EXISTS sales_items (
    item_id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    batch_id INTEGER,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_cost_price REAL NOT NULL CHECK (unit_cost_price >= 0),
    unit_selling_price REAL NOT NULL CHECK (unit_selling_price >= 0),
    discount_percent REAL DEFAULT 0.0 CHECK (discount_percent BETWEEN 0.0 AND 100.0),
    taxable_value REAL NOT NULL CHECK (taxable_value >= 0),
    gst_rate REAL NOT NULL CHECK (gst_rate IN (0.0, 5.0, 12.0, 18.0, 28.0)),
    cgst_rate REAL DEFAULT 0.0,
    cgst_amount REAL DEFAULT 0.0,
    sgst_rate REAL DEFAULT 0.0,
    sgst_amount REAL DEFAULT 0.0,
    igst_rate REAL DEFAULT 0.0,
    igst_amount REAL DEFAULT 0.0,
    total_item_amount REAL NOT NULL CHECK (total_item_amount >= 0),
    gross_profit REAL NOT NULL,
    FOREIGN KEY (invoice_id) REFERENCES sales_invoices(invoice_id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(product_id),
    FOREIGN KEY (batch_id) REFERENCES inventory_batches(batch_id)
);

-- 11b. Sales Returns & Reversals Ledger
CREATE TABLE IF NOT EXISTS sales_returns (
    return_id INTEGER PRIMARY KEY AUTOINCREMENT,
    return_number TEXT NOT NULL UNIQUE,
    invoice_id INTEGER NOT NULL,
    item_id INTEGER,
    product_id INTEGER NOT NULL,
    batch_id INTEGER,
    return_date DATE NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    refund_amount REAL NOT NULL CHECK (refund_amount >= 0),
    tax_refund_amount REAL DEFAULT 0.0,
    reason TEXT NOT NULL,
    restock_to_inventory INTEGER DEFAULT 1 CHECK (restock_to_inventory IN (0, 1)),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (invoice_id) REFERENCES sales_invoices(invoice_id) ON DELETE RESTRICT,
    FOREIGN KEY (item_id) REFERENCES sales_items(item_id) ON DELETE SET NULL,
    FOREIGN KEY (product_id) REFERENCES products(product_id) ON DELETE RESTRICT,
    FOREIGN KEY (batch_id) REFERENCES inventory_batches(batch_id) ON DELETE SET NULL
);

-- 12. Operating Expenses
CREATE TABLE IF NOT EXISTS expenses (
    expense_id INTEGER PRIMARY KEY AUTOINCREMENT,
    expense_category TEXT NOT NULL CHECK (expense_category IN (
        'RENT', 'TRANSPORT', 'PACKAGING', 'WAGES', 'MARKETING', 'OTHER',
        'FESTIVAL_DECORATION', 'TEMPORARY_STALL_RENT', 'PACKAGING_BOXES', 
        'STAFF_BONUS_OVERTIME', 'MARKETING_BANNERS_PAMPHLETS', 'TRANSPORT_FREIGHT', 
        'UTILITIES_POWER', 'MISCELLANEOUS'
    )),
    occurrence_id INTEGER,
    expense_date DATE NOT NULL,
    amount REAL NOT NULL CHECK (amount > 0),
    payment_mode TEXT NOT NULL DEFAULT 'CASH' CHECK (payment_mode IN ('UPI', 'CASH', 'BANK_TRANSFER', 'CARD', 'OTHER')),
    vendor_name TEXT,
    invoice_receipt_no TEXT,
    description TEXT,
    notes TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'CORRECTED', 'CANCELLED')),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (occurrence_id) REFERENCES festival_occurrences(occurrence_id)
);

-- 12b. Expense Edit & Correction Audit Logs
CREATE TABLE IF NOT EXISTS expense_audit_logs (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    expense_id INTEGER NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('CREATE', 'UPDATE', 'CORRECTION', 'CANCEL')),
    changed_by TEXT DEFAULT 'User',
    previous_values TEXT, -- JSON string
    new_values TEXT,      -- JSON string
    reason TEXT,
    changed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (expense_id) REFERENCES expenses(expense_id) ON DELETE CASCADE
);

-- 13. Festival Sales & Procurement Targets
CREATE TABLE IF NOT EXISTS festival_sales_targets (
    target_id INTEGER PRIMARY KEY AUTOINCREMENT,
    occurrence_id INTEGER NOT NULL,
    category_id INTEGER,
    target_revenue REAL NOT NULL CHECK (target_revenue > 0),
    target_profit REAL CHECK (target_profit >= 0),
    budgeted_expenses REAL DEFAULT 0.0 CHECK (budgeted_expenses >= 0),
    FOREIGN KEY (occurrence_id) REFERENCES festival_occurrences(occurrence_id) ON DELETE CASCADE,
    FOREIGN KEY (category_id) REFERENCES product_categories(category_id) ON DELETE CASCADE,
    UNIQUE (occurrence_id, category_id)
);

-- Analytical & Fast Lookup Indexes
CREATE INDEX IF NOT EXISTS idx_products_sku ON products(sku);
CREATE INDEX IF NOT EXISTS idx_products_category ON products(category_id);
CREATE INDEX IF NOT EXISTS idx_batches_product ON inventory_batches(product_id);
CREATE INDEX IF NOT EXISTS idx_batches_expiry ON inventory_batches(expiry_date);
CREATE INDEX IF NOT EXISTS idx_sales_date ON sales_invoices(invoice_date);
CREATE INDEX IF NOT EXISTS idx_sales_occurrence ON sales_invoices(occurrence_id);
CREATE INDEX IF NOT EXISTS idx_sales_items_invoice ON sales_items(invoice_id);
CREATE INDEX IF NOT EXISTS idx_sales_items_product ON sales_items(product_id);
CREATE INDEX IF NOT EXISTS idx_expenses_occurrence ON expenses(occurrence_id);
CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(expense_date);
CREATE INDEX IF NOT EXISTS idx_festival_dates ON festival_occurrences(prep_start_date, campaign_end_date);
CREATE INDEX IF NOT EXISTS idx_stock_movements_product ON stock_movements(product_id);
CREATE INDEX IF NOT EXISTS idx_stock_movements_batch ON stock_movements(batch_id);
CREATE INDEX IF NOT EXISTS idx_stock_movements_type ON stock_movements(movement_type);
CREATE INDEX IF NOT EXISTS idx_stock_movements_created ON stock_movements(created_at);
CREATE INDEX IF NOT EXISTS idx_sales_returns_invoice ON sales_returns(invoice_id);
CREATE INDEX IF NOT EXISTS idx_sales_returns_product ON sales_returns(product_id);
CREATE INDEX IF NOT EXISTS idx_sales_transaction_ref ON sales_invoices(transaction_reference);
