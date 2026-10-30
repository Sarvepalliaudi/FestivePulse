"""
FestivePulse — SQLite Database Connection & Initialization
Enforces strict relational integrity, foreign keys, and WAL mode.
"""

import sqlite3
import contextlib
from typing import Generator
import pandas as pd
from config import DATABASE_PATH, SCHEMA_PATH

# Register numpy data types with sqlite3 so that pandas int64/float64 bind correctly in queries
try:
    import numpy as np
    sqlite3.register_adapter(np.int64, int)
    sqlite3.register_adapter(np.int32, int)
    sqlite3.register_adapter(np.int16, int)
    sqlite3.register_adapter(np.int8, int)
    sqlite3.register_adapter(np.float64, float)
    sqlite3.register_adapter(np.float32, float)
except ImportError:
    pass


def get_db_connection() -> sqlite3.Connection:
    """
    Returns an active SQLite connection configured with:
    - Foreign key constraints enabled
    - Row factory as sqlite3.Row for dictionary-like column access
    - WAL (Write-Ahead Logging) journal mode for concurrency
    """
    conn = sqlite3.connect(DATABASE_PATH, timeout=20.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


@contextlib.contextmanager
def db_session() -> Generator[sqlite3.Connection, None, None]:
    """
    Context manager for atomic database transactions.
    Automatically commits on success or rolls back on exception.
    """
    conn = get_db_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Safely applies any schema enhancements and migrations."""
    cursor = conn.cursor()
    # 1. Ensure expense_audit_logs table exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS expense_audit_logs (
            audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            expense_id INTEGER NOT NULL,
            action TEXT NOT NULL CHECK (action IN ('CREATE', 'UPDATE', 'CORRECTION', 'CANCEL')),
            changed_by TEXT DEFAULT 'User',
            previous_values TEXT,
            new_values TEXT,
            reason TEXT,
            changed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (expense_id) REFERENCES expenses(expense_id) ON DELETE CASCADE
        )
    """)

    # 2. Check expenses table schema
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='expenses'")
    row = cursor.fetchone()
    if row and row[0]:
        sql = row[0]
        if "'RENT'" not in sql or "status" not in sql:
            cursor.execute("PRAGMA foreign_keys = OFF;")
            cursor.execute("""
                CREATE TABLE expenses_migrated (
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
                )
            """)
            cursor.execute("""
                INSERT INTO expenses_migrated (
                    expense_id, expense_category, occurrence_id, expense_date,
                    amount, payment_mode, vendor_name, invoice_receipt_no, notes, created_at
                )
                SELECT expense_id, expense_category, occurrence_id, expense_date,
                       amount, payment_mode, vendor_name, invoice_receipt_no, notes, created_at
                FROM expenses
            """)
            cursor.execute("UPDATE expenses_migrated SET description = notes WHERE description IS NULL")
            cursor.execute("DROP TABLE expenses")
            cursor.execute("ALTER TABLE expenses_migrated RENAME TO expenses")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_expenses_occurrence ON expenses(occurrence_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(expense_date);")
            cursor.execute("PRAGMA foreign_keys = ON;")

    # 3. Ensure business_settings has configurable timezone, currency, and report settings
    cursor.execute("PRAGMA table_info(business_settings);")
    bs_cols = {r[1] for r in cursor.fetchall()}
    if "timezone" not in bs_cols:
        cursor.execute("ALTER TABLE business_settings ADD COLUMN timezone TEXT DEFAULT 'Asia/Kolkata';")
    if "currency_display" not in bs_cols:
        cursor.execute("ALTER TABLE business_settings ADD COLUMN currency_display TEXT DEFAULT 'INR (₹)';")
    if "report_footer_notes" not in bs_cols:
        cursor.execute("ALTER TABLE business_settings ADD COLUMN report_footer_notes TEXT DEFAULT 'FestivePulse AI — Local SQLite Database System Record';")
    if "report_page_orientation" not in bs_cols:
        cursor.execute("ALTER TABLE business_settings ADD COLUMN report_page_orientation TEXT DEFAULT 'landscape';")
    if "max_upload_size_mb" not in bs_cols:
        cursor.execute("ALTER TABLE business_settings ADD COLUMN max_upload_size_mb INTEGER DEFAULT 10;")


def init_db(force_recreate: bool = False) -> None:
    """
    Initializes the database schema and seeds initial master data if empty.
    """
    if force_recreate and DATABASE_PATH.exists():
        DATABASE_PATH.unlink()

    with db_session() as conn:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            schema_script = f.read()
        conn.executescript(schema_script)
        _run_migrations(conn)

    # After tables are ready, seed baseline data if needed
    from database.seed_data import seed_initial_data
    seed_initial_data()


def query_df(query: str, params: tuple = ()) -> pd.DataFrame:
    """
    Executes a SELECT query and returns the results as a Pandas DataFrame.
    """
    conn = get_db_connection()
    try:
        df = pd.read_sql_query(query, conn, params=params)
        return df
    finally:
        conn.close()


def execute_mutation(query: str, params: tuple = ()) -> int:
    """
    Executes an INSERT, UPDATE, or DELETE query and returns lastrowid or affected rows.
    """
    with db_session() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.lastrowid
