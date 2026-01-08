"""SIP selector aligned to shared daily_sip JSON artifacts."""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional


class PolygonSIPSelector:
    """SIP universe selection via shared daily_sip artifacts."""

    def __init__(self, api_key: Optional[str] = None):
        self.logger = logging.getLogger(__name__)

    def _sip_daily_root(self) -> Path:
        return Path(
            os.environ.get(
                "SIP_DAILY_ROOT", "/home/jacobw/intraday_stack/data/daily_sip"
            )
        )

    def _latest_sip_date(self, root: Path) -> str | None:
        date_dirs = sorted(root.glob("date=*"))
        if not date_dirs:
            return None
        return date_dirs[-1].name.split("date=")[-1]

    def get_sip_universe(self, top_k: int = 40, score_floor: float = 0.01) -> list[str]:
        """Load SIP universe from shared daily_sip JSON artifacts."""
        root = self._sip_daily_root()
        date_str = datetime.now().strftime("%Y-%m-%d")
        sip_file = root / f"date={date_str}" / "sip_universe.json"

        if not sip_file.exists():
            latest = self._latest_sip_date(root)
            if not latest:
                raise RuntimeError(f"No SIP universe files found in {root}")
            sip_file = root / f"date={latest}" / "sip_universe.json"

        with open(sip_file) as f:
            data = json.load(f)

        symbols = data.get("symbols", []) if isinstance(data, dict) else data
        scores = data.get("scores", {}) if isinstance(data, dict) else {}

        if scores:
            symbols = [sym for sym in symbols if scores.get(sym, 0.0) >= score_floor]
        if top_k > 0:
            symbols = symbols[:top_k]

        self.logger.info(f"Loaded {len(symbols)} SIP symbols from {sip_file}")
        return symbols

    def get_nyse_symbols(self, sip_universe: list[str]) -> list[str]:
        """Return top 6 NYSE symbols for L2 collection."""
        selected = sip_universe[:6]  # Top 6 highest scoring
        self.logger.info(f"L2 symbols (top 6 SIP): {selected}")
        return selected
