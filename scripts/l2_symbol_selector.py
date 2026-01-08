#!/usr/bin/env python3
"""L2 symbol selection strategy for IBKR 3-symbol limit compliance."""

import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def _sip_daily_root() -> Path:
    return Path(
        os.environ.get("SIP_DAILY_ROOT", "/home/jacobw/intraday_stack/data/daily_sip")
    )


def _current_date_str() -> str:
    return datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")


def load_daily_sip_universe() -> list[str]:
    """
    Load today's SIP universe from daily SIP files.
    Returns symbols ranked by HMM score (highest first).
    """
    sip_dir = _sip_daily_root()
    date_str = _current_date_str()
    sip_file = sip_dir / f"date={date_str}" / "sip_universe.json"

    if not sip_file.exists():
        print(f"Warning: SIP universe not found for {date_str}: {sip_file}")
        return []

    try:
        with open(sip_file, "r") as f:
            data = json.load(f)
        artifact_date = data.get("date") if isinstance(data, dict) else None
        if artifact_date and artifact_date != date_str:
            print(
                f"Warning: SIP artifact date mismatch (file={artifact_date}, "
                f"expected={date_str})"
            )
            return []
        symbols = data.get("symbols", []) if isinstance(data, dict) else data
        print(f"Loaded {len(symbols)} symbols from {sip_file}")
        return symbols
    except FileNotFoundError:
        print(f"Warning: Could not load SIP universe from {sip_file}")
        return []


def get_l2_symbols(sip_universe: list[str] = None) -> list[str]:
    """
    Select symbols for L2 collection using top-3 strategy:
    - IBKR account limit: 3 concurrent L2 depth subscriptions (Error 309)
    - Strategy: Select top 3 symbols from daily SIP universe
    - Rotation: Automatic 5-minute rotation through top symbols for broader coverage
    """

    # Load SIP universe if not provided
    if sip_universe is None:
        sip_universe = load_daily_sip_universe()

    if not sip_universe:
        print("Warning: No SIP universe available, using emergency fallback symbols")
        # Emergency fallback - high liquidity NYSE symbols
        return ["HAL", "PFE", "JPM"]

    # Take top 3 symbols from SIP universe (already ranked by HMM score)
    top_3_symbols = sip_universe[:3] if len(sip_universe) >= 3 else sip_universe

    # Ensure we have exactly 3 symbols (pad with next best if needed)
    if len(top_3_symbols) < 3:
        remaining_symbols = sip_universe[len(top_3_symbols) :]
        for symbol in remaining_symbols:
            if len(top_3_symbols) >= 3:
                break
            top_3_symbols.append(symbol)

    return top_3_symbols[:3]  # Ensure exactly 3 symbols


def get_rotation_pool(sip_universe: list[str] = None, pool_size: int = 15) -> list[str]:
    """
    Get rotation pool for 5-minute symbol rotation.
    Returns top 15 symbols from daily SIP for rotation through 3-symbol slots.
    """
    if sip_universe is None:
        sip_universe = load_daily_sip_universe()

    return sip_universe[:pool_size] if len(sip_universe) >= pool_size else sip_universe


def save_l2_symbols(l2_symbols: list[str]):
    """Save L2 symbols to daily file for L2 collector to read."""
    date_str = _current_date_str()
    l2_file = Path(f"data/daily_sip/l2_symbols_{date_str}.txt")

    # Ensure directory exists
    l2_file.parent.mkdir(parents=True, exist_ok=True)

    with open(l2_file, "w") as f:
        for symbol in l2_symbols:
            f.write(f"{symbol}\n")

    print(f"Saved L2 symbols to: {l2_file}")
    return l2_file


def log_symbol_selection(
    l2_symbols: list[str], sip_universe: list[str], rotation_pool: list[str] = None
):
    """Log symbol selection for tracking."""
    log_dir = Path("data/l2_selection_log")
    log_dir.mkdir(parents=True, exist_ok=True)

    date_str = _current_date_str()
    log_file = log_dir / f"{date_str}.json"

    selection = {
        "date": date_str,
        "timestamp": datetime.now().isoformat(),
        "strategy": "top_3_rotation",
        "ibkr_limit": 3,
        "l2_symbols": l2_symbols,
        "rotation_pool": rotation_pool or sip_universe[:15],
        "sip_universe_size": len(sip_universe),
        "total_l2_symbols": len(l2_symbols),
        "compliance_note": "IBKR Error 309 - Max 3 concurrent L2 depth subscriptions",
        "data_source": "daily_sip_dynamic",
    }

    with open(log_file, "w") as f:
        json.dump(selection, f, indent=2)

    return selection


if __name__ == "__main__":
    # Load today's SIP universe dynamically
    sip_universe = load_daily_sip_universe()

    if not sip_universe:
        print("No SIP universe found - using example data for testing")
        sip_universe = [
            "MOS",
            "ACHR",
            "CRGY",
            "FCX",
            "AA",
            "T",
            "VZ",
            "HPE",
            "HAL",
            "PFE",
            "JPM",
            "XOM",
            "BAC",
            "WMT",
            "JNJ",
            "CVX",
            "HD",
            "KO",
            "PEP",
            "MCD",
            "CAT",
            "DE",
            "BA",
            "GE",
        ]

    # Select L2 symbols and rotation pool
    l2_symbols = get_l2_symbols(sip_universe)
    rotation_pool = get_rotation_pool(sip_universe)

    print(f"SIP Universe size: {len(sip_universe)}")
    print(f"L2 symbols (IBKR limit: 3): {l2_symbols}")
    print(f"Rotation pool (15): {rotation_pool}")
    print(f"Strategy: Top-3 with 5-minute rotation for broader coverage")

    # Save L2 symbols for collector to read
    save_l2_symbols(l2_symbols)

    # Log the selection
    selection = log_symbol_selection(l2_symbols, sip_universe, rotation_pool)
    print(f"\nLogged selection to: data/l2_selection_log/{selection['date']}.json")
    print(f"Compliance: {selection['compliance_note']}")
