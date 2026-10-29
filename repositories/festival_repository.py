"""
FestivePulse — Festival Repository
Parameterized queries and transactions for festival definitions, occurrences, and targets.
"""

import json
from typing import List, Dict, Any, Optional
from database.connection import get_db_connection, db_session


class FestivalRepository:

    @staticmethod
    def get_all_festivals(only_active: bool = True) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            if only_active:
                cursor.execute("SELECT * FROM festivals WHERE is_active = 1 ORDER BY festival_name ASC")
            else:
                cursor.execute("SELECT * FROM festivals ORDER BY festival_name ASC")
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def get_festival_by_id(festival_id: int) -> Optional[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM festivals WHERE festival_id = ?", (festival_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def get_festival_by_code(code: str) -> Optional[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM festivals WHERE festival_code = ?", (code.strip().upper(),))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def create_festival(
        festival_code: str,
        festival_name: str,
        primary_regions: List[str],
        typical_surge_multiplier: float = 2.50,
        preparation_lead_days: int = 30
    ) -> int:
        sql = """
            INSERT INTO festivals (
                festival_code, festival_name, primary_regions,
                typical_surge_multiplier, preparation_lead_days, is_active
            ) VALUES (?, ?, ?, ?, ?, 1)
        """
        params = (
            festival_code.strip().upper(),
            festival_name.strip(),
            json.dumps(primary_regions),
            float(typical_surge_multiplier),
            int(preparation_lead_days)
        )
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return cursor.lastrowid

    @staticmethod
    def get_occurrences(year: Optional[int] = None, active_only: bool = False) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            sql = """
                SELECT o.*, f.festival_name, f.festival_code, f.typical_surge_multiplier
                FROM festival_occurrences o
                JOIN festivals f ON o.festival_id = f.festival_id
            """
            conditions = []
            params = []
            if year:
                conditions.append("o.year = ?")
                params.append(year)
            if active_only:
                conditions.append("o.is_current_active = 1")

            if conditions:
                sql += " WHERE " + " AND ".join(conditions)

            sql += " ORDER BY o.year DESC, o.festival_date ASC"
            cursor.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def get_occurrence_by_id(occurrence_id: int) -> Optional[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            sql = """
                SELECT o.*, f.festival_name, f.festival_code, f.typical_surge_multiplier
                FROM festival_occurrences o
                JOIN festivals f ON o.festival_id = f.festival_id
                WHERE o.occurrence_id = ?
            """
            cursor.execute(sql, (occurrence_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def get_active_occurrence() -> Optional[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            sql = """
                SELECT o.*, f.festival_name, f.festival_code, f.typical_surge_multiplier, f.primary_regions
                FROM festival_occurrences o
                JOIN festivals f ON o.festival_id = f.festival_id
                WHERE o.is_current_active = 1
                LIMIT 1
            """
            cursor.execute(sql)
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @staticmethod
    def set_active_occurrence(occurrence_id: int) -> bool:
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE festival_occurrences SET is_current_active = 0")
            cursor.execute("UPDATE festival_occurrences SET is_current_active = 1 WHERE occurrence_id = ?", (occurrence_id,))
            return cursor.rowcount > 0

    @staticmethod
    def create_occurrence(data: Dict[str, Any]) -> int:
        sql = """
            INSERT INTO festival_occurrences (
                festival_id, year, prep_start_date, campaign_start_date,
                peak_start_date, festival_date, campaign_end_date, notes, is_current_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            int(data["festival_id"]),
            int(data["year"]),
            data["prep_start_date"],
            data["campaign_start_date"],
            data["peak_start_date"],
            data["festival_date"],
            data["campaign_end_date"],
            data.get("notes", ""),
            1 if data.get("is_current_active") else 0
        )
        with db_session() as conn:
            cursor = conn.cursor()
            if data.get("is_current_active"):
                cursor.execute("UPDATE festival_occurrences SET is_current_active = 0")
            cursor.execute(sql, params)
            return cursor.lastrowid

    @staticmethod
    def upsert_target(
        occurrence_id: int,
        category_id: int,
        target_revenue: float,
        target_profit: float = 0.0,
        budgeted_expenses: float = 0.0
    ) -> bool:
        sql = """
            INSERT INTO festival_sales_targets (
                occurrence_id, category_id, target_revenue, target_profit, budgeted_expenses
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(occurrence_id, category_id) DO UPDATE SET
                target_revenue = excluded.target_revenue,
                target_profit = excluded.target_profit,
                budgeted_expenses = excluded.budgeted_expenses
        """
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (occurrence_id, category_id, target_revenue, target_profit, budgeted_expenses))
            return cursor.rowcount > 0
