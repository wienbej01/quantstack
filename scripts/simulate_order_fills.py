#!/usr/bin/env python3
"""
Simulate IOC order fills by checking against L2 data with latency adjustment.
Tests if orders would have filled at order price, +1 tick, or -1 tick.
"""
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

# Tick size for stocks
TICK_SIZE = 0.01


def parse_api_logs(log_path: str) -> list[dict]:
    """Extract IOC entry orders from API logs."""
    import pytz

    et_tz = pytz.timezone("America/New_York")

    orders = []
    with open(log_path) as f:
        for line in f:
            # Look for order placement: <- [3;order_id;conid;symbol;...;BUY/SELL;qty;LMT;price;...;IOC;...
            if "<- [3;" in line and ";IOC;" in line:
                try:
                    # Extract timestamp
                    ts_match = re.search(r"(\d{2}):(\d{2}):(\d{2}):(\d{3})", line)
                    if not ts_match:
                        continue

                    # Construct timestamp (Jan 23, 2026 in Manila time = Jan 22-23 ET)
                    h, m, s, ms = ts_match.groups()
                    # Convert Manila time to ET (Manila is UTC+8, ET is UTC-5, so Manila is ET+13)
                    hour = int(h)
                    if hour >= 22:  # 22:00+ Manila = 09:00+ ET same day
                        timestamp = et_tz.localize(
                            datetime(
                                2026, 1, 23, hour - 13, int(m), int(s), int(ms) * 1000
                            )
                        )
                    else:  # 00:00-05:00 Manila = 11:00-16:00 ET previous day
                        timestamp = et_tz.localize(
                            datetime(
                                2026, 1, 23, hour + 11, int(m), int(s), int(ms) * 1000
                            )
                        )

                    # Parse order fields: [3;order_id;conid;symbol;...;side;qty;order_type;price;...;tif;...]
                    parts = line.split("<- [3;")[1].split(";")
                    if len(parts) < 20:
                        continue

                    order_id = parts[0]
                    conid = parts[1]
                    symbol = parts[2]
                    side = parts[15]  # BUY or SELL
                    quantity = parts[16]
                    order_type = parts[17]  # LMT
                    price = parts[18]

                    if order_type == "LMT" and price:
                        order = {
                            "timestamp": timestamp,
                            "order_id": order_id,
                            "conid": conid,
                            "symbol": symbol,
                            "side": side,
                            "price": float(price),
                            "quantity": float(quantity),
                        }
                        orders.append(order)

                except (ValueError, IndexError):
                    continue

    return orders


def parse_gateway_logs(log_path: str) -> dict:
    """Extract order placement events and calculate latencies."""
    latencies = []

    with open(log_path) as f:
        for line in f:
            # Extract latency info if available (e.g., "latency: 150ms" or similar patterns)
            latency_match = re.search(r"latency[:\s]+(\d+)", line, re.IGNORECASE)
            if latency_match:
                latencies.append(int(latency_match.group(1)))

    # Use 100ms as default if no latencies found (from previous analysis: 100-150ms typical)
    avg_latency_ms = sum(latencies) / len(latencies) if latencies else 100

    return {"avg_latency_ms": avg_latency_ms, "latencies": latencies}


def load_l2_data(symbol: str, date: str) -> pd.DataFrame:
    """Load L2 features for a symbol on a given date."""
    data_dir = Path("/home/jacobw/quantstack/data/l2/l2_maximum/features")
    symbol_dir = data_dir / f"date={date}" / f"symbol={symbol}"

    if not symbol_dir.exists():
        return pd.DataFrame()

    # Read all parquet files for this symbol using pyarrow dataset for efficiency
    try:
        import pyarrow.dataset as ds

        dataset = ds.dataset(symbol_dir, format="parquet", partitioning=None)
        table = dataset.to_table(columns=["ts_utc", "mid", "spread"])
        df = table.to_pandas()

        df["timestamp"] = pd.to_datetime(df["ts_utc"])
        df = df.sort_values("timestamp").reset_index(drop=True)

        # Calculate bid/ask from mid and spread
        df["bid"] = df["mid"] - df["spread"] / 2
        df["ask"] = df["mid"] + df["spread"] / 2

        return df[["timestamp", "bid", "ask"]]
    except Exception as e:
        print(f"  Error loading data: {e}")
        return pd.DataFrame()


def check_fill(order: dict, l2_data: pd.DataFrame, latency_ms: float) -> dict:
    """Check if order would have filled at order price, +1 tick, or -1 tick."""
    if l2_data.empty:
        return {"status": "no_data", "price": order["price"]}

    # Adjust order time for latency
    order_time = order["timestamp"] + timedelta(milliseconds=latency_ms)

    # Find closest L2 snapshot at or after order receipt time using binary search
    idx = l2_data["timestamp"].searchsorted(order_time, side="left")

    if idx >= len(l2_data):
        return {"status": "no_data_at_time", "price": order["price"]}

    row = l2_data.iloc[idx]

    # Extract bid/ask
    bid = row["bid"]
    ask = row["ask"]

    if pd.isna(bid) or pd.isna(ask) or bid == 0 or ask == 0:
        return {"status": "invalid_quote", "price": order["price"]}

    # Check fills for BUY orders (need to lift the ask)
    if order["side"] == "BUY":
        results = {
            "bid": bid,
            "ask": ask,
            "order_price": order["price"],
            "filled_at_order": order["price"] >= ask,
            "filled_plus_1": (order["price"] + TICK_SIZE) >= ask,
            "filled_minus_1": (order["price"] - TICK_SIZE) >= ask,
        }
    # Check fills for SELL orders (need to hit the bid)
    else:
        results = {
            "bid": bid,
            "ask": ask,
            "order_price": order["price"],
            "filled_at_order": order["price"] <= bid,
            "filled_plus_1": (order["price"] + TICK_SIZE) <= bid,
            "filled_minus_1": (order["price"] - TICK_SIZE) <= bid,
        }

    return results


def main():
    print("Loading logs...")

    # Parse logs
    api_log_path = "/home/jacobw/api-exported-logs.txt"
    gateway_log_path = "/home/jacobw/gateway-exported-logs.txt"

    orders = parse_api_logs(api_log_path)
    gateway_info = parse_gateway_logs(gateway_log_path)

    print(f"Found {len(orders)} IOC orders")
    print(f"Average latency: {gateway_info['avg_latency_ms']:.1f}ms")

    if len(orders) == 0:
        print("No orders found. Exiting.")
        return

    # Group by symbol
    by_symbol = defaultdict(list)
    for order in orders:
        by_symbol[order["symbol"]].append(order)

    print(f"\nProcessing {len(by_symbol)} symbols...")

    # Analyze fills
    results = {
        "at_order": 0,
        "plus_1": 0,
        "minus_1": 0,
        "no_fill": 0,
        "no_data": 0,
        "total": len(orders),
    }

    details = []

    for symbol, symbol_orders in by_symbol.items():
        print(f"\nProcessing {symbol}: {len(symbol_orders)} orders", flush=True)

        # Load L2 data
        date = symbol_orders[0]["timestamp"].strftime("%Y-%m-%d")
        print(f"  Loading L2 data...", flush=True)
        l2_data = load_l2_data(symbol, date)

        if l2_data.empty:
            print(f"  No L2 data found")
            results["no_data"] += len(symbol_orders)
            continue

        print(f"  Loaded {len(l2_data)} L2 snapshots")

        # Check each order
        for i, order in enumerate(symbol_orders):
            if i % 100 == 0:
                print(f"  Checked {i}/{len(symbol_orders)} orders", flush=True)

            fill_result = check_fill(order, l2_data, gateway_info["avg_latency_ms"])

            if "status" in fill_result:
                results["no_data"] += 1
            else:
                if fill_result["filled_at_order"]:
                    results["at_order"] += 1
                elif fill_result["filled_minus_1"]:
                    results["minus_1"] += 1
                elif fill_result["filled_plus_1"]:
                    results["plus_1"] += 1
                else:
                    results["no_fill"] += 1

                details.append(
                    {
                        "symbol": symbol,
                        "time": order["timestamp"],
                        "side": order["side"],
                        **fill_result,
                    }
                )

    # Print summary
    print("\n" + "=" * 60)
    print("FILL SIMULATION RESULTS")
    print("=" * 60)
    print(f"Total orders: {results['total']}")

    if results["total"] > 0:
        print(
            f"Filled at order price: {results['at_order']} ({100*results['at_order']/results['total']:.1f}%)"
        )
        print(
            f"Would fill at -1 tick: {results['minus_1']} ({100*results['minus_1']/results['total']:.1f}%)"
        )
        print(
            f"Would fill at +1 tick: {results['plus_1']} ({100*results['plus_1']/results['total']:.1f}%)"
        )
        print(
            f"No fill even at +/-1: {results['no_fill']} ({100*results['no_fill']/results['total']:.1f}%)"
        )
        print(
            f"No L2 data available: {results['no_data']} ({100*results['no_data']/results['total']:.1f}%)"
        )

    # Save details
    if details:
        df = pd.DataFrame(details)
        output_path = "/home/jacobw/quantstack/fill_simulation_results.csv"
        df.to_csv(output_path, index=False)
        print(f"\nDetailed results saved to: {output_path}")


if __name__ == "__main__":
    main()
