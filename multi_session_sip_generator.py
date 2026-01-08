#!/usr/bin/env python3
"""
Enhanced SIP Universe Generator with Multi-Session Data
Replaces the existing generate_daily_sip_universe.py with multi-session capability.
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx
import pandas as pd

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MultiSessionSIPGenerator:
    """Enhanced SIP generator using prior day + overnight + premarket data."""

    def __init__(self, polygon_api_key: str):
        self.api_key = polygon_api_key
        self.base_url = "https://api.polygon.io"

    def get_trading_sessions(self, target_date: str) -> Dict[str, str]:
        """Get date ranges for multi-session analysis."""
        target = pd.Timestamp(target_date).date()
        prior_day = target - timedelta(days=1)

        # Handle weekends - get last trading day
        while prior_day.weekday() >= 5:  # Saturday=5, Sunday=6
            prior_day -= timedelta(days=1)

        return {"prior_day": prior_day.strftime("%Y-%m-%d"), "target_date": target_date}

    async def load_multi_session_data(
        self, symbol: str, target_date: str
    ) -> Optional[pd.DataFrame]:
        """Load comprehensive multi-session data for symbol."""
        sessions = self.get_trading_sessions(target_date)
        all_data = []

        try:
            # Prior day full session (4:00 AM - 8:00 PM ET)
            prior_day_df = await self._load_polygon_data(symbol, sessions["prior_day"])
            if not prior_day_df.empty:
                prior_day_df["session"] = "prior_day"
                all_data.append(prior_day_df)

            # Current day premarket + early session (4:00 AM - 10:00 AM ET)
            current_day_df = await self._load_polygon_data(symbol, target_date)
            if not current_day_df.empty:
                # Filter for premarket hours (4:00 AM - 9:30 AM ET)
                premarket_mask = (
                    current_day_df["timestamp"].dt.time
                    >= pd.Timestamp("04:00:00").time()
                ) & (
                    current_day_df["timestamp"].dt.time
                    < pd.Timestamp("09:30:00").time()
                )
                premarket_df = current_day_df[premarket_mask].copy()
                premarket_df["session"] = "premarket"

                if not premarket_df.empty:
                    all_data.append(premarket_df)

            if not all_data:
                return None

            # Combine all sessions
            combined_df = pd.concat(all_data, ignore_index=True)
            combined_df = combined_df.sort_values("timestamp").reset_index(drop=True)

            return combined_df

        except Exception as e:
            logger.debug(f"Failed to load multi-session data for {symbol}: {e}")
            return None

    async def _load_polygon_data(self, symbol: str, date: str) -> pd.DataFrame:
        """Load Polygon data for a full day."""
        url = f"{self.base_url}/v2/aggs/ticker/{symbol}/range/1/minute/{date}/{date}"
        params = {
            "adjusted": "true",
            "sort": "asc",
            "limit": 50000,
            "apiKey": self.api_key,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()

            data = response.json()
            if data.get("status") not in ("OK", "DELAYED"):
                return pd.DataFrame()

            results = data.get("results", [])
            if not results:
                return pd.DataFrame()

            df = pd.DataFrame(results)
            df.rename(
                columns={
                    "o": "open",
                    "h": "high",
                    "l": "low",
                    "c": "close",
                    "v": "volume",
                    "t": "timestamp",
                },
                inplace=True,
            )
            df["timestamp"] = pd.to_datetime(
                df["timestamp"], unit="ms", utc=True
            ).dt.tz_convert("America/New_York")

            return df[["timestamp", "open", "high", "low", "close", "volume"]]

    def calculate_multi_session_score(self, df: pd.DataFrame) -> float:
        """Calculate enhanced SIP score from multi-session data."""
        if df.empty:
            return 0.0

        # Separate sessions for analysis
        prior_day = df[df.get("session", "") == "prior_day"]
        premarket = df[df.get("session", "") == "premarket"]

        # Base metrics
        total_volume = df["volume"].sum()
        price_range = df["high"].max() - df["low"].min()
        current_price = df["close"].iloc[-1]

        if current_price <= 0:
            return 0.0

        # Multi-session volatility analysis
        session_volatility = 0.0
        if not prior_day.empty:
            prior_volatility = (
                prior_day["high"].max() - prior_day["low"].min()
            ) / current_price
            session_volatility += prior_volatility

        if not premarket.empty:
            premarket_volatility = (
                premarket["high"].max() - premarket["low"].min()
            ) / current_price
            session_volatility += premarket_volatility * 1.5  # Weight premarket higher

        # Price momentum across sessions
        price_momentum = 0.0
        if not prior_day.empty and not premarket.empty:
            prior_close = prior_day["close"].iloc[-1]
            premarket_change = (current_price - prior_close) / prior_close
            price_momentum = abs(premarket_change)

        # Volume analysis
        volume_score = min(total_volume / 10_000_000, 1.0)
        volatility_score = min(session_volatility * 15, 1.0)
        momentum_score = min(price_momentum * 25, 1.0)

        # News attention proxy (volume * price movement)
        attention_score = min((total_volume * price_momentum * 100) / 1_000_000, 1.0)

        # Combined score with multi-session weighting
        final_score = (
            volume_score * 0.3
            + volatility_score * 0.3
            + momentum_score * 0.25
            + attention_score * 0.15
        )

        return min(final_score, 1.0)

    async def generate_sip_universe(
        self,
        target_date: str,
        universe_symbols: List[str],
        score_floor: float = 0.85,
        min_price: float = 5.0,
        max_price: float = 50.0,
        min_dollar_volume: float = 5_000_000,
    ) -> Dict:
        """Generate SIP universe using multi-session data."""
        logger.info(f"🚀 Generating multi-session SIP universe for {target_date}")
        logger.info(f"📊 Universe: {len(universe_symbols)} symbols")
        logger.info(f"🎯 Score floor: {score_floor}, Price: ${min_price}-${max_price}")

        qualified = []
        processed = 0

        # Process symbols with concurrency control
        semaphore = asyncio.Semaphore(8)

        async def process_symbol(symbol: str):
            nonlocal processed
            async with semaphore:
                try:
                    df = await self.load_multi_session_data(symbol, target_date)
                    if df is None or df.empty:
                        return None

                    current_price = df["close"].iloc[-1]
                    if current_price < min_price or current_price > max_price:
                        return None

                    total_dollar_volume = (df["close"] * df["volume"]).sum()
                    if total_dollar_volume < min_dollar_volume:
                        return None

                    score = self.calculate_multi_session_score(df)
                    if score < score_floor:
                        return None

                    processed += 1
                    if processed % 50 == 0:
                        logger.info(
                            f"📈 Processed {processed}/{len(universe_symbols)}, qualified: {len(qualified)}"
                        )

                    return {
                        "symbol": symbol,
                        "score": score,
                        "price": current_price,
                        "dollar_volume": total_dollar_volume,
                        "sessions": {
                            "total_bars": len(df),
                            "prior_day_bars": len(
                                df[df.get("session", "") == "prior_day"]
                            ),
                            "premarket_bars": len(
                                df[df.get("session", "") == "premarket"]
                            ),
                        },
                    }
                except Exception as e:
                    logger.debug(f"Error processing {symbol}: {e}")
                    return None

        # Execute all symbol processing
        tasks = [process_symbol(symbol) for symbol in universe_symbols]
        results = await asyncio.gather(*tasks)

        # Filter and sort results
        qualified = [r for r in results if r is not None]
        qualified.sort(key=lambda x: x["score"], reverse=True)

        logger.info(
            f"✅ Multi-session SIP generation complete: {len(qualified)} symbols qualified"
        )

        # Create enhanced SIP artifact
        artifact = {
            "date": target_date,
            "timestamp": datetime.utcnow().isoformat(),
            "symbols": [q["symbol"] for q in qualified],
            "scores": {q["symbol"]: q["score"] for q in qualified},
            "metadata": {
                q["symbol"]: {
                    "price": q["price"],
                    "dollar_volume": q["dollar_volume"],
                    "sessions": q["sessions"],
                }
                for q in qualified
            },
            "selection_params": {
                "score_floor": score_floor,
                "price_range": [min_price, max_price],
                "min_dollar_volume": min_dollar_volume,
                "data_source": "polygon_multi_session",
                "sessions": ["prior_day", "overnight", "premarket"],
                "generation_method": "multi_session_v2",
            },
            "universe_size": len(universe_symbols),
            "processing_stats": {
                "total_processed": len(universe_symbols),
                "qualified_count": len(qualified),
                "qualification_rate": (
                    len(qualified) / len(universe_symbols) if universe_symbols else 0
                ),
            },
        }

        return artifact


async def main():
    """Main entry point for multi-session SIP generation."""
    import argparse

    parser = argparse.ArgumentParser(description="Generate multi-session SIP universe")
    parser.add_argument(
        "--date", required=True, help="Target trading date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--score-floor", type=float, default=0.85, help="Minimum SIP score"
    )
    parser.add_argument(
        "--min-price", type=float, default=5.0, help="Minimum stock price"
    )
    parser.add_argument(
        "--max-price", type=float, default=50.0, help="Maximum stock price"
    )
    parser.add_argument(
        "--min-dollar-volume",
        type=float,
        default=5_000_000,
        help="Minimum dollar volume",
    )
    parser.add_argument(
        "--output-dir",
        default="/home/jacobw/intraday_stack/data/daily_sip",
        help="Output directory",
    )

    args = parser.parse_args()

    # Load universe symbols
    universe_file = Path("/home/jacobw/intraday_stack/data/nyse_gold_tickers.txt")
    with open(universe_file) as f:
        universe_symbols = [line.strip() for line in f if line.strip()]

    # Initialize generator
    api_key = os.environ.get("POLYGON_API_KEY")
    if not api_key:
        logger.error("POLYGON_API_KEY environment variable required")
        sys.exit(1)

    generator = MultiSessionSIPGenerator(api_key)

    # Generate SIP universe
    artifact = await generator.generate_sip_universe(
        target_date=args.date,
        universe_symbols=universe_symbols,
        score_floor=args.score_floor,
        min_price=args.min_price,
        max_price=args.max_price,
        min_dollar_volume=args.min_dollar_volume,
    )

    # Save artifact
    output_dir = Path(args.output_dir) / f"date={args.date}"
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = output_dir / "sip_universe.json"
    with open(output_file, "w") as f:
        json.dump(artifact, f, indent=2)

    logger.info(f"💾 Saved SIP universe to: {output_file}")
    logger.info(f"🎯 Top 10 symbols: {', '.join(artifact['symbols'][:10])}")


if __name__ == "__main__":
    asyncio.run(main())
