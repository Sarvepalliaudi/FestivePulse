# 🪔 FestivePulse — Festival Sales & Inventory Command Center

> **Real, Local-First Festival Sales and Inventory Management for Indian Small & Medium Businesses.**  
> **100% Deterministic & Non-AI:** Operates strictly on classical operations research, deterministic inventory formulas, standard accounting rules, and Indian GST tax law. Zero ML, zero LLMs, zero simulated AI.

---

## 🌟 Key Features

1. **Deterministic Festival Demand Estimation (100% Non-AI)**
   - **Historical YoY Model:** $E = \lceil S_{\text{past festival}} \times g \rceil$ using actual previous year festival sales and user-defined growth rate $g$.
   - **Cold Start Surge Model:** $E = \lceil D_{\text{regular}} \times M_{\text{fest}} \times W \rceil$ using 60-day baseline sales and category surge multipliers for new stores or new SKUs.

2. **Smart Reorder & Procurement Advisor**
   - Calculates **Safety Stock** ($SS$) buffer to absorb festive transport jams.
   - Calculates **Reorder Point** ($ROP$) and Recommended Order Quantity ($ROQ$) with standard pack size rounding.
   - **Perishable Spoilage Safeguard:** If a perishable item's shelf life is shorter than the festival campaign (e.g. fresh sweets/mithai), FestivePulse automatically generates a **staggered 3-phase delivery schedule** and warns against bulk pre-orders.

3. **High-Speed Point of Sale (POS) Counter Billing**
   - Quick SKU/barcode search and line item entry.
   - Automatic **FIFO (First In, First Out) batch selection** by expiry date.
   - Atomic SQLite transactions preventing negative inventory.
   - Full GST calculation with intra-state (50% CGST + 50% SGST) vs inter-state (100% IGST) support.
   - UPI QR prompt, Cash, Card, and Customer Khata (store credit) recording.
   - One-click professional **GST Tax Invoice PDF** generation using ReportLab.

4. **Festival Profit & Loss (P&L) Accounting**
   - Exact Cost of Goods Sold (COGS) captured at the time of sale.
   - Operating overheads tracking (store decoration, temporary stall rent, festival packaging, overtime bonuses, transport).
   - Net Festival Profit & **Return on Festival Investment (ROI %)**.

5. **Indian Retail Localization**
   - Pre-configured for **Diwali, Durga Puja, Pongal, Onam, Ganesh Chaturthi, Eid al-Fitr, Bakrid / Eid al-Adha, and Christmas**, plus custom regional festival definitions.
   - Native Indian numbering system formatting: Lakhs & Crores (`₹1,50,000`, `₹12,40,000`).
   - Standard Indian GST slabs (0%, 5%, 12%, 18%, 28%).

6. **Reports & Data Management**
   - GSTR-3B Outward Tax Liability summary.
   - Customer Khata recovery ledger.
   - Post-festival dead stock & clearance audit.
   - Bulk CSV import/export for products and sales.
   - Local ACID SQLite database backup (`.db`).

---

## 🚀 Quick Start Guide

### 1. Requirements & Dependencies
- Python 3.10+
- Installed libraries: `streamlit`, `pandas`, `plotly`, `reportlab`

Install dependencies universally:
```bash
python -m pip install -r requirements.txt
```

### 2. Launch the Application
Run via Python's module runner (compatible with Windows, macOS, Linux, and Cloud):

```bash
python -m streamlit run app.py
```

- **Local PC / Mac Access:** Open `http://localhost:8501` in your browser.
- **Mobile Phone / Tablet Access:** Connect your phone to the same local Wi-Fi / LAN network and open `http://<your-computer-ip>:8501`.
- **Cloud Deployment:** Directly deployable on Streamlit Community Cloud, Docker, VPS, Render, or Railway with `.streamlit/config.toml` pre-configured.

### 3. Running Unit Tests
```bash
python -m unittest discover tests
```

---

## 📂 Project Architecture

```
FestivePulse AI/
├── app.py                      # Main entrypoint & session state orchestrator
├── config.py                   # Constants, festival defaults, GST slabs, styling
├── requirements.txt            # Python dependencies
├── database/
│   ├── connection.py           # SQLite connection pooling & PRAGMA setup
│   ├── schema.sql              # Clean DDL with foreign keys & indexes
│   ├── seed_data.py            # Initial seed: Indian retail store, festivals, products
│   └── queries.py              # Optimized analytical and CRUD queries
├── services/
│   ├── currency_utils.py       # Indian numbering (Lakhs/Crores), INR formatting
│   ├── festival_service.py     # Festival calendar, active window checks
│   ├── inventory_service.py    # Batches, FIFO allocation, stock tracking
│   ├── sales_service.py        # Invoice creation, GST calculations, POS engine
│   ├── demand_engine.py        # Deterministic demand estimation & surge multipliers
│   ├── stock_recommender.py    # Reorder point, safety stock, lead time math
│   ├── expense_service.py      # Expense tracking & profit/ROI calculations
│   ├── pdf_generator.py        # ReportLab invoice & PO generator
│   └── ui_components.py        # Streamlit & Plotly styling tokens
├── pages/
│   ├── 1_📊_Dashboard.py        # Executive KPIs, sales pace, countdown, regional snapshot
│   ├── 2_🛍️_Products.py         # Product master, categories, pricing, festival tags
│   ├── 3_📦_Inventory.py        # Stock on hand, batches, expiry alerts, adjustments
│   ├── 4_🧾_Billing_POS.py      # Rapid bill generator, GST invoicing, UPI/Cash recording
│   ├── 5_🎉_Festivals.py        # Festival calendar, regional filters, targets
│   ├── 6_📈_Demand_Forecast.py  # Historical comparison & deterministic surge projections
│   ├── 7_🛒_Reorder_Advisor.py  # Stock procurement sheets, safety stock recommendations
│   ├── 8_💰_Expenses_Profit.py  # Festival overheads, COGS, Net Profit, ROI
│   ├── 9_📑_Reports.py          # GST summary, Category performance, Dead stock audit
│   ├── 10_📁_Import_Export.py   # Bulk CSV upload/download, database backup
│   └── 11_⚙️_Settings.py        # Business profile, GSTIN, regional customization
├── assets/
│   └── custom.css              # Rich Indian festival aesthetics (Marigold/Crimson/Emerald)
└── tests/
    ├── test_dashboard.py       # Unit tests for dashboard KPIs and chart data
    ├── test_db.py              # Unit tests for SQLite WAL constraints and transactions
    ├── test_demand_estimation.py # Unit tests for historical YoY and baseline demand math
    ├── test_expense_management.py # Unit tests for expense audit, immutable cost snapshots, and P&L
    ├── test_festival_calendar.py # Unit tests for festival calendar, dates, and overlap
    ├── test_hardening.py       # Unit tests for input sanitization, security, and disaster recovery
    ├── test_import_export.py   # Unit tests for CSV validation, preview, duplicate detection, and rollback
    ├── test_inventory_module.py # Unit tests for stock batches, movements, and expiry alerts
    ├── test_math.py            # Unit tests for tax, demand, safety stock formulas
    ├── test_product_module.py  # Unit tests for product catalog and categories
    ├── test_reports.py         # Unit tests for PDF/CSV reports and metadata classification
    ├── test_repositories.py    # Unit tests for repository layer CRUD and transactions
    ├── test_sales_module.py    # Unit tests for sales POS, FIFO inventory, returns, and khata
    ├── test_stock_planning.py  # Unit tests for budget limits and stock planning math
    └── test_ui_workflow.py     # End-to-end integration test across all 11 core shopkeeper workflows
```

---

## 💰 Expense Management & P&L Accounting System

FestivePulse provides an auditable, local-first expense management and Profit & Loss (P&L) accounting engine compliant with Indian retail practices and commercial audit standards.

### 1. Expense Categories & Metadata
Every expense record captures:
- **Amount**: Stored in decimal precision ($> 0$).
- **Expense Date**: Date incurred (`YYYY-MM-DD`).
- **Category**: Standard operational categories:
  - `RENT`: Stall rental, warehouse lease, additional counter space.
  - `TRANSPORT`: Freight logistics, delivery van hire, inbound cartage.
  - `PACKAGING`: Sweet boxes, decorative hampers, carry bags, gift wrapping.
  - `WAGES`: Temporary counter assistants, peak festival overtime bonuses.
  - `MARKETING`: Banners, local flyers, social promotions, loudspeaker permits.
  - `OTHER`: Generator fuel, temporary lighting, decorative floral garlands, festival licensing.
- **Description / Notes**: Context and purpose of the expenditure.
- **Festival Reference (`occurrence_id`)**: Optional association with a specific festival campaign.

### 2. Audit Trail & Non-Destructive Corrections
- **Zero Loss of Financial History**: Expense records are never hard-deleted.
- **Correction Workflow**: When an expense is edited, its status changes to `CORRECTED`, and both previous and new values are logged in `expense_audit_logs` along with a mandatory audit reason, timestamp, and user identifier.
- **Cancellation Workflow**: Erroneous vouchers or cancelled supplier payments are marked `CANCELLED` and logged in `expense_audit_logs`. Cancelled expenses are permanently excluded from P&L calculations.

### 3. Inviolable Historical Cost Snapshots
- When an item is sold, `sales_items.unit_cost_price` captures the exact batch acquisition cost at that moment.
- **Catalog Insulation Invariant**: When a supplier raises the product catalog cost in `products.cost_price`, historical `sales_items.unit_cost_price` records are **never modified**. Past COGS and historical Gross Profit remain 100% stable and accurate.

### 4. Mathematical P&L Formulas

$$\begin{aligned}
\text{Gross Billed Revenue} &= \sum \text{invoices.subtotal\_amount} \\
\text{Total Discounts} &= \sum \text{invoices.discount\_amount} \\
\text{Gross Taxable Sales} &= \sum \text{invoices.total\_taxable\_amount} = \text{Gross Billed Revenue} - \text{Total Discounts} \\
\text{Net Taxable Returns} &= \sum (\text{sales\_returns.refund\_amount} - \text{sales\_returns.tax\_refund\_amount}) \\
\mathbf{\text{Net Sales Revenue}} &= \mathbf{\text{Gross Taxable Sales} - \text{Net Taxable Returns}} \\
\\
\text{Gross COGS} &= \sum (\text{sales\_items.unit\_cost\_price} \times \text{sales\_items.quantity}) \\
\text{Returned COGS} &= \sum (\text{sales\_items.unit\_cost\_price} \times \text{sales\_returns.quantity}) \\
\mathbf{\text{Net COGS}} &= \mathbf{\text{Gross COGS} - \text{Returned COGS}} \\
\\
\mathbf{\text{Gross Profit}} &= \mathbf{\text{Net Sales Revenue} - \text{Net COGS}} \\
\text{Gross Margin \%} &= \left( \frac{\text{Gross Profit}}{\text{Net Sales Revenue}} \right) \times 100 \\
\\
\mathbf{\text{Net Operating Profit}} &= \mathbf{\text{Gross Profit} - \sum \text{Included Relevant Operating Expenses}} \\
\text{Net Operating Margin \%} &= \left( \frac{\text{Net Operating Profit}}{\text{Net Sales Revenue}} \right) \times 100 \\
\text{Operating ROI \%} &= \left( \frac{\text{Net Operating Profit}}{\text{Net COGS} + \sum \text{Included Relevant Operating Expenses}} \right) \times 100
\end{aligned}$$

### 5. Relevant Expenses & Labeled Exclusions
Net operating profit is computed strictly against **relevant expenses** matching the selected scope. Any excluded expense is clearly flagged in a **Labeled Exclusions** ledger:
- **Cancelled Vouchers**: Flagged with the cancellation audit reason.
- **General Store Overheads**: Excluded when viewing a specific festival campaign (unless the user explicitly toggles on general overhead inclusion).
- **Off-Festival Expenses**: Expenses tagged to other festival occurrences are segregated.
- **Active Category Filters**: When filtering for specific categories (e.g. `MARKETING` only), all other operational expenses are labeled as excluded.

---

## 📁 Reliable CSV Import & Export System

FestivePulse includes an enterprise-grade CSV import and export system designed for operational integrity and local-first data ownership.

### 1. Invariants & Business Safeguards
- **Movement Ledger Invariant**: Imported inbound stock balances **never bypass** the inventory movement ledger. Every accepted stock row atomically creates a batch in `inventory_batches` and writes an immutable `RECEIPT` record in `stock_movements`.
- **Zero Silent Discard**: Invalid rows or duplicate sales are **never silently ignored**. The importer produces an itemized report of accepted and rejected rows with exact line numbers and failure reasons.
- **Stock Depletion on Sales Import**: Imported sales invoices atomically verify unexpired inventory availability, allocate stock via FIFO, update batch balances, and record `SALE` deductions in the movement ledger.
- **Full UTF-8 Compatibility**: All templates and exported CSVs use UTF-8 with BOM (`utf-8-sig`) for full compatibility with Microsoft Excel, Indian Rupee symbols (`₹`), and regional festival names.

### 2. Import Modes
- **Atomic Mode (All-or-Nothing)**: Pre-validates all records. If a single row fails validation or contains duplicates, the entire batch rolls back with zero modifications applied to the database.
- **Safe Row-by-Row Mode**: Commits valid rows while safely isolating invalid rows into a downloadable rejection report.

### 3. Supported Entities & Column Specifications
- **Products**: `sku`, `product_name`, `category`, `unit_of_measure`, `cost_price`, `selling_price`, `gst_rate`, `mrp`, `barcode`, `hsn_code`, `min_safety_stock`, `reorder_quantity`, `is_perishable`, `shelf_life_days`, `festival_tags`.
- **Sales**: `invoice_date`, `sku`, `quantity`, `selling_price`, `invoice_number`, `discount_pct`, `overall_discount`, `payment_mode`, `customer_phone`, `customer_name`, `festival_reference`, `transaction_reference`, `notes`.
- **Expenses**: `expense_date`, `category`, `amount`, `description`, `festival_reference`, `payment_mode`, `vendor_name`, `invoice_receipt_no`.
- **Stock Inward**: `sku`, `batch_number`, `quantity`, `unit_cost`, `received_date`, `expiry_date`, `supplier_name`, `storage_location`, `purchase_invoice_no`, `reason`.

---

## 📑 Official Operational & Audit Reports Engine

FestivePulse provides an official reporting and audit export engine producing publication-grade PDFs and detailed CSVs across 6 operational and financial domains:

### 1. Core Report Categories
1. **Sales Summary & Tax Invoicing Ledger**: Consolidated transaction audit of billed invoices, item line totals, GST collections (CGST/SGST/IGST), and gross profit per line item.
2. **Inventory Valuation & Stock Status Report**: Warehouse inventory stock balances, cost asset valuation, counter turnover value, safety stock buffers, and status alerts (`HEALTHY`, `LOW STOCK`, `CRITICAL LOW`).
3. **Auditable Stock Movement Ledger**: Chronological audit trail of all inventory movement events (`RECEIPT`, `SALE`, `DAMAGE`, `EXPIRED`, `RETURN_RESTOCK`, etc.) with unit acquisition costs and financial impact.
4. **Festival Campaign Comparative Performance Report**: Multi-year campaign comparative analysis of billed sales, discounts, net revenue, net COGS, operating expenses, net operating profit, and campaign ROI %.
5. **Operating Expenses & Overheads Audit Report**: Categorized operational overheads (Rent, Logistics, Packaging, Staff Wages, Marketing) tracked against festival campaign scopes and audit statuses.
6. **Deterministic Forecast-Based Stock Procurement Plan**: Procurement planning using deterministic formulas:
   $$\text{Suggested Purchase Quantity} = \max(0, \text{Planned Demand} + \text{Safety Stock} - \text{Usable Stock})$$
   Evaluates planned outlay against purchasing budgets and highlights top excess cost contributors.

### 2. Reporting Invariants & Design Standards
- **Zero Hallucination / No Invented Charts**: 100% of figures originate from local SQLite ledger records or explicit deterministic planning formulas.
- **Explicit Actuals vs. Estimates Separation**: Every report displays a prominent data classification banner:
  - **ACTUAL (Recorded Database Ledger Records)**: For historic sales, on-hand inventory, stock movements, and audited expenses.
  - **ESTIMATES & PLANNING PROJECTIONS (Deterministic Formulas — Non-Guaranteed Forecasts)**: For festival demand forecasts and purchasing replenishment plans.
- **Standardized Metadata**: Every generated CSV and PDF includes:
  - Official Report Title and Store Header Profile (Store Name, GSTIN, Address, Phone).
  - Report Generation Timestamp (IST).
  - Explicit Currency INR (Indian Rupee) declaration.
  - Active Filter Parameters dictionary.
  - Calculation Definitions and mathematical formulas.
- **Maintained ReportLab PDF Formatting**:
  - Two-pass `NumberedCanvas` delivering dynamic `Page X of Y` footers.
  - Repeated table headers (`repeatRows=1`) across all multi-page tables.
  - Sensible landscape/portrait A4 dimensions with clean cell auto-wrapping.
  - Unicode-safe monetary rendering (`INR X,XX,XXX.XX` and `₹`).
- **Reliable Empty State Handling**: When zero database records match the selected date/region/product filters, downloads still produce valid, non-corrupted PDF and CSV files displaying informative notices.

---

## 🛡️ Local Deployment Threat Model & Security Hardening

FestivePulse is purposefully designed and hardened for **local, single-operator small-business retail and warehouse use**. In accordance with honest software engineering principles, we do not claim unsupported "enterprise-grade cloud security" where it does not exist.

### 1. Deployment Operating Boundaries & Threat Model

| Operational Dimension | Reality & Implemented Architecture |
| :--- | :--- |
| **Intended Environment** | Single trusted workstation, billing counter POS, or a tightly controlled local LAN / private Wi-Fi. |
| **Database Engine** | Local embedded SQLite running in Write-Ahead Logging (`PRAGMA journal_mode=WAL`) and `PRAGMA foreign_keys=ON`. |
| **Internet Multi-Tenancy** | **NOT SUPPORTED / NOT INTENDED**. SQLite does not provide native network user isolation, row-level access control, or concurrent internet-scale access. Never expose this app directly to the public internet without an external authentication proxy (e.g., Nginx with TLS and HTTP basic auth or OAuth). |
| **Physical / Host Security** | If an unauthorized party gains access to the operating system or raw SQLite file, they have physical access to the data. Small businesses should enforce host-level login passwords and OS full-disk encryption (e.g., **BitLocker** on Windows, **FileVault** on macOS, or **LUKS** on Linux). |

### 2. Implemented Security Safeguards

1. **100% Parameterized SQL Execution**
   - All queries throughout repositories and services exclusively use SQL parameter binding placeholders (`?`).
   - Zero dynamic string concatenation or f-strings in SQL statements, neutralizing SQL injection vectors.

2. **CSV Formula Injection (DDE) Protection**
   - Spreadsheets (Microsoft Excel, LibreOffice Calc, Apple Numbers) execute formulas when cell text begins with `=`, `+`, `-`, `@`, `\t`, `\r`, or `|`.
   - The export engine automatically scans all string and object columns with `sanitize_csv_cell()` / `sanitize_df_for_csv()`.
   - Dangerous payloads (e.g. `=cmd|' /C calc'!A0` or `@SUM(...)`) are safely prefixed with a single quote (`'`), rendering them inert literal text in spreadsheet viewers.
   - Genuine signed numeric values (e.g. `-150.50`, `+25.00`) are mathematically verified via float parsing and preserved without modification.

3. **Path Traversal & Safe Path Resolution**
   - User-supplied filenames are sanitized with `sanitize_filename()`, which strips traversal tokens (`..`), path separators (`/`, `\`), null bytes, and non-whitelisted characters.
   - Path resolution with `resolve_safe_path()` verifies that all file targets are strictly children of their designated directory (`Path.is_relative_to`), raising a `PermissionError` on any escape attempts.

4. **Strict Upload File Handling**
   - Importers enforce an explicit file size ceiling (default: 10MB, configurable via Business Settings).
   - Prohibited executable extensions (`.exe`, `.bat`, `.cmd`, `.sh`, `.py`, `.js`, `.vbs`, etc.) are actively screened and rejected.
   - Uploaded files are strictly parsed as passive UTF-8 tabular text; no user-supplied file is ever executed or evaluated.

5. **Credential & Secret Protection**
   - The codebase includes a hardened `.gitignore` ensuring that `.env`, SQLite databases (`*.db`, `*.sqlite`), emergency snapshots (`*.bak`), and generated reports are kept out of version control.

6. **Configurable Business Profile & Localization**
   - Configurable legal business name, trade name, GSTIN, address, and phone.
   - Regional localization (All India, North, South, East, West).
   - Currency display standards (Indian numbering `₹1,50,000` vs standard international `INR 150,000.00`).
   - Timezone configuration (e.g., `Asia/Kolkata` / IST).
   - Report formatting preferences (Landscape vs Portrait orientation, custom audit footer notes).
   - Upload ceiling customization.

---

## 💾 Backup, Disaster Recovery & Integrity Verification

To protect local retail businesses against hardware crashes, power cuts, or accidental operational corruption, FestivePulse provides atomic backup, integrity diagnostics, and safety-guarded restoration.

### 1. Atomic Online Backups
- Uses Python's native `sqlite3.Connection.backup()` API.
- Generates a point-in-time snapshot without locking the live WAL database or corrupting ongoing POS billing transactions.
- Computes and displays the SHA-256 cryptographic hash of every backup file.

### 2. Comprehensive Database Integrity Diagnostics
- Runs live SQLite integrity checks directly from the UI or programmatic service:
  - `PRAGMA integrity_check`: Validates B-tree indexing and internal database page structures.
  - `PRAGMA foreign_key_check`: Scans for broken relationship constraints.
  - Page count and on-disk file size telemetry.

### 3. Destruction Protection & Emergency Rollback
- **Confirmation Required**: Database restoration requires explicit confirmation (`confirm=True` or UI confirmation toggle).
- **Pre-Restoration Integrity Verification**: Candidate backup files are verified for the SQLite format 3 magic header and core schema tables before live data is touched.
- **Automated Safety Snapshot**: Immediately before applying a restore, the system generates an emergency pre-restore snapshot (`festivepulse_pre_restore_safety_*.bak`).
- **Safe Failure Recovery**: If the newly restored database fails post-restore integrity checks, FestivePulse **automatically rolls back** to the safety snapshot, preserving existing data and logging the incident.

---

## 🧪 Comprehensive Automated Test Suite

FestivePulse includes a comprehensive automated test suite consisting of **140 unit and integration tests** verifying financial calculations, database ACID integrity, security safeguards, and disaster recovery:

```bash
python -m unittest discover tests
```

- `tests/test_ui_workflow.py`: End-to-end integration test validating the full operational workflow from product creation, stock batch receipt, POS billing, and movement ledger auditing to official report generation and disaster recovery backups.
- `tests/test_hardening.py`: CSV formula injection escaping, path traversal blocking, upload size enforcement, PRAGMA database integrity, backup creation, destructive restore confirmation, and automated rollback recovery.
- `tests/test_reports.py`: PDF generation with ReportLab, CSV data exports, classification labels (Actuals vs Estimates), metadata dictionaries, and empty-state handling.
- `tests/test_import_export.py`: CSV parsing, row-level validation, duplicate detection, atomic transactions, and movement ledger reconciliation.
- `tests/test_expense_management.py`: Audit trails, non-destructive expense corrections, immutable historical cost snapshots, P&L calculations, and labeled exclusions.
- `tests/test_stock_planning.py`: Deterministic reorder formulas, safety stock calculations, budget limits, and excess cost contributors.
- `tests/test_demand_estimation.py`: Non-AI historical YoY demand estimations, baseline calculations, and insufficient history handling.
- `tests/test_dashboard.py`: SQLite-backed KPI metrics, month-to-date sales, inventory valuation, and dynamic chart filtering.
- `tests/test_sales_module.py`: POS transactions, FIFO inventory allocation, stock movement receipts/deductions, discounts, sales returns, and cancellation reversals.
- `tests/test_festival_calendar.py`: Regional filtering, festival date validations, and overlapping planning windows.
- `tests/test_inventory_module.py`: Batch tracking, expiry alerts, and stock adjustments.
- `tests/test_math.py`: Indian numbering formatting, GST tax splitting, and monetary precision.

---

## ☁️ Streamlit Community Cloud Free Hosting Guide

FestivePulse is configured for one-click deployment on **Streamlit Community Cloud**:

### 1. Step-by-Step Deployment Steps
1. Push your code to GitHub: `https://github.com/Sarvepalliaudi/FestivePulse.git` on the `main` branch.
2. Sign in to [share.streamlit.io](https://share.streamlit.io/) with your GitHub account (`Sarvepalliaudi`).
3. Click **"New app"** (or **"Create app"**).
4. Fill in the deployment form:
   - **Repository**: `Sarvepalliaudi/FestivePulse`
   - **Branch**: `main`
   - **Main file path**: `app.py`
   - **App URL** (Optional): Choose a custom subdomain (e.g. `festivepulse.streamlit.app`).
5. Click **"Deploy!"**.
6. Streamlit Cloud will automatically install dependencies from `requirements.txt` and launch the app.

### 2. Configuration & Secrets
- **No external API keys or secrets are required** for default operation because FestivePulse is 100% deterministic and non-AI.
- If you need custom environment variables in the future, configure them in the Streamlit Cloud dashboard under **App Settings > Secrets** using TOML format.

### 3. ⚠️ Cloud Database Persistence & Privacy Notice
> [!WARNING]
> **Ephemeral Storage Notice:** Streamlit Community Cloud runs in stateless, ephemeral Linux containers.
> - Any sales, products, or stock transactions recorded through the public web interface will persist **only while the container is actively running**.
> - When the container reboots, updates, or goes to sleep due to inactivity, local storage (`festivepulse.db`) resets back to the initial seeded demo state.
> - **Privacy:** Do not enter real-world confidential customer records or private financial data on a public Streamlit Cloud deployment.
> - **Production Deployment:** For permanent live store operations, run FestivePulse locally on a dedicated PC/laptop (where SQLite is permanent and offline-first) or connect to an external persistent database (such as PostgreSQL).

---

## 👨‍💻 Author & Developer

**Audi Siva Bhanuvardhan Sarvepalli**  
🔗 LinkedIn: [linkedin.com/in/audi-siva-bhanuvardhan-sarvepalli-4598a8289](https://www.linkedin.com/in/audi-siva-bhanuvardhan-sarvepalli-4598a8289/)  

*FestivePulse — Designed and engineered for Indian small-business retailers, distributors, and warehouse operators.*
