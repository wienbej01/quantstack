"""Daily SIP universe loader.

Loads daily stock selection universe from ~/intraday_stack/data/daily_sip/.
Data is organized as: date={YYYY-MM-DD}/sip_universe.json

Example: ~/intraday_stack/data/daily_sip/date=2024-01-19/sip_universe.json

JSON format:
{
    "date": "2024-01-19",
    "timestamp": "2025-12-22T16:32:27.729549+00:00",
    "symbols": ["KEY", "RF", "USB", ...]
}
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


class SipLoader:
    """Load daily SIP universe from intraday_stack data store."""

    # Base path for SIP data
    DEFAULT_SIP_PATH = Path("~/intraday_stack/data/daily_sip").expanduser()

    def __init__(self, sip_path: Optional[Path] = None):
        """Initialize loader with optional custom path.

        Args:
            sip_path: Path to SIP data store. Defaults to ~/intraday_stack/data/daily_sip
        """
        self.sip_path = sip_path or self.DEFAULT_SIP_PATH

        if not self.sip_path.exists():
            logger.warning(f"SIP path not found: {self.sip_path}")

    def load_universe(self, date: str) -> List[str]:
        """Load SIP universe for a specific date.

        Args:
            date: Date in YYYY-MM-DD format

        Returns:
            List of symbol strings (e.g., ["AAPL", "MSFT", "SPY", ...])

        Raises:
            FileNotFoundError: If SIP file not found for date
            ValueError: If date format is invalid or JSON is malformed
        """
        # Validate date format
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError as e:
            raise ValueError(f"Invalid date format. Use YYYY-MM-DD: {e}")

        # Construct file path
        file_path = self.sip_path / f"date={date}" / "sip_universe.json"

        if not file_path.exists():
            raise FileNotFoundError(
                f"SIP file not found: {file_path}. "
                f"Date {date} may not exist in SIP data."
            )

        try:
            with open(file_path, 'r') as f:
                data = json.load(f)

            # Validate structure
            if "symbols" not in data:
                raise ValueError(f"Invalid SIP JSON: missing 'symbols' key in {file_path}")

            symbols = data["symbols"]

            # Validate symbols is a list of strings
            if not isinstance(symbols, list):
                raise ValueError(f"Invalid SIP JSON: 'symbols' must be a list in {file_path}")

            # Filter out any non-string or empty symbols
            symbols = [s for s in symbols if isinstance(s, str) and s.strip()]

            if not symbols:
                logger.warning(f"Empty symbols list for date {date}")

            logger.info(f"Loaded {len(symbols)} symbols from SIP for {date}")

            return symbols

        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in {file_path}: {e}")
        except Exception as e:
            raise RuntimeError(f"Error loading SIP file {file_path}: {e}")

    def load_universe_multi(self, dates: List[str]) -> pd.DataFrame:
        """Load SIP universe for multiple dates.

        Args:
            dates: List of dates in YYYY-MM-DD format

        Returns:
            DataFrame with columns: date, symbol
            One row per (date, symbol) combination
        """
        all_rows = []

        for date in dates:
            try:
                symbols = self.load_universe(date)
                for symbol in symbols:
                    all_rows.append({"date": date, "symbol": symbol})
            except FileNotFoundError as e:
                logger.warning(f"Skipping {date}: {e}")
            except Exception as e:
                logger.error(f"Error loading {date}: {e}")

        if not all_rows:
            return pd.DataFrame(columns=["date", "symbol"])

        df = pd.DataFrame(all_rows)
        df = df.sort_values(["date", "symbol"]).reset_index(drop=True)

        logger.info(f"Loaded {len(df)} symbol-date combinations for {len(dates)} dates")

        return df

    def load_universe_range(
        self,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """Load SIP universe for a date range.

        Args:
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format

        Returns:
            DataFrame with columns: date, symbol
        """
        # Generate list of business days in range
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError as e:
            raise ValueError(f"Invalid date format. Use YYYY-MM-DD: {e}")

        # Get business days (excludes weekends)
        business_days = pd.bdate_range(start_date, end_date)
        dates = [d.strftime("%Y-%m-%d") for d in business_days]

        return self.load_universe_multi(dates)

    def get_available_dates(self) -> List[str]:
        """Get list of available dates in SIP data.

        Returns:
            List of dates in YYYY-MM-DD format
        """
        if not self.sip_path.exists():
            return []

        # Find all date= directories
        date_dirs = [d for d in self.sip_path.iterdir() if d.is_dir() and d.name.startswith("date=")]

        # Extract dates
        dates = []
        for date_dir in sorted(date_dirs):
            date_str = date_dir.name.replace("date=", "")
            dates.append(date_str)

        return dates

    def check_coverage(
        self,
        start_date: str,
        end_date: str,
    ) -> dict:
        """Check SIP data coverage for a date range.

        Args:
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format

        Returns:
            Dict with coverage stats:
            - expected_dates: Number of business days in range
            - found_dates: Number of dates with SIP data
            - coverage_pct: Percentage coverage
            - missing_dates: List of dates without SIP data
        """
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError as e:
            raise ValueError(f"Invalid date format. Use YYYY-MM-DD: {e}")

        # Expected business days
        business_days = pd.bdate_range(start_date, end_date)
        expected_dates = set([d.strftime("%Y-%m-%d") for d in business_days])

        # Available dates
        available_dates = set(self.get_available_dates())
        found_dates = expected_dates.intersection(available_dates)

        # Missing dates
        missing_dates = sorted(expected_dates - found_dates)

        coverage_pct = (len(found_dates) / len(expected_dates) * 100) if expected_dates else 0

        return {
            "expected_dates": len(expected_dates),
            "found_dates": len(found_dates),
            "coverage_pct": round(coverage_pct, 2),
            "missing_dates": missing_dates,
        }
