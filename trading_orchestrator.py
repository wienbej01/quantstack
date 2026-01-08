#!/usr/bin/env python3
"""
Trading System Orchestrator
Coordinates SIP generation, IBKR connectivity, and L2 collection with comprehensive monitoring.
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx
import pandas as pd

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("/home/jacobw/quantstack/logs/orchestrator.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


class NotificationManager:
    """Handles ntfy notifications for trading system events."""

    def __init__(self):
        self.base_url = "https://ntfy.sh"
        self.topics = {
            "alerts": "trading-system-alerts",
            "status": "trading-system-status",
            "trades": "trading-system-trades",
            "data": "trading-system-data",
        }

    async def send(
        self,
        topic: str,
        title: str,
        message: str,
        priority: str = "default",
        tags: str = "",
    ):
        """Send notification to ntfy topic."""
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{self.base_url}/{self.topics[topic]}",
                    data=message,
                    headers={"Title": title, "Priority": priority, "Tags": tags},
                )
            logger.info(f"Notification sent: {topic} - {title}")
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")


class MultiSessionSIPGenerator:
    """Generates SIP universe using prior day + overnight + premarket data."""

    def __init__(self, polygon_api_key: str):
        self.api_key = polygon_api_key
        self.base_url = "https://api.polygon.io"
        # Connection pool for better performance
        self.client_pool = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client with connection pooling."""
        if self.client_pool is None:
            limits = httpx.Limits(max_keepalive_connections=20, max_connections=100)
            self.client_pool = httpx.AsyncClient(
                timeout=30,
                limits=limits,
                headers={"User-Agent": "quantstack-sip-generator/1.0"},
            )
        return self.client_pool

    async def close(self):
        """Close connection pool."""
        if self.client_pool:
            await self.client_pool.aclose()
            self.client_pool = None

    def get_trading_sessions(self, target_date: str) -> Dict[str, str]:
        """Get date ranges for multi-session analysis."""
        target = pd.Timestamp(target_date).date()
        prior_day = target - timedelta(days=1)

        # Handle weekends - get last trading day
        while prior_day.weekday() >= 5:  # Saturday=5, Sunday=6
            prior_day -= timedelta(days=1)

        return {
            "prior_day": prior_day.strftime("%Y-%m-%d"),
            "overnight_start": prior_day.strftime("%Y-%m-%d"),
            "premarket_date": target_date,
        }

    async def load_multi_session_data(
        self, symbol: str, target_date: str
    ) -> Optional[pd.DataFrame]:
        """Load prior day + overnight + premarket data for symbol."""
        sessions = self.get_trading_sessions(target_date)

        try:
            # Prior day regular session (9:30 AM - 4:00 PM ET)
            prior_day_df = await self._load_polygon_session(
                symbol, sessions["prior_day"], start_time="09:30", end_time="16:00"
            )

            # Overnight session (4:00 PM prior day - 9:30 AM current day)
            overnight_df = await self._load_polygon_session(
                symbol,
                sessions["overnight_start"],
                start_time="16:00",
                end_time="23:59",
            )

            # Premarket session (4:00 AM - 9:30 AM ET current day)
            premarket_df = await self._load_polygon_session(
                symbol, target_date, start_time="04:00", end_time="09:30"
            )

            # Combine all sessions
            combined_df = pd.concat(
                [prior_day_df, overnight_df, premarket_df], ignore_index=True
            )
            combined_df = combined_df.sort_values("timestamp").reset_index(drop=True)

            return combined_df if not combined_df.empty else None

        except Exception as e:
            logger.debug(f"Failed to load multi-session data for {symbol}: {e}")
            return None

    async def _load_polygon_session(
        self, symbol: str, date: str, start_time: str, end_time: str
    ) -> pd.DataFrame:
        """Load Polygon data for specific session with retry logic."""
        url = f"{self.base_url}/v2/aggs/ticker/{symbol}/range/1/minute/{date}/{date}"
        params = {
            "adjusted": "true",
            "sort": "asc",
            "limit": 50000,
            "apiKey": self.api_key,
        }

        # Retry logic with exponential backoff
        max_retries = 3
        base_delay = 1

        for attempt in range(max_retries):
            try:
                client = await self._get_client()
                response = await client.get(url, params=params)
                response.raise_for_status()

                data = response.json()
                if data.get("status") not in ("OK", "DELAYED"):
                    if attempt < max_retries - 1:
                        await asyncio.sleep(base_delay * (2**attempt))
                        continue
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

                # Filter by session time
                session_start = pd.Timestamp(
                    f"{date} {start_time}:00", tz="America/New_York"
                )
                session_end = pd.Timestamp(
                    f"{date} {end_time}:00", tz="America/New_York"
                )

                # Handle overnight session spanning midnight
                if start_time > end_time:
                    session_end += timedelta(days=1)

                df = df[
                    (df["timestamp"] >= session_start)
                    & (df["timestamp"] <= session_end)
                ]
                return df
            except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
                if attempt < max_retries - 1:
                    delay = base_delay * (2**attempt)
                    logger.debug(
                        f"Polygon API retry {attempt + 1}/{max_retries} for {symbol} after {delay}s: {e}"
                    )
                    await asyncio.sleep(delay)
                    continue
                else:
                    logger.warning(
                        f"Polygon API failed for {symbol} after {max_retries} attempts: {e}"
                    )
                    return pd.DataFrame()
            except Exception as e:
                logger.debug(f"Unexpected error for {symbol}: {e}")
                return pd.DataFrame()

            return df[["timestamp", "open", "high", "low", "close", "volume"]]

    def calculate_multi_session_score(self, df: pd.DataFrame) -> float:
        """Calculate SIP score from multi-session data."""
        if df.empty:
            return 0.0

        # Separate sessions for analysis
        prior_day = df[df["timestamp"].dt.date < df["timestamp"].iloc[-1].date()]
        overnight = df[(df["timestamp"].dt.hour >= 16) | (df["timestamp"].dt.hour <= 4)]
        premarket = df[(df["timestamp"].dt.hour >= 4) & (df["timestamp"].dt.hour < 9.5)]

        # Calculate session metrics
        prior_close = (
            prior_day["close"].iloc[-1] if not prior_day.empty else df["close"].iloc[0]
        )
        current_price = df["close"].iloc[-1]

        # Multi-session volatility
        session_returns = []
        if not prior_day.empty:
            session_returns.append(
                (prior_day["close"].iloc[-1] - prior_day["open"].iloc[0])
                / prior_day["open"].iloc[0]
            )
        if not overnight.empty:
            session_returns.append(
                (overnight["close"].iloc[-1] - overnight["open"].iloc[0])
                / overnight["open"].iloc[0]
            )
        if not premarket.empty:
            session_returns.append(
                (premarket["close"].iloc[-1] - premarket["open"].iloc[0])
                / premarket["open"].iloc[0]
            )

        # Overall metrics
        total_volume = df["volume"].sum()
        price_change = (
            abs(current_price - prior_close) / prior_close if prior_close > 0 else 0
        )
        volatility = (
            df["high"].max() - df["low"].min() / current_price
            if current_price > 0
            else 0
        )

        # Multi-session attention score
        session_volatility = (
            sum(abs(r) for r in session_returns) / len(session_returns)
            if session_returns
            else 0
        )
        volume_score = min(total_volume / 10_000_000, 1.0)
        volatility_score = min(volatility * 20, 1.0)
        attention_score = min(price_change * total_volume * 100 / 1_000_000, 1.0)
        session_score = min(session_volatility * 30, 1.0)

        return (volume_score + volatility_score + attention_score + session_score) / 4

    async def generate_sip_universe(
        self,
        target_date: str,
        universe_symbols: List[str],
        score_floor: float = 0.85,
        min_price: float = 2.0,
        max_price: float = 200.0,
        min_dollar_volume: float = 5_000_000,
    ) -> Dict:
        """Generate SIP universe using multi-session data."""
        logger.info(f"Generating multi-session SIP universe for {target_date}")
        logger.info(
            f"Universe: {len(universe_symbols)} symbols, score_floor: {score_floor}"
        )

        qualified = []

        # Process symbols concurrently
        semaphore = asyncio.Semaphore(8)  # Limit concurrent requests

        async def process_symbol(symbol: str):
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

                    return {
                        "symbol": symbol,
                        "score": score,
                        "price": current_price,
                        "dollar_volume": total_dollar_volume,
                        "sessions": {
                            "prior_day_bars": len(
                                df[
                                    df["timestamp"].dt.date
                                    < df["timestamp"].iloc[-1].date()
                                ]
                            ),
                            "overnight_bars": len(
                                df[
                                    (df["timestamp"].dt.hour >= 16)
                                    | (df["timestamp"].dt.hour <= 4)
                                ]
                            ),
                            "premarket_bars": len(
                                df[
                                    (df["timestamp"].dt.hour >= 4)
                                    & (df["timestamp"].dt.hour < 9.5)
                                ]
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

        # Create SIP artifact
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
            },
            "universe_size": len(universe_symbols),
        }

        logger.info(
            f"Multi-session SIP generation complete: {len(qualified)} symbols qualified"
        )
        # Clean up connection pool
        await self.sip_generator.close()

        return artifact


class IBKRManager:
    """Manages IBKR Gateway connectivity and health."""

    def __init__(self):
        self.gateway_host = "127.0.0.1"
        self.gateway_port = 7497
        self.gateway_service = "ibkr-gateway.service"  # Assumes systemd service exists

    async def check_gateway_health(self) -> bool:
        """Check if IBKR Gateway is running and accessible."""
        try:
            import socket

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex((self.gateway_host, self.gateway_port))
            sock.close()
            return result == 0
        except:
            return False

    async def restart_gateway(self) -> bool:
        """Restart IBKR Gateway via systemd."""
        try:
            # Stop gateway
            stop_result = subprocess.run(
                ["sudo", "systemctl", "stop", self.gateway_service],
                capture_output=True,
                text=True,
                timeout=30,
            )

            # Wait a moment
            await asyncio.sleep(5)

            # Start gateway
            start_result = subprocess.run(
                ["sudo", "systemctl", "start", self.gateway_service],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if start_result.returncode == 0:
                # Wait for gateway to initialize
                await asyncio.sleep(10)

                # Verify it's running
                for attempt in range(6):  # 30 second timeout
                    if await self.check_gateway_health():
                        logger.info("IBKR Gateway successfully restarted")
                        return True
                    await asyncio.sleep(5)

                logger.error("IBKR Gateway started but not responding")
                return False
            else:
                logger.error(f"Failed to start IBKR Gateway: {start_result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            logger.error("IBKR Gateway restart timed out")
            return False
        except Exception as e:
            logger.error(f"Failed to restart IBKR Gateway: {e}")
            return False

    async def ensure_gateway_running(self) -> bool:
        """Ensure IBKR Gateway is running, restart if needed."""
        if await self.check_gateway_health():
            return True

        logger.warning("IBKR Gateway not responding, attempting restart...")
        return await self.restart_gateway()


class TradingOrchestrator:
    """Main orchestrator for trading system operations."""

    def __init__(self):
        self.notifications = NotificationManager()
        self.sip_generator = MultiSessionSIPGenerator(os.environ.get("POLYGON_API_KEY"))
        self.ibkr_manager = IBKRManager()

        # Paths
        self.base_dir = Path("/home/jacobw/quantstack")
        self.intraday_dir = Path("/home/jacobw/intraday_stack")
        self.universe_file = self.intraday_dir / "data/nyse_gold_tickers.txt"

    def load_universe_symbols(self) -> List[str]:
        """Load NYSE universe symbols."""
        with open(self.universe_file) as f:
            return [line.strip() for line in f if line.strip()]

    def get_next_trading_day(self) -> str:
        """Get next trading day date string."""
        et_tz = ZoneInfo("America/New_York")
        now = datetime.now(et_tz)

        # If before 9:30 AM, use today; otherwise use next trading day
        if now.time() < time(9, 30):
            target = now.date()
        else:
            target = now.date() + timedelta(days=1)

        # Skip weekends
        while target.weekday() >= 5:
            target += timedelta(days=1)

        return target.strftime("%Y-%m-%d")

    async def run_sip_generation(self) -> bool:
        """Execute SIP universe generation with multi-session data."""
        try:
            target_date = self.get_next_trading_day()
            universe_symbols = self.load_universe_symbols()

            await self.notifications.send(
                "data",
                "SIP Generation Started",
                f"Generating multi-session SIP universe for {target_date}\nSymbols: {len(universe_symbols)}",
                tags="chart_with_upwards_trend",
            )

            # Generate SIP universe
            artifact = await self.sip_generator.generate_sip_universe(
                target_date=target_date,
                universe_symbols=universe_symbols,
                score_floor=0.85,  # Slightly relaxed from 0.89
                min_price=5.0,
                max_price=50.0,
                min_dollar_volume=5_000_000,
            )

            # Save artifact
            sip_dir = self.intraday_dir / "data/daily_sip" / f"date={target_date}"
            sip_dir.mkdir(parents=True, exist_ok=True)

            with open(sip_dir / "sip_universe.json", "w") as f:
                json.dump(artifact, f, indent=2)

            # Validate results
            symbol_count = len(artifact["symbols"])
            if symbol_count == 0:
                await self.notifications.send(
                    "alerts",
                    "SIP Generation Failed",
                    f"No symbols qualified for {target_date}\nCheck filters and data availability",
                    priority="high",
                    tags="warning",
                )
                return False
            elif symbol_count < 5:
                await self.notifications.send(
                    "alerts",
                    "Low SIP Universe",
                    f"Only {symbol_count} symbols qualified for {target_date}\nMay indicate data issues",
                    priority="default",
                    tags="warning",
                )

            await self.notifications.send(
                "status",
                "SIP Generation Complete",
                f'Generated universe for {target_date}\nSymbols: {symbol_count}\nTop 5: {", ".join(artifact["symbols"][:5])}',
                tags="white_check_mark",
            )

            logger.info(
                f"SIP generation successful: {symbol_count} symbols for {target_date}"
            )
            return True

        except Exception as e:
            await self.notifications.send(
                "alerts",
                "SIP Generation Error",
                f"Failed to generate SIP universe: {str(e)}",
                priority="high",
                tags="x",
            )
            logger.error(f"SIP generation failed: {e}")
            return False

    async def validate_system_health(self) -> Dict[str, bool]:
        """Check health of all system components with automatic recovery."""
        health = {}

        # Check and ensure IBKR Gateway is running
        health["ibkr_gateway"] = await self.ibkr_manager.ensure_gateway_running()

        # Check SIP universe availability
        target_date = self.get_next_trading_day()
        sip_file = (
            self.intraday_dir
            / "data/daily_sip"
            / f"date={target_date}"
            / "sip_universe.json"
        )
        health["sip_universe"] = sip_file.exists()

        # Check and restart L2 collector if needed
        try:
            result = subprocess.run(
                ["systemctl", "is-active", "l2-collector.service"],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                logger.warning("L2 collector not active, attempting restart...")
                restart_result = subprocess.run(
                    ["sudo", "systemctl", "restart", "l2-collector.service"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                health["l2_collector"] = restart_result.returncode == 0
                if health["l2_collector"]:
                    logger.info("L2 collector successfully restarted")
            else:
                health["l2_collector"] = True
        except subprocess.TimeoutExpired:
            logger.error("L2 collector restart timed out")
            health["l2_collector"] = False
        except Exception as e:
            logger.error(f"L2 collector check failed: {e}")
            health["l2_collector"] = False

        return health

    async def run_pre_market_sequence(self):
        """Execute pre-market preparation sequence."""
        logger.info("Starting pre-market sequence")

        # 1. Generate SIP universe
        sip_success = await self.run_sip_generation()
        if not sip_success:
            await self.notifications.send(
                "alerts",
                "Pre-Market Sequence Failed",
                "SIP generation failed - trading system may not start properly",
                priority="high",
                tags="x",
            )
            return False

        # 2. Validate system health
        health = await self.validate_system_health()

        # 3. Report system status
        health_summary = "\n".join(
            [f"{k}: {'✓' if v else '✗'}" for k, v in health.items()]
        )

        if all(health.values()):
            await self.notifications.send(
                "status",
                "Pre-Market Ready",
                f"All systems operational\n{health_summary}",
                tags="rocket",
            )
        else:
            await self.notifications.send(
                "alerts",
                "System Health Issues",
                f"Some components not ready\n{health_summary}",
                priority="default",
                tags="warning",
            )

        logger.info("Pre-market sequence complete")
        return True


async def main():
    """Main orchestrator entry point."""
    orchestrator = TradingOrchestrator()

    # Run pre-market sequence
    await orchestrator.run_pre_market_sequence()


if __name__ == "__main__":
    asyncio.run(main())
