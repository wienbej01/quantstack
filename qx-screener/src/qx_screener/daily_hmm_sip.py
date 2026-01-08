import json
import os
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from .hmm_sip import HMMSIPConfig, HMMSIPUniverseSelector


class DailyHMMSIPSelector:
    def __init__(
        self,
        score_floor: float = 0.0,
        top_k: int = 40,
        broadcast_time: str = "09:30:00",
    ):
        self.score_floor = score_floor
        self.top_k = top_k
        self.broadcast_time = datetime.strptime(broadcast_time, "%H:%M:%S").time()
        self._daily_universes: dict[date, set[str]] = {}
        # Create a default config for the base selector
        config = HMMSIPConfig(score_floor=score_floor, top_k=top_k)
        self._base_selector = HMMSIPUniverseSelector(config)

    def _sip_daily_root(self) -> Path:
        return Path(
            os.environ.get(
                "SIP_DAILY_ROOT", "/home/jacobw/intraday_stack/data/daily_sip"
            )
        )

    def _load_daily_symbols(self, date_str: str) -> list[str]:
        sip_file = self._sip_daily_root() / f"date={date_str}" / "sip_universe.json"
        if not sip_file.exists():
            return []

        with open(sip_file) as f:
            data = json.load(f)
        symbols = data.get("symbols", []) if isinstance(data, dict) else data
        scores = data.get("scores", {}) if isinstance(data, dict) else {}

        if scores and self.score_floor > 0:
            symbols = [
                sym for sym in symbols if scores.get(sym, 0.0) >= self.score_floor
            ]

        if self.top_k > 0:
            symbols = symbols[: self.top_k]

        return symbols

    def select_daily_universes(self, bars_utc: pd.DataFrame) -> dict[date, set[str]]:
        """Select universe for each trading day using shared daily_sip JSON."""
        # Group bars by date (convert integer nanosecond timestamps to datetime)
        bars_utc["date"] = pd.to_datetime(bars_utc["ts"], unit="ns").dt.date
        daily_groups = bars_utc.groupby("date")

        for trading_date, day_bars in daily_groups:
            date_str = trading_date.strftime("%Y-%m-%d")
            symbols = self._load_daily_symbols(date_str)
            self._daily_universes[trading_date] = set(symbols)

        return self._daily_universes

    def is_symbol_eligible(self, symbol: str, timestamp: datetime) -> bool:
        """Check if symbol is eligible at given timestamp"""
        trading_date = timestamp.date()
        if trading_date not in self._daily_universes:
            return False

        return symbol in self._daily_universes[trading_date]

    def get_universe_for_timestamp(self, timestamp: datetime) -> set[str]:
        """Get universe for specific timestamp (broadcasts daily universe to all intraday times)"""
        trading_date = timestamp.date()
        return self._daily_universes.get(trading_date, set())
