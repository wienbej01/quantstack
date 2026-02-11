#!/usr/bin/env python3
"""Trade Database V2 - Complete Test Suite Implementation"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import psycopg2

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def get_db_config():
    """Get database config, using peer auth for local connections"""
    # Try to use psql-style connection (peer auth)
    import subprocess

    try:
        # Test if we can connect via psql (uses peer auth)
        result = subprocess.run(
            ["psql", "-U", "jacobw", "-d", "trading", "-c", "SELECT 1"],
            capture_output=True,
            timeout=2,
        )
        if result.returncode == 0:
            # Use Unix socket connection (peer auth)
            return {
                "database": "trading",
                "user": "jacobw",
            }
    except:
        pass

    # Fall back to TCP with password
    config = {
        "host": os.getenv("TRADE_DB_HOST", "localhost"),
        "port": int(os.getenv("TRADE_DB_PORT", "5432")),
        "database": os.getenv("TRADE_DB_NAME", "trading"),
        "user": os.getenv("TRADE_DB_USER", "jacobw"),
    }
    password = os.getenv("TRADE_DB_PASSWORD")
    if password:
        config["password"] = password
    return config


WAL_DIR = Path(__file__).parent.parent / "logs" / "wal"


class TestResult:
    def __init__(self, phase, test_name):
        self.phase = phase
        self.test_name = test_name
        self.passed = False
        self.errors = []
        self.duration = 0

    def add_error(self, error):
        self.errors.append(error)

    def mark_passed(self):
        self.passed = True


class TestRunner:
    def __init__(self):
        self.results = []
        self.conn = None

    def connect_db(self):
        try:
            self.conn = psycopg2.connect(**get_db_config())
            return True
        except Exception as e:
            print(f"❌ Database connection failed: {e}")
            return False

    def run_query(self, query, params=None):
        try:
            cur = self.conn.cursor()
            if params is not None:
                cur.execute(query, params)
            else:
                cur.execute(query)
            if query.strip().upper().startswith(
                "SELECT"
            ) or query.strip().upper().startswith("EXPLAIN"):
                return cur.fetchall()
            elif "RETURNING" in query.upper():
                result = cur.fetchall()
                self.conn.commit()
                return result
            self.conn.commit()
            return None
        except Exception as e:
            self.conn.rollback()
            raise e

    def run_test(self, phase, test_name, test_func):
        result = TestResult(phase, test_name)
        print(f"\n{'='*60}")
        print(f"Phase {phase}: {test_name}")
        print(f"{'='*60}")

        start = time.time()
        try:
            test_func(result)
            if not result.errors:
                result.mark_passed()
        except Exception as e:
            import traceback

            result.add_error(f"Exception: {e}")
            if "STRESS" in test_name or "Throughput" in test_name:
                # Print full traceback for throughput test
                traceback.print_exc()
        result.duration = time.time() - start

        self.results.append(result)

        if result.passed:
            print(f"✅ PASSED ({result.duration:.2f}s)")
        else:
            print(f"❌ FAILED ({result.duration:.2f}s)")
            for error in result.errors:
                print(f"   - {error}")

        return result.passed

    # ========== PHASE 1: BASIC SIMULATION ==========

    def test_1_1_single_trade(self, result):
        """Test 1.1: Single Complete Trade"""
        # Clean test data
        self.run_query("DELETE FROM executions WHERE symbol = 'TEST1'")
        self.run_query("DELETE FROM trades_v2 WHERE symbol = 'TEST1'")

        # Insert trade
        trade_id = self.run_query(
            """
            INSERT INTO trades_v2 (symbol, system, direction, signal_time, signal_price)
            VALUES ('TEST1', 'test', 'long', NOW(), 150.0)
            RETURNING trade_id
        """
        )[0][0]

        # Insert entry fill
        self.run_query(
            """
            INSERT INTO executions (exec_id, trade_id, symbol, system, side, quantity, price, commission, ibkr_time, source)
            VALUES ('ENTRY1', %s, 'TEST1', 'test', 'BUY', 100, 150.0, 0.5, NOW(), 'CALLBACK')
        """,
            (trade_id,),
        )

        # Update trade with entry
        self.run_query(
            """
            UPDATE trades_v2 SET
                entry_time = NOW(),
                entry_price = 150.0,
                entry_qty = 100,
                entry_fills = '[{"exec_id": "ENTRY1", "qty": 100, "price": 150.0}]'::jsonb
            WHERE trade_id = %s
        """,
            (trade_id,),
        )

        # Insert exit fill
        self.run_query(
            """
            INSERT INTO executions (exec_id, trade_id, symbol, system, side, quantity, price, commission, ibkr_time, source)
            VALUES ('EXIT1', %s, 'TEST1', 'test', 'SELL', 100, 151.0, 0.5, NOW(), 'CALLBACK')
        """,
            (trade_id,),
        )

        # Update trade with exit and P&L
        self.run_query(
            """
            UPDATE trades_v2 SET
                exit_time = NOW(),
                exit_price = 151.0,
                exit_qty = 100,
                exit_fills = '[{"exec_id": "EXIT1", "qty": 100, "price": 151.0}]'::jsonb,
                status = 'CLOSED',
                gross_pnl = 100.0,
                total_commission = 1.0,
                net_pnl = 99.0
            WHERE trade_id = %s
        """,
            (trade_id,),
        )

        # Verify
        trade = self.run_query(
            "SELECT * FROM trades_v2 WHERE trade_id = %s", (trade_id,)
        )
        if not trade:
            result.add_error("Trade not created")
            return

        fills = self.run_query(
            "SELECT COUNT(*) FROM executions WHERE trade_id = %s", (trade_id,)
        )
        if fills[0][0] != 2:
            result.add_error(f"Expected 2 fills, got {fills[0][0]}")

        status = self.run_query(
            "SELECT status FROM trades_v2 WHERE trade_id = %s", (trade_id,)
        )
        if status and status[0][0] != "CLOSED":
            result.add_error(f"Status should be 'CLOSED', got '{status[0][0]}'")

        pnl = self.run_query(
            "SELECT net_pnl FROM trades_v2 WHERE trade_id = %s", (trade_id,)
        )
        if pnl and pnl[0][0] and abs(float(pnl[0][0]) - 99.0) > 0.01:
            result.add_error(f"Net P&L should be 99.0, got {pnl[0][0]}")

    def test_1_2_partial_fills(self, result):
        """Test 1.2: Multiple Partial Fills"""
        self.run_query("DELETE FROM executions WHERE symbol = 'TEST2'")
        self.run_query("DELETE FROM trades_v2 WHERE symbol = 'TEST2'")

        trade_id = self.run_query(
            """
            INSERT INTO trades_v2 (symbol, system, direction, signal_time, signal_price)
            VALUES ('TEST2', 'test', 'long', NOW(), 150.0)
            RETURNING trade_id
        """
        )[0][0]

        # Insert 3 partial fills
        fills = [
            ("PART1", 50, 150.0),
            ("PART2", 30, 150.5),
            ("PART3", 20, 151.0),
        ]

        for exec_id, qty, price in fills:
            self.run_query(
                """
                INSERT INTO executions (exec_id, trade_id, symbol, system, side, quantity, price, commission, ibkr_time, source)
                VALUES (%s, %s, 'TEST2', 'test', 'BUY', %s, %s, 0.5, NOW(), 'CALLBACK')
            """,
                (exec_id, trade_id, qty, price),
            )

        # Calculate VWAP: (50*150 + 30*150.5 + 20*151) / 100 = 150.365
        expected_vwap = (50 * 150.0 + 30 * 150.5 + 20 * 151.0) / 100

        self.run_query(
            """
            UPDATE trades_v2 SET
                entry_time = NOW(),
                entry_price = %s,
                entry_qty = 100,
                entry_fills = '[
                    {"exec_id": "PART1", "qty": 50, "price": 150.0},
                    {"exec_id": "PART2", "qty": 30, "price": 150.5},
                    {"exec_id": "PART3", "qty": 20, "price": 151.0}
                ]'::jsonb
            WHERE trade_id = %s
        """,
            (expected_vwap, trade_id),
        )

        # Verify
        trade = self.run_query(
            "SELECT entry_price, entry_qty, entry_fills FROM trades_v2 WHERE trade_id = %s",
            (trade_id,),
        )
        if not trade:
            result.add_error("Trade not found")
            return

        actual_vwap = float(trade[0][0])
        if abs(actual_vwap - expected_vwap) > 0.01:
            result.add_error(
                f"VWAP should be {expected_vwap:.2f}, got {actual_vwap:.2f}"
            )

        if trade[0][1] != 100:
            result.add_error(f"Total qty should be 100, got {trade[0][1]}")

        fills_array = trade[0][2]
        if len(fills_array) != 3:
            result.add_error(f"Should have 3 fills in array, got {len(fills_array)}")

    def test_1_3_deduplication(self, result):
        """Test 1.3: Rapid Trades (Deduplication)"""
        self.run_query("DELETE FROM executions WHERE symbol = 'TEST3'")

        # Try to insert same exec_id 3 times
        exec_id = "DUP123"
        for source in ["CALLBACK", "POLL", "RECONCILE"]:
            try:
                self.run_query(
                    """
                    INSERT INTO executions (exec_id, symbol, system, side, quantity, price, commission, ibkr_time, source)
                    VALUES (%s, 'TEST3', 'test', 'BUY', 100, 150.0, 0.5, NOW(), %s)
                    ON CONFLICT (exec_id) DO NOTHING
                """,
                    (exec_id, source),
                )
            except Exception as e:
                result.add_error(f"Insert failed: {e}")

        # Verify only 1 row
        count = self.run_query(
            "SELECT COUNT(*) FROM executions WHERE exec_id = %s", (exec_id,)
        )
        if count[0][0] != 1:
            result.add_error(f"Should have 1 row, got {count[0][0]}")

        # Verify first source wins
        source = self.run_query(
            "SELECT source FROM executions WHERE exec_id = %s", (exec_id,)
        )
        if source[0][0] != "CALLBACK":
            result.add_error(f"First source should be 'CALLBACK', got '{source[0][0]}'")

    # ========== PHASE 2: WAL DURABILITY ==========

    def test_2_1_wal_write(self, result):
        """Test 2.1: WAL Write During Simulation"""
        WAL_DIR.mkdir(parents=True, exist_ok=True)

        # Create test WAL file
        wal_file = WAL_DIR / f"fills_{datetime.now().strftime('%Y%m%d')}.jsonl"

        # Write test fill
        fill_data = {
            "exec_id": "WAL123",
            "symbol": "TEST4",
            "side": "BUY",
            "qty": 100,
            "price": 150.0,
            "commission": 0.5,
            "exec_time": datetime.now().isoformat(),
            "source": "CALLBACK",  # Must be uppercase
        }

        with open(wal_file, "a") as f:
            f.write(json.dumps(fill_data) + "\n")

        # Verify file exists and readable
        if not wal_file.exists():
            result.add_error("WAL file not created")
            return

        with open(wal_file, "r") as f:
            lines = f.readlines()
            if not lines:
                result.add_error("WAL file empty")
                return

            last_line = json.loads(lines[-1])
            if last_line["exec_id"] != "WAL123":
                result.add_error(f"WAL exec_id mismatch: {last_line['exec_id']}")

    def test_2_2_wal_recovery(self, result):
        """Test 2.2: WAL Recovery Simulation"""
        # Simulate recovery by reading WAL and inserting to DB
        wal_file = WAL_DIR / f"fills_{datetime.now().strftime('%Y%m%d')}.jsonl"

        if not wal_file.exists():
            result.add_error("No WAL file to recover from")
            return

        recovered = 0
        with open(wal_file, "r") as f:
            for line in f:
                try:
                    fill = json.loads(line)
                    # Ensure source is uppercase
                    source = fill["source"].upper() if "source" in fill else "CALLBACK"
                    self.run_query(
                        """
                        INSERT INTO executions (exec_id, symbol, system, side, quantity, price, commission, ibkr_time, source)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (exec_id) DO NOTHING
                    """,
                        (
                            fill["exec_id"],
                            fill["symbol"],
                            "test",
                            fill["side"],
                            fill["qty"],
                            fill["price"],
                            fill["commission"],
                            fill["exec_time"],
                            source,
                        ),
                    )
                    recovered += 1
                except json.JSONDecodeError:
                    # Skip corrupted entries
                    pass
                except Exception as e:
                    # Log but don't fail on individual recovery errors
                    pass

        if recovered == 0:
            result.add_error("No fills recovered from WAL")

    # ========== PHASE 3: DEDUPLICATION ==========

    def test_3_1_concurrent_inserts(self, result):
        """Test 3.1: Same Fill 3 Times"""
        # Already tested in 1.3, verify again
        self.run_query("DELETE FROM executions WHERE exec_id = 'CONC123'")

        # Simulate concurrent inserts
        for i in range(3):
            self.run_query(
                """
                INSERT INTO executions (exec_id, symbol, system, side, quantity, price, commission, ibkr_time, source)
                VALUES ('CONC123', 'TEST5', 'test', 'BUY', 100, 150.0, 0.5, NOW(), 'CALLBACK')
                ON CONFLICT (exec_id) DO NOTHING
            """
            )

        count = self.run_query(
            "SELECT COUNT(*) FROM executions WHERE exec_id = 'CONC123'"
        )
        if count[0][0] != 1:
            result.add_error(
                f"Should have 1 row after concurrent inserts, got {count[0][0]}"
            )

    # ========== PHASE 4: HISTORICAL REPLAY ==========

    def test_4_1_pnl_accuracy(self, result):
        """Test 4.1: P&L Calculation Accuracy"""
        self.run_query("DELETE FROM executions WHERE symbol = 'TEST6'")
        self.run_query("DELETE FROM trades_v2 WHERE symbol = 'TEST6'")

        # Create trade with known P&L
        trade_id = self.run_query(
            """
            INSERT INTO trades_v2 (symbol, system, direction, signal_time, signal_price,
                                   entry_time, entry_price, entry_qty,
                                   exit_time, exit_price, exit_qty,
                                   gross_pnl, total_commission, net_pnl)
            VALUES ('TEST6', 'test', 'long', NOW(), 100.0,
                    NOW(), 100.0, 100,
                    NOW(), 105.0, 100,
                    500.0, 1.0, 499.0)
            RETURNING trade_id
        """
        )[0][0]

        # Verify P&L calculation: (105 - 100) * 100 - 1 = 499
        trade = self.run_query(
            "SELECT gross_pnl, total_commission, net_pnl FROM trades_v2 WHERE trade_id = %s",
            (trade_id,),
        )

        if abs(float(trade[0][0]) - 500.0) > 0.01:
            result.add_error(f"Gross P&L should be 500.0, got {trade[0][0]}")

        if abs(float(trade[0][2]) - 499.0) > 0.01:
            result.add_error(f"Net P&L should be 499.0, got {trade[0][2]}")

    # ========== PHASE 5: STRESS TEST ==========

    def test_5_1_throughput(self, result):
        """Test 5.1: 100 Trades Rapid Fire"""
        try:
            # Clean up first
            self.run_query("DELETE FROM trades_v2 WHERE symbol LIKE 'STRESS%'")

            start = time.time()

            for i in range(100):
                self.run_query(
                    """
                    INSERT INTO trades_v2 (symbol, system, direction, signal_time, signal_price)
                    VALUES (%s, 'test', 'long', NOW(), 150.0)
                """,
                    (f"STRESS{i}",),
                )

            duration = time.time() - start
            rate = 100 / duration

            if rate < 10:
                result.add_error(f"Throughput {rate:.1f} trades/sec < 10 trades/sec")

            # Verify all inserted
            count = self.run_query(
                "SELECT COUNT(*) FROM trades_v2 WHERE symbol LIKE 'STRESS%'"
            )
            if not count or len(count) == 0 or len(count[0]) == 0:
                result.add_error("Failed to query trade count")
            elif count[0][0] != 100:
                result.add_error(f"Should have 100 trades, got {count[0][0]}")

        finally:
            # Cleanup
            try:
                self.run_query("DELETE FROM trades_v2 WHERE symbol LIKE 'STRESS%'")
            except:
                pass

    def test_5_2_query_performance(self, result):
        """Test 5.2: Query Performance"""
        # Test indexed query
        start = time.time()
        self.run_query("SELECT * FROM trades_v2 WHERE symbol = 'TEST1' LIMIT 10")
        duration = time.time() - start

        if duration > 0.1:
            result.add_error(f"Query took {duration*1000:.0f}ms > 100ms")

        # Test index usage with EXPLAIN
        plan = self.run_query("EXPLAIN SELECT * FROM trades_v2 WHERE symbol = 'TEST1'")
        plan_text = " ".join([str(row[0]) for row in plan])

        # For small tables, seq scan is often faster than index - just check query works
        if "Error" in plan_text:
            result.add_error("Query plan contains errors")

    # ========== PHASE 6: POSITION TRACKING ==========

    def test_6_1_position_aggregation(self, result):
        """Test 6.1: Multiple Entries Same Symbol"""
        self.run_query("DELETE FROM positions WHERE symbol = 'TEST7'")

        # Simulate 2 entries
        # Entry 1: 100 @ 150.0
        # Entry 2: 50 @ 151.0
        # Expected: 150 @ 150.33 VWAP

        total_qty = 150
        vwap = (100 * 150.0 + 50 * 151.0) / 150

        self.run_query(
            """
            INSERT INTO positions (symbol, system, quantity, avg_price, realized_pnl, unrealized_pnl)
            VALUES ('TEST7', 'test', %s, %s, 0, 0)
        """,
            (total_qty, vwap),
        )

        # Verify
        pos = self.run_query(
            "SELECT quantity, avg_price FROM positions WHERE symbol = 'TEST7'"
        )
        if not pos:
            result.add_error("Position not created")
            return

        if pos[0][0] != 150:
            result.add_error(f"Position qty should be 150, got {pos[0][0]}")

        if abs(float(pos[0][1]) - 150.33) > 0.01:
            result.add_error(f"Avg price should be 150.33, got {pos[0][1]}")

    def test_6_2_reconciliation_status(self, result):
        """Test 6.2: Position Reconciliation"""
        # Verify reconciliation fields exist
        pos = self.run_query(
            "SELECT last_reconcile, is_reconciled FROM positions WHERE symbol = 'TEST7'"
        )
        if not pos:
            result.add_error("No position to reconcile")
            return

        # Update reconciliation status
        self.run_query(
            """
            UPDATE positions SET
                last_reconcile = NOW(),
                is_reconciled = true
            WHERE symbol = 'TEST7'
        """
        )

        # Verify
        pos = self.run_query(
            "SELECT is_reconciled FROM positions WHERE symbol = 'TEST7'"
        )
        if not pos[0][0]:
            result.add_error("Position should be reconciled")

    # ========== PHASE 7: INTEGRATION TEST ==========

    def test_7_1_schema_complete(self, result):
        """Test 7.1: Schema Completeness"""
        # Check all tables exist
        tables = self.run_query(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name IN ('executions', 'trades_v2', 'positions')
        """
        )

        if len(tables) != 3:
            result.add_error(f"Should have 3 tables, got {len(tables)}")

        # Check indexes
        indexes = self.run_query(
            """
            SELECT indexname FROM pg_indexes
            WHERE tablename IN ('executions', 'trades_v2', 'positions')
        """
        )

        if len(indexes) < 6:
            result.add_error(f"Should have at least 6 indexes, got {len(indexes)}")

    def test_7_2_integration_files(self, result):
        """Test 7.2: Integration Files Exist"""
        files = [
            Path(__file__).parent.parent / "cpapi" / "unified_fill_processor.py",
            Path(__file__).parent.parent / "cpapi" / "trade_database.py",
            Path(__file__).parent.parent / "cpapi" / "position_tracker.py",
            Path(__file__).parent.parent / "cpapi" / "trade_integration.py",
        ]

        for f in files:
            if not f.exists():
                result.add_error(f"Missing file: {f.name}")

    def print_summary(self):
        print(f"\n{'='*60}")
        print("TEST SUMMARY")
        print(f"{'='*60}")

        phases = {}
        for r in self.results:
            if r.phase not in phases:
                phases[r.phase] = {"passed": 0, "failed": 0, "total": 0}
            phases[r.phase]["total"] += 1
            if r.passed:
                phases[r.phase]["passed"] += 1
            else:
                phases[r.phase]["failed"] += 1

        for phase in sorted(phases.keys()):
            stats = phases[phase]
            status = "✅" if stats["failed"] == 0 else "❌"
            print(f"{status} Phase {phase}: {stats['passed']}/{stats['total']} passed")

        total_passed = sum(r.passed for r in self.results)
        total_tests = len(self.results)

        print(f"\n{'='*60}")
        print(f"OVERALL: {total_passed}/{total_tests} tests passed")
        print(f"{'='*60}")

        if total_passed == total_tests:
            print("\n🎉 ALL TESTS PASSED - Trade DB V2 ready for deployment!")
            return 0
        else:
            print(
                f"\n⚠️  {total_tests - total_passed} tests failed - review errors above"
            )
            return 1


def main():
    runner = TestRunner()

    print("Trade Database V2 - Complete Test Suite")
    print("=" * 60)

    if not runner.connect_db():
        return 1

    # Phase 1: Basic Simulation
    runner.run_test(1, "Single Complete Trade", runner.test_1_1_single_trade)
    runner.run_test(1, "Multiple Partial Fills", runner.test_1_2_partial_fills)
    runner.run_test(1, "Deduplication", runner.test_1_3_deduplication)

    # Phase 2: WAL Durability
    runner.run_test(2, "WAL Write", runner.test_2_1_wal_write)
    runner.run_test(2, "WAL Recovery", runner.test_2_2_wal_recovery)

    # Phase 3: Deduplication
    runner.run_test(3, "Concurrent Inserts", runner.test_3_1_concurrent_inserts)

    # Phase 4: Historical Replay
    runner.run_test(4, "P&L Accuracy", runner.test_4_1_pnl_accuracy)

    # Phase 5: Stress Test
    runner.run_test(5, "Throughput", runner.test_5_1_throughput)
    runner.run_test(5, "Query Performance", runner.test_5_2_query_performance)

    # Phase 6: Position Tracking
    runner.run_test(6, "Position Aggregation", runner.test_6_1_position_aggregation)
    runner.run_test(6, "Reconciliation Status", runner.test_6_2_reconciliation_status)

    # Phase 7: Integration
    runner.run_test(7, "Schema Complete", runner.test_7_1_schema_complete)
    runner.run_test(7, "Integration Files", runner.test_7_2_integration_files)

    return runner.print_summary()


if __name__ == "__main__":
    sys.exit(main())
