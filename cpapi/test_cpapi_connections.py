#!/usr/bin/env python3
"""
IBKR Client Portal API v1.0 Connection Test.

Creates 5 dummy client connections and tests functionality over 20 minutes
(4x 5-minute intervals) as specified.

Requirements:
- Client Portal Gateway must be running on localhost:5000
- User must be authenticated via browser login

Usage:
    python test_cpapi_connections.py
"""
import logging
import sys
import time
from datetime import datetime

from cpapi import CPAPIClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

NUM_CLIENTS = 5
TEST_INTERVALS = 5  # 5 test cycles
INTERVAL_SECONDS = 300  # 5 minutes between tests


def create_clients() -> list[CPAPIClient]:
    """Create 5 dummy client connections."""
    clients = []
    for i in range(NUM_CLIENTS):
        client = CPAPIClient(client_id=f"client_{i+1}")
        clients.append(client)
        logger.info(f"Created {client.client_id}")
    return clients


def test_client(client: CPAPIClient) -> dict:
    """Test a single client's functionality."""
    results = {
        "client_id": client.client_id,
        "timestamp": datetime.now().isoformat(),
        "auth_status": False,
        "accounts": [],
        "positions_count": 0,
        "pnl": None,
        "error": None,
    }

    try:
        # 1. Check auth status
        if not client.check_auth_status():
            # Try to init brokerage session
            client.init_brokerage_session()
            client.check_auth_status()

        results["auth_status"] = client.state.authenticated

        if not client.state.authenticated:
            results["error"] = "Not authenticated"
            return results

        # 2. Get accounts (MUST be called first)
        accounts = client.get_accounts()
        results["accounts"] = accounts

        if not accounts:
            results["error"] = "No accounts returned"
            return results

        # 3. Get positions for first account
        positions = client.get_positions(accounts[0])
        results["positions_count"] = len(positions)

        # 4. Get P&L
        pnl = client.get_account_pnl()
        results["pnl"] = pnl.get("upnl") if pnl else None

        # 5. Tickle to keep alive
        client.tickle()

    except Exception as e:
        results["error"] = str(e)
        logger.error(f"[{client.client_id}] Error: {e}")

    return results


def run_test_cycle(clients: list[CPAPIClient], cycle: int) -> list[dict]:
    """Run a single test cycle for all clients."""
    logger.info(f"\n{'='*60}")
    logger.info(f"TEST CYCLE {cycle}/{TEST_INTERVALS} - {datetime.now().isoformat()}")
    logger.info(f"{'='*60}")

    results = []
    for client in clients:
        result = test_client(client)
        results.append(result)

        status = "✓" if result["auth_status"] and not result["error"] else "✗"
        logger.info(
            f"  [{status}] {result['client_id']}: "
            f"auth={result['auth_status']}, "
            f"accounts={len(result['accounts'])}, "
            f"positions={result['positions_count']}, "
            f"error={result['error']}"
        )

        # Small delay between clients to respect pacing
        time.sleep(0.2)

    return results


def print_summary(all_results: list[list[dict]]):
    """Print test summary."""
    logger.info(f"\n{'='*60}")
    logger.info("TEST SUMMARY")
    logger.info(f"{'='*60}")

    total_tests = 0
    successful_tests = 0

    for cycle_idx, cycle_results in enumerate(all_results, 1):
        cycle_success = sum(
            1 for r in cycle_results if r["auth_status"] and not r["error"]
        )
        total_tests += len(cycle_results)
        successful_tests += cycle_success
        logger.info(
            f"  Cycle {cycle_idx}: {cycle_success}/{len(cycle_results)} successful"
        )

    success_rate = (successful_tests / total_tests * 100) if total_tests > 0 else 0
    logger.info(
        f"\nOverall: {successful_tests}/{total_tests} ({success_rate:.1f}% success rate)"
    )

    # Check for stale connection issues
    stale_count = 0
    for cycle_results in all_results:
        for r in cycle_results:
            if r["error"] and "timeout" in str(r["error"]).lower():
                stale_count += 1

    if stale_count > 0:
        logger.warning(f"⚠️  Detected {stale_count} potential stale connection issues")
    else:
        logger.info("✓ No stale connection issues detected")


def main():
    logger.info("IBKR Client Portal API v1.0 Connection Test")
    logger.info(
        f"Testing {NUM_CLIENTS} clients over {TEST_INTERVALS} cycles ({INTERVAL_SECONDS}s intervals)"
    )
    logger.info(
        f"Total test duration: ~{TEST_INTERVALS * INTERVAL_SECONDS / 60:.0f} minutes\n"
    )

    # Create clients
    clients = create_clients()
    all_results = []

    try:
        for cycle in range(1, TEST_INTERVALS + 1):
            results = run_test_cycle(clients, cycle)
            all_results.append(results)

            if cycle < TEST_INTERVALS:
                logger.info(f"\nWaiting {INTERVAL_SECONDS}s until next cycle...")
                time.sleep(INTERVAL_SECONDS)

        print_summary(all_results)

    except KeyboardInterrupt:
        logger.info("\nTest interrupted by user")
    finally:
        # Cleanup
        logger.info("\nCleaning up clients...")
        for client in clients:
            client.stop()

    return 0 if all_results else 1


if __name__ == "__main__":
    sys.exit(main())
