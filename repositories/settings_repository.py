"""
FestivePulse — Settings Repository
Parameterized queries and persistence for store profile and application settings.
"""

from typing import Dict, Any
from database.connection import get_db_connection, db_session


class SettingsRepository:

    @staticmethod
    def get_settings() -> Dict[str, Any]:
        """
        Retrieves the business configuration singleton row.
        """
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM business_settings WHERE setting_id = 1")
            row = cursor.fetchone()
            if row:
                return dict(row)
            return {}
        finally:
            conn.close()

    @staticmethod
    def update_settings(data: Dict[str, Any]) -> bool:
        """
        Updates the business settings singleton record.
        """
        sql = """
            UPDATE business_settings
            SET business_name = ?,
                trade_name = ?,
                phone = ?,
                email = ?,
                gstin = ?,
                address_line1 = ?,
                address_line2 = ?,
                city = ?,
                pincode = ?,
                state = ?,
                state_code = ?,
                primary_region = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE setting_id = 1
        """
        params = (
            data.get("business_name", ""),
            data.get("trade_name", ""),
            data.get("phone", ""),
            data.get("email", ""),
            data.get("gstin", ""),
            data.get("address_line1", ""),
            data.get("address_line2", ""),
            data.get("city", ""),
            data.get("pincode", ""),
            data.get("state", "Maharashtra"),
            data.get("state_code", "27"),
            data.get("primary_region", "West")
        )
        with db_session() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return cursor.rowcount > 0
