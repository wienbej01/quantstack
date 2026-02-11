#!/usr/bin/env python3
"""Clear zombie IBKR market depth subscriptions.

Run this before starting L2 services to ensure clean subscription state.
Connects briefly to cancel any lingering depth subscriptions.
"""

import sys
import time

from ib_insync import IB, Stock

HOST = "127.0.0.1"
PORT = 7494
CLIENT_IDS = [
    250,
    521,
    201,
]  # Use 201 instead of 200 to avoid conflict with main service


def clear_subscriptions():
    """Connect with each client ID and cancel all depth subscriptions."""
    for client_id in CLIENT_IDS:
        ib = IB()
        try:
            ib.connect(HOST, PORT, clientId=client_id, timeout=10)
            print(f"[{client_id}] Connected, canceling depth subscriptions...")

            # Cancel any active market depth
            for ticker in ib.tickers():
                if hasattr(ticker, "domBids") or hasattr(ticker, "domAsks"):
                    try:
                        ib.cancelMktDepth(ticker.contract)
                        print(
                            f"[{client_id}] Canceled depth for {ticker.contract.symbol}"
                        )
                    except Exception as e:
                        print(f"[{client_id}] Error canceling: {e}")

            ib.disconnect()
            print(f"[{client_id}] Disconnected cleanly")
            time.sleep(0.5)
        except Exception as e:
            print(f"[{client_id}] Could not connect: {e}")

    print("Done clearing subscriptions")


if __name__ == "__main__":
    clear_subscriptions()
