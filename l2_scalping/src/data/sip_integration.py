"""SIP Universe Integration for L2 Scalping System

Reads the same daily SIP ticker list used by l2-collector.
"""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def _sip_daily_root() -> Path:
    return Path(
        os.environ.get("SIP_DAILY_ROOT", "/home/jacobw/intraday_stack/data/daily_sip")
    )


def _latest_sip_date(root: Path) -> str | None:
    date_dirs = sorted(root.glob("date=*"))
    if not date_dirs:
        return None
    return date_dirs[-1].name.split("date=")[-1]


def load_daily_sip_symbols(date_str: str | None = None) -> list[str]:
    """Load daily SIP symbols from shared daily_sip JSON artifacts.

    If date_str is provided, uses that specific date.
    Otherwise, finds the most recent SIP file.
    """
    sip_dir = _sip_daily_root()
    if date_str is None:
        date_str = _latest_sip_date(sip_dir)
        if date_str is None:
            logger.warning("No SIP universe files found")
            return []

    sip_file = sip_dir / f"date={date_str}" / "sip_universe.json"

    try:
        with open(sip_file) as f:
            data = json.load(f)
        symbols = data.get("symbols", []) if isinstance(data, dict) else data
        logger.info(f"Loaded {len(symbols)} symbols from {sip_file}")
        return symbols
    except FileNotFoundError:
        logger.error(f"SIP file not found: {sip_file}")
        return []
    except Exception as e:
        logger.error(f"Error loading SIP symbols: {e}")
        return []


def get_scalping_symbols(max_symbols: int = 3) -> list[str]:
    """Get NYSE symbols for scalping from daily SIP list

    Uses all symbols from SIP file that qualify, but filters for NYSE only
    since L2 data subscription is NYSE-only.
    
    If no NYSE symbols qualify, returns empty list - system should not trade.

    Raises RuntimeError if no SIP file found.
    """

    sip_symbols = load_daily_sip_symbols()

    if not sip_symbols:
        raise RuntimeError(
            "No SIP universe found! Run generate_daily_sip_universe.py before market open. "
            "System will not trade without valid SIP list."
        )

    # Filter for NYSE symbols only (L2 data subscription requirement)
    nyse_symbols = []
    
    # Quick exchange check using known NYSE vs ARCA symbols
    known_nyse = {'SMR', 'VST', 'INSM', 'F', 'GE', 'BAC', 'C', 'JPM', 'WFC', 'XOM', 'CVX'}
    known_arca = {'UNG', 'SPY', 'QQQ', 'IWM', 'EFA', 'EEM', 'GLD', 'SLV', 'TLT', 'HYG'}
    
    for symbol in sip_symbols:
        if symbol in known_nyse:
            nyse_symbols.append(symbol)
        elif symbol not in known_arca:
            # Default to NYSE for unknown symbols (most stocks trade on NYSE)
            nyse_symbols.append(symbol)
        # Skip known ARCA symbols

    if not nyse_symbols:
        logger.warning("No NYSE symbols in SIP universe - L2 scalping will not trade")
        return []

    logger.info(
        f"Filtered {len(nyse_symbols)} NYSE symbols from {len(sip_symbols)} SIP symbols: {nyse_symbols}"
    )
    return nyse_symbols
