"""
FestivePulse — Expense Repository
Parameterized queries and persistence for operating expenses, festival attribution, and P&L inputs.
Supports edit, correction, and cancellation audit trails.
"""

import json
from typing import List, Dict, Any, Optional
from database.connection import get_db_connection, db_session


class ExpenseRepository:

    @staticmethod
    def create_expense(
        expense_category: str,
        expense_date: str,
        amount: float,
        payment_mode: str = "CASH",
        occurrence_id: Optional[int] = None,
        vendor_name: Optional[str] = None,
        invoice_receipt_no: Optional[str] = None,
        notes: Optional[str] = None,
        description: Optional[str] = None,
        created_by: str = "User"
    ) -> int:
        desc = description or notes or "Expense"
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO expenses (
                    expense_category, occurrence_id, expense_date, amount,
                    payment_mode, vendor_name, invoice_receipt_no, description, notes, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE')
            """, (
                expense_category, occurrence_id, expense_date, float(amount),
                payment_mode, vendor_name, invoice_receipt_no, desc, notes or desc
            ))
            exp_id = cursor.lastrowid

            snapshot = {
                "expense_id": exp_id,
                "category": expense_category,
                "amount": float(amount),
                "expense_date": expense_date,
                "occurrence_id": occurrence_id,
                "description": desc,
                "payment_mode": payment_mode,
                "vendor_name": vendor_name,
                "invoice_receipt_no": invoice_receipt_no
            }
            cursor.execute("""
                INSERT INTO expense_audit_logs (expense_id, action, changed_by, new_values, reason)
                VALUES (?, 'CREATE', ?, ?, 'Initial creation')
            """, (exp_id, created_by, json.dumps(snapshot)))

            return exp_id

    @staticmethod
    def get_expenses(
        occurrence_id: Optional[int] = None,
        category: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        include_cancelled: bool = False,
        limit: int = 200
    ) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            sql = """
                SELECT e.*, f.festival_name, o.year
                FROM expenses e
                LEFT JOIN festival_occurrences o ON e.occurrence_id = o.occurrence_id
                LEFT JOIN festivals f ON o.festival_id = f.festival_id
                WHERE 1=1
            """
            params: List[Any] = []
            if not include_cancelled:
                sql += " AND e.status != 'CANCELLED'"
            if occurrence_id is not None:
                sql += " AND e.occurrence_id = ?"
                params.append(occurrence_id)
            if category:
                sql += " AND e.expense_category = ?"
                params.append(category)
            if start_date:
                sql += " AND e.expense_date >= ?"
                params.append(start_date)
            if end_date:
                sql += " AND e.expense_date <= ?"
                params.append(end_date)

            sql += " ORDER BY e.expense_date DESC, e.expense_id DESC LIMIT ?"
            params.append(limit)
            cursor.execute(sql, tuple(params))
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def get_expense_by_id(expense_id: int) -> Optional[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM expenses WHERE expense_id = ?", (expense_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def update_expense(
        expense_id: int,
        reason: str,
        amount: Optional[float] = None,
        expense_date: Optional[str] = None,
        category: Optional[str] = None,
        description: Optional[str] = None,
        occurrence_id: Optional[int] = None,
        payment_mode: Optional[str] = None,
        vendor_name: Optional[str] = None,
        invoice_receipt_no: Optional[str] = None,
        changed_by: str = "User"
    ) -> bool:
        from services.expense_service import edit_expense
        return edit_expense(
            expense_id=expense_id,
            reason=reason,
            amount=amount,
            expense_date=expense_date,
            category=category,
            description=description,
            occurrence_id=occurrence_id,
            payment_mode=payment_mode,
            vendor_name=vendor_name,
            invoice_receipt_no=invoice_receipt_no,
            changed_by=changed_by
        )

    @staticmethod
    def cancel_expense(expense_id: int, reason: str, cancelled_by: str = "User") -> bool:
        from services.expense_service import cancel_expense
        return cancel_expense(expense_id, reason, cancelled_by)

    @staticmethod
    def delete_expense(expense_id: int) -> bool:
        """Preserves backwards compatibility for hard deletion when required in test tearDowns."""
        sql = "DELETE FROM expenses WHERE expense_id = ?"
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (expense_id,))
            return cursor.rowcount > 0

    @staticmethod
    def get_expense_totals(occurrence_id: Optional[int] = None) -> float:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            sql = "SELECT COALESCE(SUM(amount), 0) FROM expenses WHERE status != 'CANCELLED'"
            params: List[Any] = []
            if occurrence_id is not None:
                sql += " AND occurrence_id = ?"
                params.append(occurrence_id)
            cursor.execute(sql, tuple(params))
            return float(cursor.fetchone()[0] or 0.0)
        finally:
            conn.close()
