"""Utility functions for CPAPI order handling."""

def round_to_tick_size(price: float, tick_size: float = 0.01) -> float:
    """
    Round price to nearest tick size.
    
    Args:
        price: Price to round
        tick_size: Minimum price increment (default 0.01 for stocks)
    
    Returns:
        Price rounded to nearest tick
    """
    return round(price / tick_size) * tick_size
