"""
FestivePulse — Reorder & Procurement Advisor (Compatibility Layer)
Delegates to services.stock_planning_service for transparent,
deterministic festival stock planning and purchase calculations.
100% Non-AI.
"""

from typing import Dict, Any, List, Optional
import pandas as pd
from services.stock_planning_service import (
    compute_product_stock_plan,
    generate_festival_stock_plan_table
)


def get_stock_recommendation_for_product(
    product_id: int,
    occurrence_id: int,
    growth_multiplier: float = 1.10
) -> Dict[str, Any]:
    """
    Computes deterministic procurement recommendations for a single product.
    Formula: max(0, planned demand + safety stock - usable stock)
    """
    return compute_product_stock_plan(
        product_id=product_id,
        occurrence_id=occurrence_id,
        growth_multiplier=growth_multiplier
    )


def generate_festival_procurement_worksheet(
    occurrence_id: int,
    growth_multiplier: float = 1.10,
    only_order_required: bool = False,
    purchasing_budget: float = 500000.0,
    selected_product_ids: Optional[List[int]] = None
) -> pd.DataFrame:
    """
    Generates the procurement worksheet for all selected products.
    """
    df, _ = generate_festival_stock_plan_table(
        occurrence_id=occurrence_id,
        purchasing_budget=purchasing_budget,
        selected_product_ids=selected_product_ids,
        growth_multiplier=growth_multiplier
    )
    if only_order_required and not df.empty:
        df = df[df["recommended_order_quantity"] > 0]
    return df
