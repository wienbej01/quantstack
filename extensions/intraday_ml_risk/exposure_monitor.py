"""Exposure monitoring for ML-powered risk management."""

import logging
import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from threading import Lock
from enum import Enum
import queue


class ExposureType(Enum):
    """Types of exposure to monitor."""
    GROSS = "gross"
    NET = "net"
    LONG = "long"
    SHORT = "short"
    LEVERAGE = "leverage"
    CONCENTRATION = "concentration"


@dataclass
class ExposureLimit:
    """Exposure limit configuration."""
    name: str
    exposure_type: ExposureType
    limit_value: float
    current_value: float = 0.0
    utilization: float = 0.0
    warning_threshold: float = 0.8
    critical_threshold: float = 0.95
    enabled: bool = True


@dataclass
class ExposureAlert:
    """Exposure alert information."""
    timestamp: datetime
    limit_name: str
    exposure_type: ExposureType
    current_value: float
    limit_value: float
    utilization: float
    severity: str  # "warning", "critical"
    message: str


@dataclass
class ExposureMetrics:
    """Current exposure metrics."""
    total_exposure: float
    net_exposure: float
    gross_exposure: float
    long_exposure: float
    short_exposure: float
    leverage_ratio: float
    concentration_ratio: float
    sector_exposures: Dict[str, float]
    currency_exposures: Dict[str, float]
    timestamp: datetime


class ExposureMonitor:
    """Exposure monitoring for ML-powered risk management."""

    def __init__(
        self,
        total_capital: float = 1000000.0,
        max_leverage: float = 2.0,
        max_concentration: float = 0.3,
        max_sector_exposure: float = 0.4,
        alerting_enabled: bool = True
    ):
        """
        Initialize exposure monitor.

        Args:
            total_capital: Total capital available
            max_leverage: Maximum leverage ratio
            max_concentration: Maximum concentration in single position
            max_sector_exposure: Maximum exposure to any sector
            alerting_enabled: Whether to enable alerts
        """
        self.total_capital = total_capital
        self.max_leverage = max_leverage
        self.max_concentration = max_concentration
        self.max_sector_exposure = max_sector_exposure
        self.alerting_enabled = alerting_enabled
        self.logger = logging.getLogger(__name__)
        self._lock = Lock()

        # Initialize limits
        self.limits = self._initialize_limits()

        # Position tracking
        self.positions = {}
        self.sector_mapping = {}
        self.currency_mapping = {}

        # Alert tracking
        self.alerts = queue.Queue(maxsize=1000)
        self.alert_history = []

    def _initialize_limits(self) -> Dict[str, ExposureLimit]:
        """Initialize exposure limits."""
        return {
            "total_gross": ExposureLimit(
                name="total_gross",
                exposure_type=ExposureType.GROSS,
                limit_value=self.total_capital * self.max_leverage,
                warning_threshold=0.8,
                critical_threshold=0.95
            ),
            "net_exposure": ExposureLimit(
                name="net_exposure",
                exposure_type=ExposureType.NET,
                limit_value=self.total_capital,
                warning_threshold=0.9,
                critical_threshold=1.0
            ),
            "single_position": ExposureLimit(
                name="single_position",
                exposure_type=ExposureType.CONCENTRATION,
                limit_value=self.total_capital * self.max_concentration,
                warning_threshold=0.8,
                critical_threshold=0.95
            ),
            "sector_exposure": ExposureLimit(
                name="sector_exposure",
                exposure_type=ExposureType.CONCENTRATION,
                limit_value=self.total_capital * self.max_sector_exposure,
                warning_threshold=0.8,
                critical_threshold=0.95
            )
        }

    def add_position(
        self,
        symbol: str,
        size: float,
        price: float,
        sector: Optional[str] = None,
        currency: str = "USD"
    ):
        """Add or update position."""
        with self._lock:
            exposure = size * price
            self.positions[symbol] = {
                "size": size,
                "price": price,
                "exposure": exposure,
                "sector": sector,
                "currency": currency,
                "timestamp": datetime.now()
            }

            if sector:
                self.sector_mapping[symbol] = sector
            self.currency_mapping[symbol] = currency

            # Check exposure limits
            self._check_all_limits()

    def remove_position(self, symbol: str):
        """Remove position."""
        with self._lock:
            if symbol in self.positions:
                del self.positions[symbol]
                self.sector_mapping.pop(symbol, None)
                self.currency_mapping.pop(symbol, None)

                # Recheck limits
                self._check_all_limits()

    def update_position_price(self, symbol: str, new_price: float):
        """Update position price."""
        with self._lock:
            if symbol in self.positions:
                position = self.positions[symbol]
                position["price"] = new_price
                position["exposure"] = position["size"] * new_price
                position["timestamp"] = datetime.now()

                # Check exposure limits
                self._check_all_limits()

    def get_current_exposures(self) -> ExposureMetrics:
        """Calculate current exposure metrics."""
        with self._lock:
            if not self.positions:
                return ExposureMetrics(
                    total_exposure=0.0,
                    net_exposure=0.0,
                    gross_exposure=0.0,
                    long_exposure=0.0,
                    short_exposure=0.0,
                    leverage_ratio=0.0,
                    concentration_ratio=0.0,
                    sector_exposures={},
                    currency_exposures={},
                    timestamp=datetime.now()
                )

            # Calculate exposures
            long_exposure = sum(pos["exposure"] for pos in self.positions.values() if pos["size"] > 0)
            short_exposure = sum(abs(pos["exposure"]) for pos in self.positions.values() if pos["size"] < 0)
            gross_exposure = long_exposure + short_exposure
            net_exposure = long_exposure - short_exposure

            # Calculate leverage
            leverage_ratio = gross_exposure / self.total_capital if self.total_capital > 0 else 0

            # Calculate concentration (largest position / total capital)
            max_exposure = max(abs(pos["exposure"]) for pos in self.positions.values())
            concentration_ratio = max_exposure / self.total_capital if self.total_capital > 0 else 0

            # Calculate sector exposures
            sector_exposures = {}
            for symbol, position in self.positions.items():
                sector = self.sector_mapping.get(symbol, "Unknown")
                if sector not in sector_exposures:
                    sector_exposures[sector] = 0.0
                sector_exposures[sector] += abs(position["exposure"])

            # Calculate currency exposures
            currency_exposures = {}
            for symbol, position in self.positions.items():
                currency = self.currency_mapping.get(symbol, "USD")
                if currency not in currency_exposures:
                    currency_exposures[currency] = 0.0
                currency_exposures[currency] += position["exposure"]

            return ExposureMetrics(
                total_exposure=gross_exposure,
                net_exposure=net_exposure,
                gross_exposure=gross_exposure,
                long_exposure=long_exposure,
                short_exposure=short_exposure,
                leverage_ratio=leverage_ratio,
                concentration_ratio=concentration_ratio,
                sector_exposures=sector_exposures,
                currency_exposures=currency_exposures,
                timestamp=datetime.now()
            )

    def _check_all_limits(self):
        """Check all exposure limits."""
        metrics = self.get_current_exposures()

        # Check total gross exposure
        self._check_limit("total_gross", metrics.gross_exposure)

        # Check net exposure
        self._check_limit("net_exposure", abs(metrics.net_exposure))

        # Check single position concentration
        if self.positions:
            max_position_exposure = max(abs(pos["exposure"]) for pos in self.positions.values())
            self._check_limit("single_position", max_position_exposure)

        # Check sector exposures
        for sector, exposure in metrics.sector_exposures.items():
            self._check_limit("sector_exposure", exposure, f"sector_{sector}")

    def _check_limit(self, limit_name: str, current_value: float, custom_name: Optional[str] = None):
        """Check individual exposure limit."""
        if limit_name not in self.limits:
            return

        limit = self.limits[limit_name]
        if not limit.enabled:
            return

        limit.current_value = current_value
        limit.utilization = current_value / limit.limit_value if limit.limit_value > 0 else 0

        display_name = custom_name or limit_name

        # Check for critical threshold
        if limit.utilization >= limit.critical_threshold:
            self._create_alert(
                limit_name=display_name,
                exposure_type=limit.exposure_type,
                current_value=current_value,
                limit_value=limit.limit_value,
                utilization=limit.utilization,
                severity="critical"
            )

        # Check for warning threshold
        elif limit.utilization >= limit.warning_threshold:
            self._create_alert(
                limit_name=display_name,
                exposure_type=limit.exposure_type,
                current_value=current_value,
                limit_value=limit.limit_value,
                utilization=limit.utilization,
                severity="warning"
            )

    def _create_alert(
        self,
        limit_name: str,
        exposure_type: ExposureType,
        current_value: float,
        limit_value: float,
        utilization: float,
        severity: str
    ):
        """Create exposure alert."""
        if not self.alerting_enabled:
            return

        alert = ExposureAlert(
            timestamp=datetime.now(),
            limit_name=limit_name,
            exposure_type=exposure_type,
            current_value=current_value,
            limit_value=limit_value,
            utilization=utilization,
            severity=severity,
            message=f"{severity.title()} exposure alert: {limit_name} at {utilization:.1%} utilization "
                   f"(${current_value:,.0f} / ${limit_value:,.0f})"
        )

        # Add to queues
        try:
            self.alerts.put_nowait(alert)
        except queue.Full:
            pass  # Remove oldest alert if queue is full
            try:
                self.alerts.get_nowait()
                self.alerts.put_nowait(alert)
            except queue.Empty:
                pass

        self.alert_history.append(alert)

        # Log alert
        if severity == "critical":
            self.logger.critical(alert.message)
        else:
            self.logger.warning(alert.message)

    def get_exposure_summary(self) -> Dict[str, Any]:
        """Get exposure monitoring summary."""
        metrics = self.get_current_exposures()
        limits_status = {}

        for name, limit in self.limits.items():
            limits_status[name] = {
                "current": limit.current_value,
                "limit": limit.limit_value,
                "utilization": limit.utilization,
                "status": "normal" if limit.utilization < limit.warning_threshold else
                         "warning" if limit.utilization < limit.critical_threshold else "critical"
            }

        # Get recent alerts
        recent_alerts = []
        temp_queue = queue.Queue()

        # Get up to 10 recent alerts
        for _ in range(min(10, self.alerts.qsize())):
            try:
                alert = self.alerts.get_nowait()
                recent_alerts.append({
                    "timestamp": alert.timestamp.isoformat(),
                    "limit_name": alert.limit_name,
                    "severity": alert.severity,
                    "message": alert.message
                })
                temp_queue.put(alert)
            except queue.Empty:
                break

        # Restore alerts to queue
        while not temp_queue.empty():
            try:
                self.alerts.put_nowait(temp_queue.get_nowait())
            except queue.Full:
                break

        return {
            "metrics": {
                "total_exposure": metrics.total_exposure,
                "net_exposure": metrics.net_exposure,
                "gross_exposure": metrics.gross_exposure,
                "leverage_ratio": metrics.leverage_ratio,
                "concentration_ratio": metrics.concentration_ratio,
                "long_exposure": metrics.long_exposure,
                "short_exposure": metrics.short_exposure
            },
            "limits": limits_status,
            "sector_exposures": metrics.sector_exposures,
            "currency_exposures": metrics.currency_exposures,
            "recent_alerts": recent_alerts,
            "total_positions": len(self.positions),
            "timestamp": metrics.timestamp.isoformat()
        }

    def update_limit(self, limit_name: str, new_limit: float):
        """Update exposure limit."""
        with self._lock:
            if limit_name in self.limits:
                self.limits[limit_name].limit_value = new_limit
                self.logger.info(f"Updated {limit_name} limit to ${new_limit:,.0f}")
                self._check_all_limits()
            else:
                self.logger.warning(f"Unknown limit: {limit_name}")

    def enable_alerting(self, enabled: bool):
        """Enable or disable alerting."""
        self.alerting_enabled = enabled
        self.logger.info(f"Alerting {'enabled' if enabled else 'disabled'}")

    def clear_alert_history(self):
        """Clear alert history."""
        with self._lock:
            self.alert_history.clear()
            # Clear alert queue
            while not self.alerts.empty():
                try:
                    self.alerts.get_nowait()
                except queue.Empty:
                    break

    def get_position_details(self) -> List[Dict[str, Any]]:
        """Get detailed position information."""
        with self._lock:
            positions = []
            for symbol, position in self.positions.items():
                positions.append({
                    "symbol": symbol,
                    "size": position["size"],
                    "price": position["price"],
                    "exposure": position["exposure"],
                    "sector": position.get("sector", "Unknown"),
                    "currency": position.get("currency", "USD"),
                    "timestamp": position["timestamp"].isoformat()
                })
            return positions

    def calculate_scenario_exposure(self, price_changes: Dict[str, float]) -> Dict[str, float]:
        """Calculate exposure under different price scenarios."""
        scenario_exposures = {}

        for scenario_name, price_change_pct in price_changes.items():
            total_exposure = 0.0

            for symbol, position in self.positions.items():
                new_price = position["price"] * (1 + price_change_pct)
                new_exposure = position["size"] * new_price
                total_exposure += new_exposure

            scenario_exposures[scenario_name] = total_exposure

        return scenario_exposures