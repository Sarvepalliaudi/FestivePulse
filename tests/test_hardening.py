"""
FestivePulse — Security Hardening, Input Validation & Disaster Recovery Test Suite
Validates:
- Protection against CSV Formula Injection (DDE) on exports
- Path Traversal Prevention and filename sanitization
- Upload size limits, extension whitelisting, and executable prevention
- Comprehensive input validation for business profile, products, and expenses
- Low-level database integrity checks (PRAGMA integrity_check, PRAGMA foreign_key_check)
- Atomic database backup generation with SHA-256 and integrity verification
- Disaster recovery restoration with confirmation safeguards and automated rollback
- Configurable business name, region, currency display, timezone, and report settings
"""

import unittest
import io
import os
import shutil
import tempfile
from pathlib import Path
import pandas as pd

from database.connection import init_db, get_db_connection, db_session, DATABASE_PATH
from database.queries import get_business_settings, update_business_settings
from services.security_service import (
    sanitize_csv_cell,
    sanitize_df_for_csv,
    sanitize_filename,
    resolve_safe_path,
    validate_uploaded_file,
    validate_business_settings_input,
    validate_product_input,
    validate_expense_input,
    check_database_integrity,
    create_database_backup,
    verify_backup_file,
    restore_database_backup,
    list_backups,
    BACKUP_DIR
)


class TestSecurityHardeningAndDisasterRecovery(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        """Prepares clean test context and backup directory."""
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    # ==========================================================================
    # 1. CSV FORMULA INJECTION (DDE) SANITIZATION TESTS
    # ==========================================================================
    def test_csv_formula_injection_sanitization(self):
        """Verifies that spreadsheet formula triggers are escaped while pure numbers remain untouched."""
        # Malicious spreadsheet payloads that must be escaped
        malicious_cases = [
            ("=cmd|'/c calc'!A1", "'=cmd|'/c calc'!A1"),
            ("=SUM(A1:B10)", "'=SUM(A1:B10)"),
            ("@SUM(1,2)", "'@SUM(1,2)"),
            ("+cmd", "'+cmd"),
            ("+1+2", "'+1+2"),
            ("-powershell", "'-powershell"),
            ("\t=1+1", "'\t=1+1"),
            ("\r=evil", "'\r=evil"),
            ("|calc", "'|calc"),
            ("=HYPERLINK(\"http://evil.com\")", "'=HYPERLINK(\"http://evil.com\")")
        ]
        for raw, expected in malicious_cases:
            cleaned = sanitize_csv_cell(raw)
            self.assertEqual(cleaned, expected, f"Failed to sanitize CSV injection formula: {raw}")

        # Pure numbers (positive and negative) that MUST be preserved as valid numbers
        safe_numbers = [
            -150.50,
            "+50",
            "-25",
            "-0.05",
            0,
            1250.75,
            "100"
        ]
        for num in safe_numbers:
            res = sanitize_csv_cell(num)
            if isinstance(num, str) and num.startswith(("+", "-")):
                # Should not be prefixed with quote if it's a valid float
                self.assertFalse(str(res).startswith("'"), f"Valid number was incorrectly escaped: {num}")

        # Normal text strings without formula triggers
        self.assertEqual(sanitize_csv_cell("Kaju Katli Special Box"), "Kaju Katli Special Box")
        self.assertEqual(sanitize_csv_cell("Diwali Festive Sale 2026"), "Diwali Festive Sale 2026")
        self.assertEqual(sanitize_csv_cell(None), "")

    def test_sanitize_dataframe_for_csv(self):
        """Verifies that sanitize_df_for_csv safely escapes entire DataFrames."""
        df = pd.DataFrame([
            {"sku": "SKU-001", "name": "=cmd|'calc'!A0", "price": 450.0, "notes": "@alert(1)"},
            {"sku": "SKU-002", "name": "Pure Gold Diya", "price": 1200.0, "notes": "-50% discount campaign"},
            {"sku": "SKU-003", "name": "Sweets Hamper", "price": 800.0, "notes": "+91 9876543210"}
        ])
        clean_df = sanitize_df_for_csv(df)

        # Check that formula payloads are escaped with single quote
        self.assertTrue(clean_df.iloc[0]["name"].startswith("'="))
        self.assertTrue(clean_df.iloc[0]["notes"].startswith("'@"))
        self.assertTrue(clean_df.iloc[1]["notes"].startswith("'-"))
        self.assertTrue(clean_df.iloc[2]["notes"].startswith("'+"))

        # Check that safe values remain unaltered
        self.assertEqual(clean_df.iloc[0]["sku"], "SKU-001")
        self.assertEqual(clean_df.iloc[1]["name"], "Pure Gold Diya")
        self.assertEqual(clean_df.iloc[0]["price"], 450.0)

    # ==========================================================================
    # 2. PATH TRAVERSAL & SAFE FILENAMES TESTS
    # ==========================================================================
    def test_path_traversal_prevention(self):
        """Verifies that directory traversal tokens are blocked and stripped."""
        # 1. Filename sanitization
        self.assertEqual(sanitize_filename("../../etc/passwd"), "etc_passwd")
        self.assertEqual(sanitize_filename("..\\..\\windows\\system32\\cmd.exe"), "windows_system32_cmd.exe")
        self.assertEqual(sanitize_filename("test\0injection.db"), "testinjection.db")
        self.assertEqual(sanitize_filename("...secret....db"), "secret.db")

        # 2. Safe path resolution
        base_dir = BACKUP_DIR.resolve()

        # Legitimate path inside base_dir
        safe_path = resolve_safe_path(base_dir, "valid_backup.db")
        self.assertTrue(safe_path.is_relative_to(base_dir))

        # Traversal attempts must raise PermissionError
        with self.assertRaises(PermissionError):
            resolve_safe_path(base_dir, "../../../evil.db")

        with self.assertRaises(PermissionError):
            resolve_safe_path(base_dir, "..\\..\\windows\\system32.db")

    # ==========================================================================
    # 3. UPLOAD SIZE & TYPE VALIDATION TESTS
    # ==========================================================================
    def test_upload_size_and_extension_validation(self):
        """Verifies upload limits, extension screening, and non-executable enforcement."""
        # 1. Valid CSV upload
        valid_bytes = b"sku,product_name,category\nSKU-1,Laddoo,Sweets"
        ok, msg = validate_uploaded_file("products.csv", valid_bytes)
        self.assertTrue(ok)

        # 2. Prohibited executable extensions
        for bad_ext in ["malware.exe", "script.bat", "run.sh", "payload.py", "shell.js"]:
            ok, msg = validate_uploaded_file(bad_ext, b"echo test")
            self.assertFalse(ok)
            self.assertIn("prohibited", msg.lower())

        # 3. Empty file
        ok, msg = validate_uploaded_file("empty.csv", b"")
        self.assertFalse(ok)
        self.assertIn("empty", msg.lower())

        # 4. File exceeding max size limit (e.g. 500 KB limit for test)
        large_bytes = b"A" * (600 * 1024)
        ok, msg = validate_uploaded_file("large.csv", large_bytes, max_size_bytes=500 * 1024)
        self.assertFalse(ok)
        self.assertIn("exceeds maximum allowed limit", msg)

    # ==========================================================================
    # 4. INPUT VALIDATION TESTS (MALFORMED INPUTS)
    # ==========================================================================
    def test_input_validation_malformed_inputs(self):
        """Verifies rejection of malformed or invalid business settings, products, and expenses."""
        # 1. Business Settings Validation
        bad_settings = {
            "business_name": "",  # Empty name
            "phone": "123",       # Less than 10 digits
            "email": "invalid_email_format",
            "gstin": "INVALID_GSTIN_LEN"
        }
        ok, errors = validate_business_settings_input(bad_settings)
        self.assertFalse(ok)
        self.assertGreaterEqual(len(errors), 3)

        # 2. Product Validation
        bad_prod = {
            "sku": "BAD SKU WITH SPACES &!@",
            "product_name": "",
            "cost_price": -50.0,   # Negative cost
            "selling_price": 20.0, # Less than cost
            "unit_of_measure": "liters",  # Not in allowed UoM
            "gst_rate": 7.5        # Not in GST_SLABS
        }
        ok, p_errors = validate_product_input(bad_prod)
        self.assertFalse(ok)
        self.assertGreaterEqual(len(p_errors), 4)

        # 3. Expense Validation
        bad_exp = {
            "expense_date": "20-10-2026",  # Non-ISO format
            "category": "ENTERTAINMENT_INVALID",
            "amount": -500.0,  # Negative
            "status": "INVALID_STATUS"
        }
        ok, e_errors = validate_expense_input(bad_exp)
        self.assertFalse(ok)
        self.assertGreaterEqual(len(e_errors), 3)

    # ==========================================================================
    # 5. DATABASE INTEGRITY TESTS
    # ==========================================================================
    def test_database_integrity_check(self):
        """Verifies SQLite PRAGMA integrity_check and foreign_key_check execution."""
        diag = check_database_integrity()
        self.assertTrue(diag["is_healthy"])
        self.assertEqual(diag["integrity_status"], "ok")
        self.assertEqual(diag["foreign_key_violations_count"], 0)
        self.assertGreater(diag["page_count"], 0)
        self.assertGreater(diag["file_size_bytes"], 0)

    # ==========================================================================
    # 6. DATABASE BACKUP & RESTORE TESTS
    # ==========================================================================
    def test_database_backup_creation_and_verification(self):
        """Verifies atomic SQLite backup creation, SHA-256 computation, and integrity verification."""
        meta = create_database_backup(notes="Unit Test Hardening Backup")
        self.assertIn("filename", meta)
        self.assertTrue(Path(meta["filepath"]).exists())
        self.assertGreater(meta["file_size_bytes"], 1024)
        self.assertEqual(len(meta["sha256"]), 64)  # Valid SHA-256 hex string

        # Verify backup file
        is_valid, msg, details = verify_backup_file(Path(meta["filepath"]))
        self.assertTrue(is_valid)
        self.assertEqual(details["integrity"], "PASSED")
        self.assertIn("products", details["record_counts"])

    def test_database_restore_with_confirmation_and_rollback(self):
        """Verifies database restoration, pre-verification rejection of corrupt files, and rollback safety."""
        # 1. Take a baseline backup of current state
        original_settings = get_business_settings()
        original_name = original_settings.get("business_name")

        backup_meta = create_database_backup(notes="Pre-Restore Verification Snapshot")
        backup_file = Path(backup_meta["filepath"])

        # 2. Modify database
        update_business_settings(
            business_name="TEMPORARY MODIFIED STORE NAME 999",
            phone=original_settings.get("phone", "9876543210"),
            address_line1=original_settings.get("address_line1", "Market"),
            city=original_settings.get("city", "Mumbai")
        )
        mod_settings = get_business_settings()
        self.assertEqual(mod_settings["business_name"], "TEMPORARY MODIFIED STORE NAME 999")

        # 3. Attempt restore WITHOUT confirmation -> must fail
        ok, msg = restore_database_backup(backup_file, confirm=False)
        self.assertFalse(ok)
        self.assertIn("confirmation", msg.lower())

        # 4. Attempt restore WITH confirmation -> must succeed
        ok, msg = restore_database_backup(backup_file, confirm=True)
        self.assertTrue(ok)
        self.assertIn("successfully restored", msg.lower())

        # Verify that business name reverted to original
        restored_settings = get_business_settings()
        self.assertEqual(restored_settings["business_name"], original_name)

        # 5. Attempt restore of a CORRUPTED file -> must be rejected during pre-verification
        corrupted_temp = BACKUP_DIR / "corrupted_fake.db"
        with open(corrupted_temp, "wb") as f:
            f.write(b"NOT A SQLITE FILE RANDOM CORRUPTED DATA BYTES 12345")

        ok, msg = restore_database_backup(corrupted_temp, confirm=True)
        self.assertFalse(ok)
        self.assertIn("failed integrity checks", msg.lower())

        # Clean temp corrupt file
        if corrupted_temp.exists():
            corrupted_temp.unlink()

    # ==========================================================================
    # 7. CONFIGURABLE BUSINESS SETTINGS, TIMEZONE & REPORT PREFERENCES
    # ==========================================================================
    def test_configurable_settings_storage_and_retrieval(self):
        """Verifies configurable business name, region, currency display, timezone, and report settings."""
        success = update_business_settings(
            business_name="Hardened Retail Command Co",
            trade_name="FestivePulse Store",
            phone="9876543210",
            email="owner@hardened.local",
            gstin="27AAACR1234M1Z5",
            address_line1="100 Commercial Street",
            city="Pune",
            state="Maharashtra",
            state_code="27",
            pincode="411001",
            primary_region="West",
            timezone="Asia/Kolkata",
            currency_display="INR (₹)",
            report_footer_notes="Confidential Internal Audit Record",
            report_page_orientation="landscape",
            max_upload_size_mb=15
        )
        self.assertTrue(success)

        curr = get_business_settings()
        self.assertEqual(curr["business_name"], "Hardened Retail Command Co")
        self.assertEqual(curr["trade_name"], "FestivePulse Store")
        self.assertEqual(curr["gstin"], "27AAACR1234M1Z5")
        self.assertEqual(curr["primary_region"], "West")
        self.assertEqual(curr["timezone"], "Asia/Kolkata")
        self.assertEqual(curr["currency_display"], "INR (₹)")
        self.assertEqual(curr["report_footer_notes"], "Confidential Internal Audit Record")
        self.assertEqual(curr["report_page_orientation"], "landscape")
        self.assertEqual(curr["max_upload_size_mb"], 15)


if __name__ == "__main__":
    unittest.main()
