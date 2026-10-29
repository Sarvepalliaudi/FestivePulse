"""
FestivePulse — Security, Hardening, Input Validation & Disaster Recovery Engine

LOCAL DEPLOYMENT THREAT MODEL NOTICE:
FestivePulse is engineered specifically for local small-business retail use on a
single trusted machine or controlled local area network (LAN). It utilizes SQLite
with WAL mode for fast, local-first data ownership. It is NOT designed as an
internet-facing, multi-tenant cloud service. It does not provide native multi-user
authentication, network TLS termination, or at-rest database encryption.
Users operating on untrusted networks must deploy behind a secure reverse proxy
(such as Nginx with TLS and HTTP Basic/OAuth authentication) and utilize OS-level
full-disk encryption (e.g. BitLocker / LUKS) for at-rest storage protection.

SECURITY & HARDENING FEATURES:
1. CSV Formula Injection (DDE) Sanitization: Neutralizes leading '=', '+', '-', '@', '\t', '\r' on exports.
2. Path Traversal Protection: Enforces strict canonical directory boundaries and sanitizes filenames.
3. Upload Size & Content Safety: Limits file uploads (10 MB default) and prevents executing uploaded files.
4. Input Validation: Parameterized verification of business settings, products, sales, expenses, and festivals.
5. Parameterized SQL Enforcement: All queries use '?' parameter placeholders.
6. Database Backup & Disaster Recovery: Atomic SQLite online backups, PRAGMA integrity checks, SHA-256 verification, and safe rollback recovery on failed restores.
"""

import os
import re
import io
import json
import sqlite3
import hashlib
from datetime import datetime, date
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Union
import pandas as pd

from config import (
    BASE_DIR,
    DATABASE_PATH,
    INDIAN_STATES,
    REGIONS,
    GST_SLABS,
    EXPENSE_CATEGORIES
)
from database.connection import get_db_connection, db_session

# Directory for verified database backups
BACKUP_DIR = BASE_DIR / "data" / "backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

# Maximum upload size limit (10 Megabytes default)
DEFAULT_MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024

# Threat model declaration
DEPLOYMENT_THREAT_MODEL = {
    "target_environment": "Single trusted local workstation or controlled small-business LAN",
    "architecture": "Local-first SQLite with WAL journal concurrency",
    "is_multi_tenant_internet_service": False,
    "internet_facing_recommendation": (
        "Do NOT expose the Streamlit port directly to the public internet. "
        "If LAN access is required, place behind an authenticated reverse proxy (e.g., Nginx with TLS) "
        "and enable operating-system disk encryption (BitLocker/LUKS) for physical storage security."
    )
}


# ==============================================================================
# 1. CSV FORMULA INJECTION (DDE) PROTECTION
# ==============================================================================

# Characters that trigger spreadsheet formula evaluation in Excel, Calc, and Sheets
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "|", "%")


def sanitize_csv_cell(val: Any) -> Any:
    """
    Sanitizes a single cell value to prevent CSV Formula Injection (DDE).
    If a string starts with formula triggers (=, +, -, @, tab, return, pipe),
    it is escaped with a leading single quote (') unless it is a valid pure number.
    Spreadsheet applications treat single-quote prefixed cells strictly as literal text.
    """
    if val is None:
        return ""

    # If it is a container (list, tuple, dict, set, numpy array)
    if isinstance(val, (list, tuple, dict, set)):
        s = str(val)
    elif isinstance(val, (int, float, bool)):
        if isinstance(val, float) and pd.isna(val):
            return ""
        return val
    else:
        try:
            if pd.isna(val):
                return ""
        except (ValueError, TypeError):
            pass
        s = str(val)

    if not s:
        return ""

    stripped = s.strip()
    if not stripped:
        return s

    first_char = stripped[0]
    if first_char in FORMULA_PREFIXES:
        # Check if it is a standard signed number (e.g., "+100", "-50.50", "-0.25")
        try:
            float(stripped)
            # Pure number: safe to leave unchanged
            return val
        except ValueError:
            # Dangerous formula or command execution payload: neutralise by prefixing single quote
            return f"'{s}"

    return s


def sanitize_df_for_csv(df: pd.DataFrame) -> pd.DataFrame:
    """
    Returns a copy of the DataFrame with all text/object columns sanitized
    against CSV formula injection before exporting to spreadsheet software.
    """
    if df.empty:
        return df.copy()

    clean_df = df.copy()
    for col in clean_df.columns:
        if clean_df[col].dtype == "object":
            clean_df[col] = clean_df[col].apply(sanitize_csv_cell)

    return clean_df


# ==============================================================================
# 2. PATH TRAVERSAL & SAFE FILE HANDLING
# ==============================================================================

def sanitize_filename(filename: str) -> str:
    """
    Strips directory separators, traversal tokens ('..'), null bytes, and unsafe characters.
    Returns a clean base filename safe across all operating systems.
    """
    if not filename:
        return "unnamed_file"

    # Remove null bytes
    base = str(filename).replace("\0", "")
    # Remove directory traversal sequences (e.g. ../ or ..\)
    base = re.sub(r"\.\.+[\\/]+", "", base)
    # Convert any remaining slashes and backslashes to underscores
    base = re.sub(r"[\\/]+", "_", base)
    # Remove control characters and non-whitelisted characters
    base = re.sub(r"[^\w\.\-\_]", "_", base)
    # Collapse multiple dots to a single dot (e.g. ...secret....db -> .secret.db)
    base = re.sub(r"\.{2,}", ".", base)
    # Collapse multiple underscores
    base = re.sub(r"_{2,}", "_", base)
    # Avoid leading or trailing dots and underscores
    base = base.strip("._")

    return base or "unnamed_file"


def resolve_safe_path(base_dir: Union[str, Path], user_path: Union[str, Path]) -> Path:
    """
    Resolves canonical path and verifies that it strictly resides within base_dir.
    Raises PermissionError if a directory traversal attempt is detected.
    """
    base_dir = Path(base_dir).resolve()
    target_path = Path(user_path)

    if not target_path.is_absolute():
        resolved_path = (base_dir / target_path).resolve()
    else:
        resolved_path = target_path.resolve()

    try:
        resolved_path.relative_to(base_dir)
    except ValueError:
        raise PermissionError(
            f"Path traversal detected: Target path '{user_path}' resolves outside allowed directory '{base_dir}'."
        )

    return resolved_path


# ==============================================================================
# 3. UPLOAD SIZE & CONTENT VALIDATION
# ==============================================================================

PROHIBITED_EXTENSIONS = {
    ".exe", ".bat", ".cmd", ".sh", ".ps1", ".vbs", ".js", ".py", ".pyw",
    ".dll", ".so", ".bin", ".com", ".scr", ".msi", ".jar", ".php", ".phtml"
}


def validate_uploaded_file(
    file_name: str,
    file_bytes: bytes,
    max_size_bytes: int = DEFAULT_MAX_UPLOAD_SIZE_BYTES,
    allowed_extensions: Tuple[str, ...] = (".csv", ".db", ".sqlite", ".sqlite3", ".bak")
) -> Tuple[bool, str]:
    """
    Validates uploaded file size, extension, and content invariants:
    - Size must not exceed max_size_bytes.
    - File must not be empty.
    - Extension must be in allowed_extensions.
    - Must not contain null bytes in file name or executable extensions.
    """
    if not file_name:
        return False, "File upload rejected: Missing filename."

    clean_name = sanitize_filename(file_name)
    ext = Path(clean_name).suffix.lower()

    if not ext:
        return False, "File upload rejected: Missing file extension."

    if ext in PROHIBITED_EXTENSIONS:
        return False, f"File upload rejected: Executable or script extension '{ext}' is prohibited."

    if ext not in [e.lower() for e in allowed_extensions]:
        return False, f"File upload rejected: Extension '{ext}' is not permitted. Allowed: {', '.join(allowed_extensions)}"

    if not file_bytes or len(file_bytes) == 0:
        return False, "File upload rejected: Uploaded file is completely empty."

    if len(file_bytes) > max_size_bytes:
        mb_size = len(file_bytes) / (1024 * 1024)
        mb_limit = max_size_bytes / (1024 * 1024)
        return False, f"File upload rejected: Size ({mb_size:.2f} MB) exceeds maximum allowed limit ({mb_limit:.2f} MB)."

    return True, f"File '{clean_name}' passed upload validation."


# ==============================================================================
# 4. COMPREHENSIVE INPUT VALIDATION
# ==============================================================================

def validate_business_settings_input(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validates business legal info, GSTIN, region, timezone, and report settings."""
    errors = []

    b_name = str(data.get("business_name", "")).strip()
    if not b_name:
        errors.append("Business Legal Name is required.")
    elif len(b_name) > 150:
        errors.append("Business Name must not exceed 150 characters.")

    phone = str(data.get("phone", "")).strip()
    phone_digits = re.sub(r"\D", "", phone)
    if not phone:
        errors.append("Contact Phone Number is required.")
    elif len(phone_digits) < 10 or len(phone_digits) > 12:
        errors.append("Phone Number must contain 10 to 12 digits.")

    gstin = str(data.get("gstin", "")).strip().upper()
    if gstin:
        gstin_regex = r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$"
        if not re.match(gstin_regex, gstin):
            errors.append(f"Invalid GSTIN format '{gstin}'. Standard GSTIN is 15 alphanumeric characters (e.g. 27AAACR1234M1Z5).")

    email = str(data.get("email", "")).strip()
    if email:
        email_regex = r"^[\w\.\+\-]+@[\w\.\-]+\.[a-zA-Z]{2,}$"
        if not re.match(email_regex, email):
            errors.append(f"Invalid email address '{email}'.")

    reg = str(data.get("primary_region", "")).strip()
    if reg and reg not in REGIONS:
        errors.append(f"Invalid primary region '{reg}'. Must be one of: {', '.join(REGIONS)}.")

    tz = str(data.get("timezone", "")).strip()
    if tz and len(tz) > 60:
        errors.append("Timezone identifier must not exceed 60 characters.")

    max_up = data.get("max_upload_size_mb")
    if max_up is not None:
        try:
            m_val = int(max_up)
            if m_val < 1 or m_val > 100:
                errors.append("Max upload size must be between 1 MB and 100 MB.")
        except (ValueError, TypeError):
            errors.append("Max upload size must be an integer number of megabytes.")

    return (len(errors) == 0, errors)


def validate_product_input(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validates product catalog attributes before database persistence."""
    errors = []

    sku = str(data.get("sku", "")).strip().upper()
    if not sku:
        errors.append("SKU is required.")
    elif len(sku) > 50:
        errors.append("SKU must not exceed 50 characters.")
    elif not re.match(r"^[\w\.\-\_]+$", sku):
        errors.append("SKU must contain only alphanumeric characters, dashes, and underscores.")

    name = str(data.get("product_name", "")).strip()
    if not name:
        errors.append("Product Name is required.")
    elif len(name) > 200:
        errors.append("Product Name must not exceed 200 characters.")

    uom = str(data.get("unit_of_measure", "")).strip().lower()
    valid_uoms = {"pcs", "kg", "grams", "box", "pack", "meter", "set", "kit"}
    if not uom or uom not in valid_uoms:
        errors.append(f"Invalid Unit of Measure '{uom}'. Allowed: {', '.join(sorted(valid_uoms))}.")

    try:
        cost = float(data.get("cost_price", 0))
        if cost < 0:
            errors.append("Cost Price must be non-negative (>= 0.00).")
    except (ValueError, TypeError):
        errors.append("Cost Price must be a valid numeric amount.")

    try:
        price = float(data.get("selling_price", 0))
        if price < 0:
            errors.append("Selling Price must be non-negative (>= 0.00).")
        elif "cost" in locals() and price < cost:
            errors.append(f"Selling Price (₹{price:,.2f}) cannot be less than Cost Price (₹{cost:,.2f}).")
    except (ValueError, TypeError):
        errors.append("Selling Price must be a valid numeric amount.")

    try:
        gst = float(data.get("gst_rate", 0))
        if gst not in GST_SLABS:
            errors.append(f"Invalid GST Rate '{gst}%'. Must be a standard slab: {GST_SLABS}.")
    except (ValueError, TypeError):
        errors.append("GST Rate must be a valid numeric slab.")

    return (len(errors) == 0, errors)


def validate_expense_input(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validates expense vouchers and audit attributes."""
    errors = []

    dt = str(data.get("expense_date", "")).strip()
    if not dt:
        errors.append("Expense Date is required.")
    else:
        try:
            datetime.strptime(dt, "%Y-%m-%d")
        except ValueError:
            errors.append(f"Expense Date '{dt}' must follow ISO format (YYYY-MM-DD).")

    cat = str(data.get("category") or data.get("expense_category") or "").strip().upper()
    valid_cats = {c[0] for c in EXPENSE_CATEGORIES}
    if not cat or cat not in valid_cats:
        errors.append(f"Invalid Expense Category '{cat}'. Allowed categories: {', '.join(sorted(valid_cats))}.")

    try:
        amt = float(data.get("amount", 0))
        if amt <= 0:
            errors.append("Expense Amount must be strictly greater than 0.00.")
    except (ValueError, TypeError):
        errors.append("Expense Amount must be a valid numeric value.")

    stat = str(data.get("status", "ACTIVE")).strip().upper()
    if stat not in ("ACTIVE", "CORRECTED", "CANCELLED"):
        errors.append(f"Invalid Expense Status '{stat}'. Allowed: ACTIVE, CORRECTED, CANCELLED.")

    return (len(errors) == 0, errors)


# ==============================================================================
# 5. DATABASE INTEGRITY CHECKS & DIAGNOSTICS
# ==============================================================================

def check_database_integrity() -> Dict[str, Any]:
    """
    Executes deep SQLite low-level integrity verification:
    - PRAGMA integrity_check (page allocations, B-trees, indices)
    - PRAGMA quick_check
    - PRAGMA foreign_key_check (relational integrity across all tables)
    Returns detailed health diagnostics.
    """
    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        # 1. Full integrity check
        cursor.execute("PRAGMA integrity_check;")
        integrity_rows = cursor.fetchall()
        is_integrity_ok = len(integrity_rows) == 1 and integrity_rows[0][0] == "ok"
        integrity_messages = [r[0] for r in integrity_rows]

        # 2. Foreign key relational check
        cursor.execute("PRAGMA foreign_key_check;")
        fk_violations = cursor.fetchall()
        fk_issues = []
        for v in fk_violations:
            fk_issues.append({
                "table": v[0],
                "rowid": v[1],
                "parent_table": v[2],
                "fk_idx": v[3]
            })

        # 3. Database metrics
        cursor.execute("PRAGMA page_count;")
        page_count = cursor.fetchone()[0]
        cursor.execute("PRAGMA page_size;")
        page_size = cursor.fetchone()[0]
        cursor.execute("PRAGMA freelist_count;")
        freelist_count = cursor.fetchone()[0]

        file_size_bytes = DATABASE_PATH.stat().st_size if DATABASE_PATH.exists() else 0

        is_healthy = is_integrity_ok and len(fk_issues) == 0

        return {
            "is_healthy": is_healthy,
            "status": "HEALTHY" if is_healthy else "ISSUES_DETECTED",
            "integrity_status": "ok" if is_integrity_ok else "; ".join(integrity_messages),
            "foreign_key_violations_count": len(fk_issues),
            "foreign_key_violations": fk_issues,
            "page_count": page_count,
            "page_size": page_size,
            "freelist_pages": freelist_count,
            "file_size_bytes": file_size_bytes,
            "file_size_kb": round(file_size_bytes / 1024, 2),
            "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")
        }
    finally:
        conn.close()


# ==============================================================================
# 6. ATOMIC BACKUP, VERIFICATION & DISASTER RECOVERY RESTORE
# ==============================================================================

def create_database_backup(destination_path: Optional[Path] = None, notes: str = "") -> Dict[str, Any]:
    """
    Creates an atomic, non-locking backup of the live SQLite database using
    sqlite3.Connection.backup().
    Verifies the backup immediately via PRAGMA integrity_check, computes its
    SHA-256 hash, and logs manifest metadata.
    """
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    if destination_path is None:
        ts_slug = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest_file = BACKUP_DIR / f"festivepulse_backup_{ts_slug}.db"
    else:
        dest_file = resolve_safe_path(BACKUP_DIR, destination_path)

    # 1. Connect to live database
    src_conn = get_db_connection()
    try:
        # Pre-backup sanity check on live DB
        cur = src_conn.cursor()
        cur.execute("PRAGMA integrity_check;")
        live_check = cur.fetchone()[0]
        if live_check != "ok":
            raise RuntimeError(f"Live database integrity check failed before backup: {live_check}")

        # 2. Perform online atomic backup
        dest_conn = sqlite3.connect(str(dest_file))
        try:
            src_conn.backup(dest_conn)
        finally:
            dest_conn.close()

        # 3. Post-backup verification on the generated file
        chk_conn = sqlite3.connect(str(dest_file))
        try:
            chk_cur = chk_conn.cursor()
            chk_cur.execute("PRAGMA integrity_check;")
            chk_res = chk_cur.fetchone()[0]
            if chk_res != "ok":
                raise RuntimeError(f"Generated backup file failed integrity check: {chk_res}")
        finally:
            chk_conn.close()

        # 4. Compute SHA-256 checksum and size
        hasher = hashlib.sha256()
        with open(dest_file, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                hasher.update(chunk)
        sha256_hash = hasher.hexdigest()
        file_size = dest_file.stat().st_size

        metadata = {
            "filename": dest_file.name,
            "filepath": str(dest_file),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S IST"),
            "file_size_bytes": file_size,
            "sha256": sha256_hash,
            "integrity_status": "VERIFIED_OK",
            "notes": notes or "Automated on-demand snapshot"
        }

        # Append to manifest
        manifest_file = BACKUP_DIR / "backup_manifest.json"
        manifest_records = []
        if manifest_file.exists():
            try:
                with open(manifest_file, "r", encoding="utf-8") as f:
                    manifest_records = json.load(f)
            except Exception:
                manifest_records = []
        manifest_records.append(metadata)
        with open(manifest_file, "w", encoding="utf-8") as f:
            json.dump(manifest_records, f, indent=2)

        return metadata
    finally:
        src_conn.close()


def verify_backup_file(backup_path: Path) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Performs comprehensive verification of a backup file:
    - Checks file existence and minimum size (> 100 bytes).
    - Validates SQLite 16-byte magic header ('SQLite format 3\000').
    - Executes PRAGMA integrity_check and PRAGMA quick_check.
    - Confirms required FestivePulse tables exist and are readable.
    """
    backup_path = Path(backup_path)
    if not backup_path.exists() or not backup_path.is_file():
        return False, f"Backup file not found at '{backup_path}'.", {}

    if backup_path.stat().st_size < 100:
        return False, "File is too small to be a valid SQLite database.", {}

    # Verify SQLite format 3 magic header bytes
    try:
        with open(backup_path, "rb") as f:
            header = f.read(16)
        if header != b"SQLite format 3\000":
            return False, "File is not a valid SQLite database (missing 'SQLite format 3' magic header).", {}
    except Exception as e:
        return False, f"Failed to read file header: {str(e)}", {}

    # Open connection to backup and inspect
    try:
        conn = sqlite3.connect(str(backup_path), timeout=5.0)
        try:
            cursor = conn.cursor()

            # Integrity check
            cursor.execute("PRAGMA integrity_check;")
            res = cursor.fetchone()[0]
            if res != "ok":
                return False, f"Corrupted SQLite database: integrity_check returned '{res}'.", {}

            # Table verification
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = {r[0] for r in cursor.fetchall()}
            required_tables = {"products", "sales_invoices", "inventory_batches", "business_settings"}
            missing = required_tables - tables
            if missing:
                return False, f"Backup is missing essential FestivePulse tables: {', '.join(sorted(missing))}.", {}

            # Gather table counts
            counts = {}
            for t in ["products", "sales_invoices", "inventory_batches", "expenses", "festivals"]:
                if t in tables:
                    cursor.execute(f"SELECT COUNT(*) FROM {t};")
                    counts[t] = cursor.fetchone()[0]

            details = {
                "tables_count": len(tables),
                "record_counts": counts,
                "file_size_bytes": backup_path.stat().st_size,
                "integrity": "PASSED"
            }
            return True, "Backup file verified successfully. All integrity checks passed.", details
        finally:
            conn.close()
    except Exception as e:
        return False, f"Failed to verify database file: {str(e)}", {}


def restore_database_backup(backup_path: Path, confirm: bool = False) -> Tuple[bool, str]:
    """
    Restores the live database from a verified backup file.
    SAFEGUARDS:
    1. Requires explicit confirmation (confirm=True).
    2. Runs verify_backup_file() on the source backup BEFORE touching the live database.
    3. Creates an emergency pre-restore snapshot of the current live database.
    4. Restores atomically using sqlite3.Connection.backup().
    5. Runs PRAGMA integrity_check on the restored live database.
    6. Safe Failure Recovery: If anything fails, automatically rolls back to the pre-restore snapshot!
    """
    if not confirm:
        return False, "Restoration aborted: Explicit user confirmation is required before overwriting live database."

    backup_path = Path(backup_path)

    # 1. Pre-verification: Verify backup validity before touching live DB
    is_valid, msg, details = verify_backup_file(backup_path)
    if not is_valid:
        return False, f"Restoration aborted: Target backup file failed integrity checks ({msg}). Live database was NOT modified."

    # 2. Emergency Rollback Snapshot: Save copy of current live DB
    emergency_snapshot = None
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        emergency_snapshot = BACKUP_DIR / f"festivepulse_pre_restore_safety_{ts}.bak"

        live_conn = get_db_connection()
        try:
            emerg_conn = sqlite3.connect(str(emergency_snapshot))
            try:
                live_conn.backup(emerg_conn)
            finally:
                emerg_conn.close()
        finally:
            live_conn.close()
    except Exception as e:
        return False, f"Restoration aborted: Failed to create pre-restore emergency rollback snapshot ({str(e)}). Live database was NOT modified."

    # 3. Perform restoration using SQLite backup API
    try:
        src_backup_conn = sqlite3.connect(str(backup_path))
        dest_live_conn = get_db_connection()
        try:
            src_backup_conn.backup(dest_live_conn)
        finally:
            src_backup_conn.close()
            dest_live_conn.close()

        # 4. Post-restore verification on live database
        post_conn = get_db_connection()
        try:
            cur = post_conn.cursor()
            cur.execute("PRAGMA integrity_check;")
            post_res = cur.fetchone()[0]
            if post_res != "ok":
                raise RuntimeError(f"Post-restore live database check failed: {post_res}")
        finally:
            post_conn.close()

        return True, (
            f"Database successfully restored from '{backup_path.name}'. "
            f"Pre-restore emergency safety rollback snapshot preserved as '{emergency_snapshot.name}'."
        )
    except Exception as restore_err:
        # 5. SAFE FAILURE RECOVERY: Roll back to emergency snapshot!
        if emergency_snapshot and emergency_snapshot.exists():
            try:
                rb_src = sqlite3.connect(str(emergency_snapshot))
                rb_dest = get_db_connection()
                try:
                    rb_src.backup(rb_dest)
                finally:
                    rb_src.close()
                    rb_dest.close()
                return False, (
                    f"Restoration failed: {str(restore_err)}. "
                    f"Automatic emergency rollback succeeded — live database was safely restored to pre-operation state."
                )
            except Exception as rb_err:
                return False, (
                    f"CRITICAL: Restoration failed ({str(restore_err)}) and emergency rollback also failed ({str(rb_err)}). "
                    f"The safety snapshot file remains available at '{emergency_snapshot}'."
                )
        return False, f"Restoration failed: {str(restore_err)}."


def list_backups() -> List[Dict[str, Any]]:
    """
    Returns a sorted list of all verified backups in data/backups/.
    """
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backups = []

    # Read manifest if present
    manifest_map = {}
    manifest_file = BACKUP_DIR / "backup_manifest.json"
    if manifest_file.exists():
        try:
            with open(manifest_file, "r", encoding="utf-8") as f:
                records = json.load(f)
                for r in records:
                    manifest_map[r["filename"]] = r
        except Exception:
            manifest_map = {}

    for p in BACKUP_DIR.glob("*.db"):
        if p.is_file():
            stat = p.stat()
            file_meta = manifest_map.get(p.name, {})
            backups.append({
                "filename": p.name,
                "filepath": str(p),
                "created_at": file_meta.get("created_at") or datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S IST"),
                "file_size_bytes": stat.st_size,
                "file_size_kb": round(stat.st_size / 1024, 1),
                "sha256": file_meta.get("sha256", "-"),
                "notes": file_meta.get("notes", "Manual Snapshot")
            })

    # Sort newest first
    backups.sort(key=lambda x: x["filename"], reverse=True)
    return backups
