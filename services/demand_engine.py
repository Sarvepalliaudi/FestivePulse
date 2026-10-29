"""
FestivePulse — Demand Estimation Engine (Compatibility Layer)
Re-routes demand estimation requests to the transparent, auditable
services.demand_estimation_service.
Strictly non-AI, mathematically documented, operations-research grounded.
"""

from typing import Dict, Any, Optional
import pandas as pd
from services.demand_estimation_service import (
    estimate_product_demand as _service_estimate_product_demand,
    generate_demand_forecast_table as _service_generate_forecast_table
)


def estimate_product_demand(
    product_id: int,
    target_occurrence_id: int,
    growth_multiplier: float = 1.10,
    manual_daily_estimate: Optional[float] = None,
    trim_spikes: bool = False
) -> Dict[str, Any]:
    """
    Deterministically and transparently estimates festival demand for a product.
    Delegates to the auditable Demand Estimation Service.
    """
    return _service_estimate_product_demand(
        product_id=product_id,
        target_occurrence_id=target_occurrence_id,
        growth_multiplier=growth_multiplier,
        manual_daily_estimate=manual_daily_estimate,
        trim_spikes=trim_spikes
    )


def generate_festival_demand_forecast_table(
    occurrence_id: int,
    category_id: Optional[int] = None,
    growth_multiplier: float = 1.10,
    trim_spikes: bool = False,
    manual_overrides: Optional[Dict[int, float]] = None
) -> pd.DataFrame:
    """
    Generates a complete auditable demand forecast table across festival products.
    """
    return _service_generate_forecast_table(
        target_occurrence_id=occurrence_id,
        category_id=category_id,
        growth_multiplier=growth_multiplier,
        trim_spikes=trim_spikes,
        manual_overrides=manual_overrides
    )
