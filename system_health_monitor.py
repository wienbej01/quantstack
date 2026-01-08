#!/usr/bin/env python3
"""
System Health Monitor - Monitors all systemd services and sends NTFY alerts
"""

import asyncio
import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path

import httpx

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("/home/jacobw/quantstack/logs/system_monitor.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


class SystemHealthMonitor:
    """Monitor all trading system services and send alerts."""

    def __init__(self):
        self.base_url = "https://ntfy.sh"
        self.alert_topic = "jacobw-trading-alerts"
        self.status_topic = "jacobw-trading-status"

        self.services = [
            "trading-orchestrator.service",
            "l2-collector.service",
            "ibkr-gateway.service",
        ]

    async def send_notification(
        self,
        topic: str,
        title: str,
        message: str,
        priority: str = "high",
        tags: str = "warning",
    ):
        """Send NTFY notification."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/{topic}",
                    data=message,
                    headers={"Title": title, "Priority": priority, "Tags": tags},
                )
                response.raise_for_status()
                logger.info(f"Alert sent: {title}")
                return True
        except Exception as e:
            logger.error(f"Failed to send alert: {e}")
            return False

    def check_service_status(self, service: str) -> dict:
        """Check systemd service status."""
        try:
            result = subprocess.run(
                ["systemctl", "is-active", service],
                capture_output=True,
                text=True,
                check=False,
            )

            status = result.stdout.strip()

            # Get detailed status
            detail_result = subprocess.run(
                ["systemctl", "status", service, "--no-pager", "-l"],
                capture_output=True,
                text=True,
                check=False,
            )

            return {
                "service": service,
                "status": status,
                "active": status == "active",
                "details": detail_result.stdout,
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"Failed to check {service}: {e}")
            return {
                "service": service,
                "status": "error",
                "active": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
            }

    async def check_all_services(self) -> dict:
        """Check all services and return status summary."""
        results = {}
        failed_services = []

        for service in self.services:
            status = self.check_service_status(service)
            results[service] = status

            if not status["active"]:
                failed_services.append(service)

        return {
            "timestamp": datetime.now().isoformat(),
            "total_services": len(self.services),
            "failed_services": failed_services,
            "failed_count": len(failed_services),
            "all_healthy": len(failed_services) == 0,
            "details": results,
        }

    async def check_sip_universe_exists(self) -> bool:
        """Check if today's SIP universe exists."""
        today = datetime.now().strftime("%Y-%m-%d")
        sip_file = Path(
            f"/home/jacobw/intraday_stack/data/daily_sip/date={today}/sip_universe.json"
        )
        return sip_file.exists()

    async def run_health_check(self):
        """Run comprehensive health check and send alerts."""
        logger.info("Starting system health check...")

        # Check all services
        service_status = await self.check_all_services()

        # Check SIP universe
        sip_exists = await self.check_sip_universe_exists()

        # Generate alerts for failed services
        if service_status["failed_count"] > 0:
            failed_list = "\n".join(
                [
                    f"❌ {service}: {service_status['details'][service]['status']}"
                    for service in service_status["failed_services"]
                ]
            )

            await self.send_notification(
                self.alert_topic,
                f"🚨 {service_status['failed_count']} Service(s) Failed",
                f"Failed services:\n{failed_list}\n\nTime: {datetime.now().strftime('%H:%M:%S ET')}",
                priority="high",
                tags="rotating_light,warning",
            )

        # Alert if SIP universe missing
        if not sip_exists:
            await self.send_notification(
                self.alert_topic,
                "📊 SIP Universe Missing",
                f"No SIP universe found for {datetime.now().strftime('%Y-%m-%d')}\nL2 collector will fail until SIP is generated",
                priority="high",
                tags="chart_with_downwards_trend,warning",
            )

        # Send status summary
        status_emoji = "✅" if service_status["all_healthy"] and sip_exists else "⚠️"
        summary = f"""{status_emoji} System Health Check
        
Services: {service_status['total_services'] - service_status['failed_count']}/{service_status['total_services']} healthy
SIP Universe: {"✅" if sip_exists else "❌"}
Time: {datetime.now().strftime('%H:%M:%S ET')}

Failed: {', '.join(service_status['failed_services']) if service_status['failed_services'] else 'None'}"""

        await self.send_notification(
            self.status_topic,
            "System Health Report",
            summary,
            priority="default",
            tags="information_source",
        )

        # Log detailed results
        logger.info(f"Health check complete: {json.dumps(service_status, indent=2)}")

        return service_status["all_healthy"] and sip_exists


async def main():
    """Run health check."""
    monitor = SystemHealthMonitor()
    healthy = await monitor.run_health_check()
    exit(0 if healthy else 1)


if __name__ == "__main__":
    asyncio.run(main())
