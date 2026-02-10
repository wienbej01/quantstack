"""Independent L2 symbol selection."""

import glob
import hashlib
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


class L2SymbolSelector:
    """Independent symbol selection for L2 collection."""

    # Known ARCA ETFs - excluded when nyse_only=true
    KNOWN_ARCA = {"UNG", "SPY", "QQQ", "IWM", "EFA", "EEM", "GLD", "SLV", "TLT", "HYG"}

    def __init__(self, config: dict):
        symbols_cfg = config.get("symbols", {})
        self.mode = symbols_cfg.get("mode", "hybrid")
        self.core_symbols = symbols_cfg.get("core", [])
        self.rotating_pool = symbols_cfg.get("rotating_pool", [])
        self.max_symbols = symbols_cfg.get("max_symbols", 6)
        self.nyse_only = symbols_cfg.get("nyse_only", False)
        self._external_symbols: Optional[list[str]] = None
        self.sip_source = symbols_cfg.get("sip_source")
        self.sip_fallback = symbols_cfg.get("sip_fallback")
        self.sip_required = symbols_cfg.get("sip_required", True)
        schedule_cfg = config.get("schedule", {})
        self.timezone = (
            symbols_cfg.get("timezone")
            or schedule_cfg.get("timezone")
            or "America/New_York"
        )

        storage_cfg = config.get("storage", {})
        default_root = Path(
            os.environ.get("L2_DATA_ROOT", "/home/jacobw/quantstack/data/l2")
        ).expanduser()
        default_base = default_root / "l2"
        self.log_dir = Path(storage_cfg.get("base_dir", default_base)) / "selection_log"

    def get_symbols(self, date_str: str = None) -> list[str]:
        """Get symbols for collection based on mode."""
        if date_str is None:
            date_str = self._current_date_str()

        if self.mode == "static":
            symbols = self._get_static()
        elif self.mode == "rotating":
            symbols = self._get_rotating(date_str)
        elif self.mode == "hybrid":
            symbols = self._get_hybrid(date_str)
        elif self.mode == "external":
            symbols = self._get_external()
        elif self.mode == "sip_dynamic":
            symbols = self._get_sip_dynamic(date_str)
        else:
            logger.warning(f"Unknown mode '{self.mode}', using static")
            symbols = self._get_static()

        self._log_selection(date_str, symbols)
        return symbols

    def _get_static(self) -> list[str]:
        """Static: use core symbols only."""
        return self.core_symbols[: self.max_symbols]

    def _get_rotating(self, date_str: str) -> list[str]:
        """Rotating: round-robin through pool."""
        if not self.rotating_pool:
            return self.core_symbols[: self.max_symbols]

        # Deterministic rotation based on date
        day_hash = self._stable_hash(date_str) % len(self.rotating_pool)
        rotated = self.rotating_pool[day_hash:] + self.rotating_pool[:day_hash]
        return rotated[: self.max_symbols]

    def _get_hybrid(self, date_str: str) -> list[str]:
        """Hybrid: core symbols + rotating from pool."""
        symbols = list(self.core_symbols)

        if self.rotating_pool:
            # Exclude core from rotating pool
            available = [s for s in self.rotating_pool if s not in self.core_symbols]
            if available:
                day_hash = self._stable_hash(date_str) % len(available)
                rotated = available[day_hash:] + available[:day_hash]
                remaining = self.max_symbols - len(symbols)
                symbols.extend(rotated[:remaining])

        return symbols[: self.max_symbols]

    def _get_external(self) -> list[str]:
        """External: use injected symbols."""
        if self._external_symbols:
            return self._external_symbols[: self.max_symbols]
        return self.core_symbols[: self.max_symbols]

    def _get_sip_dynamic(self, date_str: str) -> list[str]:
        """SIP dynamic: load symbols from daily SIP artifacts."""
        symbols = self._load_sip_symbols(date_str)
        if not symbols:
            message = f"SIP universe not found for {date_str}"
            if self.sip_required:
                raise RuntimeError(message)
            logger.warning(message)
            return []

        # Filter for NYSE-only if configured
        if self.nyse_only:
            filtered = [s for s in symbols if s not in self.KNOWN_ARCA]
            logger.info(f"NYSE filter: {len(symbols)} -> {len(filtered)} symbols (excluded ARCA: {[s for s in symbols if s in self.KNOWN_ARCA]})")
            symbols = filtered

        return symbols[: self.max_symbols]

    def set_external_symbols(self, symbols: list[str]):
        """Inject external symbols (e.g., from SIP)."""
        self._external_symbols = symbols
        logger.info(f"External symbols set: {symbols}")

    def _current_date_str(self) -> str:
        try:
            tz = ZoneInfo(self.timezone)
        except Exception:
            logger.warning(
                "Invalid timezone %s; defaulting to America/New_York",
                self.timezone,
            )
            tz = ZoneInfo("America/New_York")
        return datetime.now(tz).strftime("%Y-%m-%d")

    def _load_sip_symbols(self, date_str: str) -> list[str]:
        for pattern in (self.sip_source, self.sip_fallback):
            if not pattern:
                continue
            sip_path = self._resolve_sip_path(pattern, date_str)
            if not sip_path or not sip_path.exists():
                continue
            try:
                with open(sip_path, "r") as f:
                    data = json.load(f)
            except Exception as exc:
                logger.warning("Failed to load SIP universe from %s: %s", sip_path, exc)
                continue

            if isinstance(data, dict):
                artifact_date = data.get("date")
                if artifact_date and artifact_date != date_str:
                    logger.warning(
                        "SIP artifact date mismatch: file=%s expected=%s",
                        artifact_date,
                        date_str,
                    )
                    continue
                symbols = data.get("symbols", [])
            else:
                symbols = data

            if symbols:
                logger.info("Loaded %s SIP symbols from %s", len(symbols), sip_path)
                return symbols

        return []

    @staticmethod
    def _resolve_sip_path(pattern: str, date_str: str) -> Optional[Path]:
        if "date=*" in pattern:
            return Path(pattern.replace("date=*", f"date={date_str}"))
        if any(char in pattern for char in ("*", "?", "[")):
            matches = [Path(path) for path in sorted(glob.glob(pattern))]
            if not matches:
                return None
            dated = [path for path in matches if f"date={date_str}" in str(path)]
            return dated[0] if dated else None
        return Path(pattern)

    @staticmethod
    def _stable_hash(value: str) -> int:
        """Stable hash for deterministic rotations."""
        digest = hashlib.md5(value.encode("utf-8")).hexdigest()
        return int(digest, 16)

    def _log_selection(self, date_str: str, symbols: list[str]):
        """Log symbol selection for tracking."""
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            log_file = self.log_dir / f"{date_str}.json"

            selection = {
                "date": date_str,
                "timestamp": datetime.now().isoformat(),
                "mode": self.mode,
                "symbols": symbols,
                "core": [s for s in symbols if s in self.core_symbols],
                "rotating": [s for s in symbols if s not in self.core_symbols],
            }

            with open(log_file, "w") as f:
                json.dump(selection, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to log selection: {e}")
