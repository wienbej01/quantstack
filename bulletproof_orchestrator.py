#!/usr/bin/env python3
"""
Bulletproof Trading Orchestrator - monitors all trading systems and reports via NTFY.

Monitors:
1. SIP generation (pre-market)
2. L2 Collector service
3. L2 Scalping service  
4. Intraday Paper trading service
"""

import asyncio
import json
import logging
import os
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import httpx

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("/home/jacobw/quantstack/logs/orchestrator.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# Audit logger
audit_logger = logging.getLogger("audit")
audit_handler = logging.FileHandler(
    "/home/jacobw/quantstack/logs/orchestrator_audit.log"
)
audit_handler.setFormatter(logging.Formatter("%(asctime)s - AUDIT - %(message)s"))
audit_logger.addHandler(audit_handler)
audit_logger.setLevel(logging.INFO)


class AuditTracker:
    def __init__(self):
        self.operations = []
        self.start_time = datetime.now()

    def log_operation(self, operation: str, status: str, details: dict = None):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "operation": operation,
            "status": status,
            "details": details or {},
            "elapsed_seconds": (datetime.now() - self.start_time).total_seconds(),
        }
        self.operations.append(entry)
        audit_logger.info(json.dumps(entry))

    def get_summary(self) -> dict:
        total_time = (datetime.now() - self.start_time).total_seconds()
        success_count = sum(1 for op in self.operations if op["status"] == "SUCCESS")
        error_count = sum(
            1 for op in self.operations if op["status"] in ("ERROR", "FAILED")
        )
        return {
            "total_operations": len(self.operations),
            "successful": success_count,
            "failed": error_count,
            "total_time_seconds": total_time,
        }


class NotificationManager:
    def __init__(self):
        self.base_url = "https://ntfy.sh"
        self.topics = {
            "status": "jacobw-trading-status",
            "data": "jacobw-trading-data",
            "alerts": "jacobw-trading-alerts",
            "trades": "jacobw-trading-trades",
        }

    async def send(
        self,
        topic: str,
        title: str,
        message: str,
        priority: str = "default",
        tags: str = "",
    ):
        try:
            topic_name = self.topics.get(topic, topic)
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    f"{self.base_url}/{topic_name}",
                    data=message,
                    headers={"Title": title, "Priority": priority, "Tags": tags},
                )
            logger.info(f"Notification sent: {topic} - {title}")
        except Exception as e:
            logger.error(f"Failed to send notification: {e}")


class ServiceMonitor:
    """Monitor systemd services and report status."""

    SERVICES = {
        "l2-collector": "L2 Collector",
        "l2-scalping": "L2 Scalping",
        "intraday-paper": "Intraday Paper",
        "l2-watchdog": "L2 Watchdog",
    }

    def __init__(self, audit: AuditTracker):
        self.audit = audit

    def check_service(self, service_name: str) -> dict:
        """Check systemd service status."""
        try:
            # Get detailed status
            result = subprocess.run(
                [
                    "systemctl",
                    "show",
                    service_name,
                    "--property=ActiveState,SubState,ExecMainStatus",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            props = dict(
                line.split("=", 1)
                for line in result.stdout.strip().split("\n")
                if "=" in line
            )

            active_state = props.get("ActiveState", "unknown")
            sub_state = props.get("SubState", "unknown")
            exit_code = props.get("ExecMainStatus", "0")

            # Service is OK if: running OR completed successfully (exit 0)
            is_ok = active_state == "active" or (
                active_state == "inactive" and exit_code == "0"
            )
            is_running = active_state == "active"

            # Get recent errors from journal
            errors = []
            err_result = subprocess.run(
                [
                    "journalctl",
                    "-u",
                    service_name,
                    "--since",
                    "10 minutes ago",
                    "--no-pager",
                    "-p",
                    "err",
                    "-o",
                    "cat",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if err_result.stdout.strip():
                errors = err_result.stdout.strip().split("\n")[-5:]

            return {
                "ok": is_ok,
                "running": is_running,
                "state": f"{active_state}/{sub_state}",
                "errors": errors,
            }
        except Exception as e:
            return {"ok": False, "running": False, "state": "error", "errors": [str(e)]}

    def check_all_services(self) -> dict:
        """Check all monitored services."""
        results = {}
        for svc_name, display_name in self.SERVICES.items():
            status = self.check_service(svc_name)
            results[svc_name] = {
                "display_name": display_name,
                "ok": status["ok"],
                "running": status["running"],
                "state": status["state"],
                "errors": status["errors"],
            }
            self.audit.log_operation(
                f"service_check_{svc_name}",
                "SUCCESS" if status["ok"] else "FAILED",
                {
                    "running": status["running"],
                    "state": status["state"],
                    "errors": len(status["errors"]),
                },
            )
        return results


class GatewayManager:
    """Check IBKR Gateway status (no programmatic start - manual only)."""

    def __init__(self, audit: AuditTracker):
        self.gateway_host = "127.0.0.1"
        self.gateway_port = 7497
        self.audit = audit

    def _count_gateway_processes(self) -> tuple[int, list[str]]:
        """Count running ibgateway/TWS processes and return PIDs."""
        try:
            # Only count the main Java processes, not shell wrappers
            result = subprocess.run(
                ["pgrep", "-f", "ibcalpha.ibc.IbcGateway|com.ib.tws"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            pids = [p.strip() for p in result.stdout.strip().split("\n") if p.strip()]
            return len(pids), pids
        except Exception:
            return 0, []

    def _check_docker_gateway(self) -> str | None:
        """Check if any ib-gateway Docker container exists."""
        try:
            result = subprocess.run(
                [
                    "docker",
                    "ps",
                    "-a",
                    "--filter",
                    "name=ib-gateway",
                    "--format",
                    "{{.Names}}:{{.Status}}",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass
        return None

    async def check_gateway_health(self) -> tuple[bool, str | None]:
        """Check gateway health and detect conflicts. Returns (ok, warning_msg)."""
        warning = None

        # Check for duplicate processes
        proc_count, pids = self._count_gateway_processes()
        if proc_count > 1:
            warning = (
                f"DUPLICATE GATEWAYS: {proc_count} processes (PIDs: {', '.join(pids)})"
            )
            logger.warning(warning)
            self.audit.log_operation(
                "gateway_duplicate_check",
                "WARNING",
                {"count": proc_count, "pids": pids},
            )

        # Check for Docker container
        docker_status = self._check_docker_gateway()
        if docker_status:
            docker_warn = f"Docker ib-gateway exists: {docker_status}"
            warning = f"{warning}; {docker_warn}" if warning else docker_warn
            logger.warning(docker_warn)
            self.audit.log_operation(
                "gateway_docker_check", "WARNING", {"status": docker_status}
            )

        # Check port connectivity
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            result = sock.connect_ex((self.gateway_host, self.gateway_port))
            sock.close()
            if result == 0:
                logger.info("IBKR Gateway accessible on port 7497")
                self.audit.log_operation(
                    "gateway_health_check", "SUCCESS", {"port": 7497}
                )
                return True, warning
            logger.error("IBKR Gateway NOT accessible - start manually")
            self.audit.log_operation("gateway_health_check", "FAILED", {"port": 7497})
            return False, warning
        except Exception as e:
            logger.error(f"Gateway health check failed: {e}")
            self.audit.log_operation("gateway_health_check", "ERROR", {"error": str(e)})
            return False, warning


class TradeMonitor:
    """Monitor trade activity and report via NTFY."""

    def __init__(self, notifications: NotificationManager, audit: AuditTracker):
        self.notifications = notifications
        self.audit = audit
        self.trade_journal = Path("/home/jacobw/quantstack/l2_scalping/data")

    async def check_recent_trades(self, target_date: str) -> dict:
        """Check for trades executed today."""
        trade_file = self.trade_journal / f"trades_{target_date.replace('-', '')}.jsonl"
        trades = []
        if trade_file.exists():
            with open(trade_file) as f:
                for line in f:
                    if line.strip():
                        trades.append(json.loads(line))

        self.audit.log_operation("trade_check", "SUCCESS", {"count": len(trades)})
        return {"count": len(trades), "trades": trades[-10:]}  # Last 10

    async def report_trades(self, target_date: str):
        """Report trade summary via NTFY."""
        trade_info = await self.check_recent_trades(target_date)
        if trade_info["count"] > 0:
            last_trade = trade_info["trades"][-1] if trade_info["trades"] else {}
            await self.notifications.send(
                "trades",
                f"Trades Today: {trade_info['count']}",
                f"Last: {last_trade.get('symbol', 'N/A')} {last_trade.get('side', '')} @ {last_trade.get('price', '')}",
                tags="chart_with_upwards_trend",
            )


class L2CollectionMonitor:
    """Monitor L2 data collection performance."""

    def __init__(self, audit: AuditTracker):
        self.audit = audit
        self.journal_db = Path("/home/jacobw/quantstack/data/l2_maximum/journal.db")

    def check_collection_status(self, target_date: str) -> dict:
        """Check L2 collection status from journal."""
        import sqlite3

        if not self.journal_db.exists():
            return {"ok": False, "error": "journal.db not found"}

        try:
            conn = sqlite3.connect(self.journal_db)
            cursor = conn.cursor()

            # Get active session
            cursor.execute(
                "SELECT session_id, start_time, records_collected, symbols FROM sessions "
                "WHERE status = 'running' ORDER BY start_time DESC LIMIT 1"
            )
            active = cursor.fetchone()

            # Get today's totals
            cursor.execute(
                "SELECT SUM(records_collected) as total, COUNT(*) as sessions "
                "FROM sessions WHERE start_time LIKE ?",
                (f"{target_date}%",),
            )
            totals = cursor.fetchone()

            # Get recent errors
            cursor.execute(
                "SELECT COUNT(*) FROM errors WHERE timestamp LIKE ?",
                (f"{target_date}%",),
            )
            errors = cursor.fetchone()[0]

            conn.close()

            result = {
                "ok": True,
                "active_session": active[0] if active else None,
                "active_records": active[2] if active else 0,
                "active_symbols": active[3] if active else "[]",
                "total_records": totals[0] or 0,
                "total_sessions": totals[1] or 0,
                "errors": errors,
            }

            self.audit.log_operation(
                "l2_collection_check",
                "SUCCESS",
                {
                    "active_records": result["active_records"],
                    "total_records": result["total_records"],
                    "errors": errors,
                },
            )

            return result

        except Exception as e:
            self.audit.log_operation("l2_collection_check", "ERROR", {"error": str(e)})
            return {"ok": False, "error": str(e)}


class BulletproofOrchestrator:
    def __init__(self):
        self.audit = AuditTracker()
        self.notifications = NotificationManager()
        self.gateway_manager = GatewayManager(self.audit)
        self.service_monitor = ServiceMonitor(self.audit)
        self.trade_monitor = TradeMonitor(self.notifications, self.audit)
        self.l2_monitor = L2CollectionMonitor(self.audit)

        self.quantstack_dir = Path("/home/jacobw/quantstack")
        self.intraday_dir = Path("/home/jacobw/intraday_stack")

    async def run_sip_generation(self, target_date: str) -> bool:
        """Run SIP generation using the intraday_stack script with Polygon data."""
        try:
            logger.info(f"Running SIP generation for {target_date} via intraday_stack")
            self.audit.log_operation(
                "sip_generation_start", "STARTED", {"date": target_date}
            )

            cmd = [
                sys.executable,
                str(self.intraday_dir / "scripts" / "generate_daily_sip_universe.py"),
                "--date",
                target_date,
                "--data-source",
                "polygon",
                "--min-price",
                "2.0",
                "--max-price",
                "200.0",
                "--min-dv-pre",
                "5000000",
                "--score-floor",
                "0.70",
                "--workers",
                "8",
            ]

            env = os.environ.copy()
            env["POLYGON_API_KEY"] = os.environ.get("POLYGON_API_KEY", "")
            env["PYTHONPATH"] = str(self.intraday_dir)

            logger.info(f"Executing: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                cwd=str(self.intraday_dir),
                env=env,
                capture_output=True,
                text=True,
                timeout=900,
            )

            if result.returncode == 0:
                logger.info("SIP generation completed successfully")
                await self._copy_sip_artifact(target_date)
                self.audit.log_operation(
                    "sip_generation", "SUCCESS", {"date": target_date}
                )
                return True
            else:
                logger.error(f"SIP generation failed: {result.stderr[-500:]}")
                self.audit.log_operation(
                    "sip_generation", "ERROR", {"stderr": result.stderr[-500:]}
                )
                return False

        except subprocess.TimeoutExpired:
            logger.error("SIP generation timed out")
            self.audit.log_operation("sip_generation", "ERROR", {"error": "timeout"})
            return False
        except Exception as e:
            logger.error(f"SIP generation failed: {e}")
            self.audit.log_operation("sip_generation", "ERROR", {"error": str(e)})
            return False

    async def _copy_sip_artifact(self, target_date: str):
        """Copy SIP artifact to quantstack location."""
        try:
            src = (
                self.intraday_dir
                / "data"
                / "daily_sip"
                / f"date={target_date}"
                / "sip_universe.json"
            )
            if not src.exists():
                return

            with open(src) as f:
                artifact = json.load(f)

            dst_dir = self.quantstack_dir / "data" / "daily_sip"
            dst_dir.mkdir(parents=True, exist_ok=True)

            txt_file = dst_dir / f"sip_universe_{target_date}.txt"
            with open(txt_file, "w") as f:
                f.write("\n".join(artifact.get("symbols", [])))

            logger.info(
                f"Copied SIP artifact: {len(artifact.get('symbols', []))} symbols"
            )
        except Exception as e:
            logger.error(f"Failed to copy SIP artifact: {e}")

    async def monitor_all_services(self) -> dict:
        """Monitor all trading services and report errors."""
        logger.info("Checking all trading services...")
        results = self.service_monitor.check_all_services()

        errors = []
        failed = []
        for svc_name, status in results.items():
            if not status["ok"]:
                failed.append(f"{status['display_name']} ({status['state']})")
            if status["errors"]:
                errors.extend(
                    [f"{status['display_name']}: {e}" for e in status["errors"][:2]]
                )

        # Report errors via NTFY
        if errors:
            await self.notifications.send(
                "alerts",
                f"Service Errors ({len(errors)})",
                "\n".join(errors[:5]),
                priority="high",
                tags="warning",
            )

        if failed:
            await self.notifications.send(
                "alerts",
                "Services Failed",
                f"Failed: {', '.join(failed)}",
                priority="high",
                tags="x",
            )

        return results

    async def run_premarket_sequence(self):
        """Run complete pre-market sequence."""
        from zoneinfo import ZoneInfo

        target_date = datetime.now(ZoneInfo("US/Eastern")).strftime("%Y-%m-%d")

        try:
            logger.info("Starting bulletproof pre-market sequence")
            self.audit.log_operation("premarket_sequence_start", "STARTED", {})

            await self.notifications.send(
                "status",
                "Pre-Market Sequence Started",
                f"Orchestrator starting at {datetime.now().strftime('%H:%M:%S')}",
                tags="rocket",
            )

            # 1. Check Gateway (must be started manually)
            gateway_ok, gateway_warning = (
                await self.gateway_manager.check_gateway_health()
            )
            if not gateway_ok:
                await self.notifications.send(
                    "alerts",
                    "IBKR Gateway DOWN",
                    "Gateway not accessible on port 7497 - start manually!",
                    priority="urgent",
                    tags="rotating_light",
                )
            if gateway_warning:
                await self.notifications.send(
                    "alerts",
                    "Gateway Conflict Detected",
                    gateway_warning,
                    priority="high",
                    tags="warning",
                )

            # 2. Generate SIP universe
            sip_success = await self.run_sip_generation(target_date)

            # 3. Monitor all services
            service_status = await self.monitor_all_services()

            # 4. Check for trades
            await self.trade_monitor.report_trades(target_date)

            # 5. Check L2 collection
            l2_status = self.l2_monitor.check_collection_status(target_date)

            # Final notification
            if sip_success:
                artifact_path = (
                    self.intraday_dir
                    / "data"
                    / "daily_sip"
                    / f"date={target_date}"
                    / "sip_universe.json"
                )
                symbol_count = 0
                top_symbols = []
                if artifact_path.exists():
                    with open(artifact_path) as f:
                        artifact = json.load(f)
                    symbol_count = len(artifact.get("symbols", []))
                    top_symbols = artifact.get("symbols", [])[:5]

                ok_services = sum(1 for s in service_status.values() if s["ok"])
                running_services = sum(
                    1 for s in service_status.values() if s["running"]
                )
                l2_records = l2_status.get("total_records", 0)
                await self.notifications.send(
                    "status",
                    "Pre-Market Complete",
                    f"SIP: {symbol_count} symbols\nTop: {', '.join(top_symbols)}\nServices: {ok_services}/4 ok, {running_services} running\nL2: {l2_records:,} records\nGateway: {'✅' if gateway_ok else '❌'}",
                    tags="white_check_mark",
                )
                self.audit.log_operation(
                    "premarket_sequence", "SUCCESS", {"symbol_count": symbol_count}
                )
                return True
            else:
                await self.notifications.send(
                    "alerts",
                    "SIP Generation Failed",
                    f"Failed to generate SIP universe for {target_date}",
                    priority="high",
                    tags="x",
                )
                self.audit.log_operation(
                    "premarket_sequence", "FAILED", {"step": "sip_generation"}
                )
                return False

        except Exception as e:
            logger.error(f"Pre-market sequence failed: {e}")
            await self.notifications.send(
                "alerts",
                "Pre-Market CRASHED",
                str(e),
                priority="urgent",
                tags="rotating_light",
            )
            self.audit.log_operation("premarket_sequence", "ERROR", {"error": str(e)})
            return False
        finally:
            summary = self.audit.get_summary()
            logger.info(
                f"Summary: {summary['successful']}/{summary['total_operations']} ops in {summary['total_time_seconds']:.1f}s"
            )


async def main():
    orchestrator = BulletproofOrchestrator()
    success = await orchestrator.run_premarket_sequence()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
