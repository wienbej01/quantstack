"""Production monitoring for ML model deployments."""

import logging
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import numpy as np

try:
    from prometheus_client import (
        CollectorRegistry,
        Counter,
        Gauge,
        Histogram,
        start_http_server,
    )

    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    Counter = None
    Histogram = None
    Gauge = None
    CollectorRegistry = None
    start_http_server = None

try:
    import requests

    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    requests = None

try:
    from sklearn.metrics import (
        accuracy_score,
        mean_absolute_error,
        mean_squared_error,
        precision_recall_fscore_support,
        r2_score,
    )

    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    accuracy_score = None
    precision_recall_fscore_support = None
    mean_squared_error = None
    mean_absolute_error = None
    r2_score = None

from extensions.intraday_ml_models.registry import MLModelRegistry
from extensions.intraday_ml_serving.inference_engine import InferenceEngine


@dataclass
class MonitoringMetrics:
    """Comprehensive monitoring metrics for ML deployments."""

    timestamp: datetime
    model_id: str
    deployment_id: str

    # Inference metrics
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    avg_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    requests_per_second: float = 0.0

    # Model performance metrics
    prediction_accuracy: float | None = None
    prediction_mse: float | None = None
    prediction_mae: float | None = None
    prediction_r2: float | None = None
    confidence_distribution: dict[str, float] = field(default_factory=dict)

    # System metrics
    cpu_usage_percent: float = 0.0
    memory_usage_mb: float = 0.0
    gpu_usage_percent: float = 0.0
    disk_io_mb_per_sec: float = 0.0
    network_io_mb_per_sec: float = 0.0

    # Business metrics
    trades_generated: int = 0
    win_rate: float = 0.0
    avg_return_per_trade: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0

    @property
    def error_rate(self) -> float:
        """Calculate error rate from requests."""
        return self.failed_requests / max(self.total_requests, 1)

    @property
    def success_rate(self) -> float:
        """Calculate success rate from requests."""
        return self.successful_requests / max(self.total_requests, 1)


@dataclass
class AlertConfig:
    """Configuration for monitoring alerts."""

    metric_name: str
    threshold: float
    operator: str  # "gt", "lt", "eq"
    duration_minutes: int = 5
    severity: str = "warning"  # "info", "warning", "critical"
    enabled: bool = True


class MetricsCollector:
    """Collects metrics from various sources."""

    def __init__(self, collection_interval_seconds: int = 30):
        self.collection_interval = collection_interval_seconds
        self.logger = logging.getLogger(__name__)
        self._stop_event = threading.Event()
        self._collection_thread = None

        # Metrics storage
        self.metrics_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self._metrics_lock = threading.Lock()

    def start_collection(self):
        """Start metrics collection thread."""
        if self._collection_thread is not None:
            return

        self._collection_thread = threading.Thread(
            target=self._collection_loop, daemon=True
        )
        self._collection_thread.start()
        self.logger.info("Metrics collection started")

    def stop_collection(self):
        """Stop metrics collection thread."""
        self._stop_event.set()
        if self._collection_thread:
            self._collection_thread.join()
        self.logger.info("Metrics collection stopped")

    def _collection_loop(self):
        """Main collection loop."""
        while not self._stop_event.is_set():
            try:
                # Collect system metrics
                system_metrics = self._collect_system_metrics()

                # Collect application metrics
                app_metrics = self._collect_application_metrics()

                # Store metrics
                timestamp = datetime.now()
                self._store_metrics(timestamp, {**system_metrics, **app_metrics})

                # Wait for next collection
                time.sleep(self.collection_interval)

            except Exception as e:
                self.logger.error(f"Metrics collection error: {e}")

    def _collect_system_metrics(self) -> dict[str, float]:
        """Collect system-level metrics."""
        try:
            import psutil

            # CPU metrics
            cpu_percent = psutil.cpu_percent(interval=1)

            # Memory metrics
            memory = psutil.virtual_memory()
            memory_usage_mb = memory.used / (1024 * 1024)

            # Disk I/O metrics
            disk_io = psutil.disk_io_counters()
            disk_io_mb_per_sec = 0.0
            if disk_io:
                disk_io_mb_per_sec = (disk_io.read_bytes + disk_io.write_bytes) / (
                    1024 * 1024
                )

            # Network I/O metrics
            network_io = psutil.net_io_counters()
            network_io_mb_per_sec = 0.0
            if network_io:
                network_io_mb_per_sec = (
                    network_io.bytes_sent + network_io.bytes_recv
                ) / (1024 * 1024)

            return {
                "cpu_usage_percent": cpu_percent,
                "memory_usage_mb": memory_usage_mb,
                "disk_io_mb_per_sec": disk_io_mb_per_sec,
                "network_io_mb_per_sec": network_io_mb_per_sec,
            }

        except Exception as e:
            self.logger.error(f"System metrics collection failed: {e}")
            return {}

    def _collect_application_metrics(self) -> dict[str, float]:
        """Collect application-level metrics."""
        # This would be implemented by the specific application
        # For now, return empty dict
        return {}

    def _store_metrics(self, timestamp: datetime, metrics: dict[str, float]):
        """Store metrics in history."""
        with self._metrics_lock:
            for key, value in metrics.items():
                self.metrics_history[key].append((timestamp, value))

    def get_metrics_history(
        self,
        metric_name: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[tuple]:
        """Get metrics history for a specific metric."""
        with self._metrics_lock:
            history = list(self.metrics_history[metric_name])

        if start_time or end_time:
            filtered_history = []
            for timestamp, value in history:
                if start_time and timestamp < start_time:
                    continue
                if end_time and timestamp > end_time:
                    continue
                filtered_history.append((timestamp, value))
            return filtered_history

        return history

    def get_latest_metrics(self) -> dict[str, Any]:
        """Get the latest metrics for all tracked metrics."""
        latest_metrics = {}
        with self._metrics_lock:
            for metric_name, history in self.metrics_history.items():
                if history:
                    latest_metrics[metric_name] = history[-1][
                        1
                    ]  # Get value from latest tuple
        return latest_metrics


class AlertManager:
    """Manages alerting based on monitoring metrics."""

    def __init__(self, alert_configs: list[AlertConfig]):
        self.alert_configs = {config.metric_name: config for config in alert_configs}
        self.logger = logging.getLogger(__name__)
        self._alert_states: dict[str, dict[str, Any]] = {}
        self._callbacks: list[Callable] = []

    def add_alert_callback(self, callback: Callable[[str, dict[str, Any]], None]):
        """Add callback for alert notifications."""
        self._callbacks.append(callback)

    def check_alerts(self, metrics: dict[str, float]):
        """Check if any alerts should be triggered."""
        timestamp = datetime.now()

        for metric_name, current_value in metrics.items():
            if metric_name not in self.alert_configs:
                continue

            config = self.alert_configs[metric_name]
            if not config.enabled:
                continue

            # Check if threshold is breached
            breached = self._check_threshold(
                current_value, config.threshold, config.operator
            )

            if metric_name not in self._alert_states:
                self._alert_states[metric_name] = {
                    "breached": False,
                    "first_breached": None,
                    "notifications_sent": 0,
                }

            state = self._alert_states[metric_name]

            if breached and not state["breached"]:
                # Alert just started
                state["breached"] = True
                state["first_breached"] = timestamp
            elif not breached and state["breached"]:
                # Alert recovered
                state["breached"] = False
                state["first_breached"] = None
                state["notifications_sent"] = 0

            # Check if we should send notification
            if (
                state["breached"]
                and state["first_breached"]
                and (timestamp - state["first_breached"])
                >= timedelta(minutes=config.duration_minutes)
            ) and state[
                "notifications_sent"
            ] == 0:  # Only send once per breach
                self._send_alert(metric_name, current_value, config, timestamp)
                state["notifications_sent"] = 1

    def _check_threshold(self, value: float, threshold: float, operator: str) -> bool:
        """Check if value breaches threshold."""
        if operator == "gt":
            return value > threshold
        elif operator == "lt":
            return value < threshold
        elif operator == "eq":
            return abs(value - threshold) < 1e-9
        else:
            return False

    def _send_alert(
        self, metric_name: str, value: float, config: AlertConfig, timestamp: datetime
    ):
        """Send alert notification."""
        alert_data = {
            "metric_name": metric_name,
            "current_value": value,
            "threshold": config.threshold,
            "operator": config.operator,
            "severity": config.severity,
            "timestamp": timestamp.isoformat(),
            "message": f"Alert: {metric_name} is {value} (threshold: {config.threshold})",
        }

        self.logger.warning(f"Alert triggered: {alert_data['message']}")

        # Call all registered callbacks
        for callback in self._callbacks:
            try:
                callback(metric_name, alert_data)
            except Exception as e:
                self.logger.error(f"Alert callback failed: {e}")


class PerformanceMonitor:
    """Monitors ML model performance in production."""

    def __init__(
        self,
        model_registry: MLModelRegistry | None = None,
        inference_engine: InferenceEngine | None = None,
        window_size_minutes: int = 60,
    ):
        self.model_registry = model_registry or MLModelRegistry()
        self.inference_engine = inference_engine
        self.window_size = timedelta(minutes=window_size_minutes)

        self.logger = logging.getLogger(__name__)

        # Performance data storage
        self.predictions_buffer: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.performance_metrics: dict[str, MonitoringMetrics] = {}

    def record_prediction(
        self,
        model_id: str,
        deployment_id: str,
        prediction: float,
        confidence: float | None,
        features: dict[str, float],
        actual: float | None = None,
        latency_ms: float = 0.0,
        timestamp: datetime | None = None,
    ):
        """Record a prediction for performance monitoring."""
        if timestamp is None:
            timestamp = datetime.now()

        prediction_data = {
            "timestamp": timestamp,
            "prediction": prediction,
            "confidence": confidence,
            "features": features,
            "actual": actual,
            "latency_ms": latency_ms,
        }

        self.predictions_buffer[model_id].append(prediction_data)

        # Clean old data
        self._clean_old_predictions(model_id)

        # Update metrics
        self._update_performance_metrics(model_id, deployment_id)

    def record_actual(
        self, model_id: str, actual: float, timestamp: datetime | None = None
    ):
        """Record actual value for a previous prediction."""
        if timestamp is None:
            timestamp = datetime.now()

        # Find matching prediction and update it
        for prediction_data in reversed(self.predictions_buffer[model_id]):
            if (
                prediction_data["actual"] is None
                and prediction_data["timestamp"] <= timestamp
            ):
                prediction_data["actual"] = actual
                break

    def _clean_old_predictions(self, model_id: str):
        """Remove old predictions outside the monitoring window."""
        cutoff_time = datetime.now() - self.window_size
        self.predictions_buffer[model_id] = [
            p for p in self.predictions_buffer[model_id] if p["timestamp"] > cutoff_time
        ]

    def _update_performance_metrics(self, model_id: str, deployment_id: str):
        """Update performance metrics for a model."""
        predictions = self.predictions_buffer[model_id]
        if not predictions:
            return

        # Calculate basic metrics
        total_requests = len(predictions)
        successful_requests = sum(1 for p in predictions if p["prediction"] is not None)
        failed_requests = total_requests - successful_requests

        # Latency metrics
        latencies = [p["latency_ms"] for p in predictions if p["latency_ms"] > 0]
        avg_latency_ms = np.mean(latencies) if latencies else 0.0
        p95_latency_ms = np.percentile(latencies, 95) if latencies else 0.0
        p99_latency_ms = np.percentile(latencies, 99) if latencies else 0.0

        # Calculate requests per second
        if len(predictions) >= 2:
            time_span = (
                predictions[-1]["timestamp"] - predictions[0]["timestamp"]
            ).total_seconds()
            requests_per_second = total_requests / time_span if time_span > 0 else 0.0
        else:
            requests_per_second = 0.0

        # Calculate model performance metrics
        prediction_accuracy = None
        prediction_mse = None
        prediction_mae = None
        prediction_r2 = None

        predictions_with_actual = [p for p in predictions if p["actual"] is not None]
        if predictions_with_actual:
            preds = [p["prediction"] for p in predictions_with_actual]
            actuals = [p["actual"] for p in predictions_with_actual]

            try:
                prediction_mse = mean_squared_error(actuals, preds)
                prediction_mae = mean_absolute_error(actuals, preds)
                prediction_r2 = r2_score(actuals, preds)

                # For classification models, calculate accuracy
                if all(p in [0, 1] for p in preds + actuals):
                    prediction_accuracy = accuracy_score(actuals, preds)

            except Exception as e:
                self.logger.error(f"Performance calculation failed: {e}")

        # Confidence distribution
        confidences = [
            p["confidence"] for p in predictions if p["confidence"] is not None
        ]
        confidence_distribution = {}
        if confidences:
            confidence_distribution = {
                "mean": np.mean(confidences),
                "std": np.std(confidences),
                "min": np.min(confidences),
                "max": np.max(confidences),
            }

        # Create metrics object
        metrics = MonitoringMetrics(
            timestamp=datetime.now(),
            model_id=model_id,
            deployment_id=deployment_id,
            total_requests=total_requests,
            successful_requests=successful_requests,
            failed_requests=failed_requests,
            avg_latency_ms=avg_latency_ms,
            p95_latency_ms=p95_latency_ms,
            p99_latency_ms=p99_latency_ms,
            requests_per_second=requests_per_second,
            prediction_accuracy=prediction_accuracy,
            prediction_mse=prediction_mse,
            prediction_mae=prediction_mae,
            prediction_r2=prediction_r2,
            confidence_distribution=confidence_distribution,
        )

        self.performance_metrics[model_id] = metrics

    def get_performance_metrics(self, model_id: str) -> MonitoringMetrics | None:
        """Get performance metrics for a model."""
        return self.performance_metrics.get(model_id)

    def get_all_performance_metrics(self) -> dict[str, MonitoringMetrics]:
        """Get performance metrics for all models."""
        return self.performance_metrics.copy()

    def calculate_drift_metrics(self, model_id: str) -> dict[str, float]:
        """Calculate drift metrics for a model."""
        predictions = self.predictions_buffer[model_id]
        if len(predictions) < 100:
            return {}

        # Get recent and older predictions for comparison
        mid_point = len(predictions) // 2
        recent_predictions = predictions[mid_point:]
        older_predictions = predictions[:mid_point]

        if len(recent_predictions) < 50 or len(older_predictions) < 50:
            return {}

        # Calculate prediction distribution drift
        recent_preds = [p["prediction"] for p in recent_predictions]
        older_preds = [p["prediction"] for p in older_predictions]

        try:
            from scipy import stats

            ks_statistic, p_value = stats.ks_2samp(recent_preds, older_preds)

            return {
                "prediction_drift_ks": ks_statistic,
                "prediction_drift_p_value": p_value,
                "prediction_drift_detected": p_value < 0.05,
            }
        except ImportError:
            self.logger.warning("scipy not available for drift calculation")
            return {}
        except Exception as e:
            self.logger.error(f"Drift calculation failed: {e}")
            return {}


class ProductionMonitor:
    """Comprehensive production monitoring for ML deployments."""

    def __init__(
        self,
        model_registry: MLModelRegistry | None = None,
        inference_engine: InferenceEngine | None = None,
        metrics_port: int = 8001,
        enable_prometheus: bool = True,
    ):
        self.model_registry = model_registry or MLModelRegistry()
        self.inference_engine = inference_engine
        self.logger = logging.getLogger(__name__)

        # Initialize components
        self.metrics_collector = MetricsCollector()
        self.performance_monitor = PerformanceMonitor(model_registry, inference_engine)
        self.alert_configs = self._create_default_alert_configs()
        self.alert_manager = AlertManager(self.alert_configs)

        # Prometheus metrics
        self.enable_prometheus = enable_prometheus
        if enable_prometheus:
            self.registry = CollectorRegistry()
            self._setup_prometheus_metrics()
            start_http_server(metrics_port, registry=self.registry)

        # Monitoring state
        self._monitoring_active = False
        self._monitoring_thread = None

    def _create_default_alert_configs(self) -> list[AlertConfig]:
        """Create default alert configurations."""
        return [
            AlertConfig(
                metric_name="error_rate",
                threshold=0.05,  # 5% error rate
                operator="gt",
                duration_minutes=5,
                severity="warning",
            ),
            AlertConfig(
                metric_name="avg_latency_ms",
                threshold=1000,  # 1 second
                operator="gt",
                duration_minutes=2,
                severity="warning",
            ),
            AlertConfig(
                metric_name="cpu_usage_percent",
                threshold=80,  # 80% CPU
                operator="gt",
                duration_minutes=10,
                severity="critical",
            ),
            AlertConfig(
                metric_name="memory_usage_mb",
                threshold=8000,  # 8GB
                operator="gt",
                duration_minutes=5,
                severity="warning",
            ),
            AlertConfig(
                metric_name="prediction_accuracy",
                threshold=0.7,  # 70% accuracy
                operator="lt",
                duration_minutes=15,
                severity="warning",
            ),
        ]

    def _setup_prometheus_metrics(self):
        """Setup Prometheus metrics."""
        self.prom_requests_total = Counter(
            "ml_inference_requests_total",
            "Total number of inference requests",
            ["model_id", "status"],
            registry=self.registry,
        )

        self.prom_latency_seconds = Histogram(
            "ml_inference_latency_seconds",
            "Inference latency in seconds",
            ["model_id"],
            registry=self.registry,
        )

        self.prom_active_models = Gauge(
            "ml_active_models", "Number of active models", registry=self.registry
        )

        self.prom_model_accuracy = Gauge(
            "ml_model_accuracy",
            "Model accuracy score",
            ["model_id"],
            registry=self.registry,
        )

    def start_monitoring(self):
        """Start production monitoring."""
        if self._monitoring_active:
            return

        self.logger.info("Starting production monitoring")

        # Start metrics collection
        self.metrics_collector.start_collection()

        # Add alert callback
        self.alert_manager.add_alert_callback(self._handle_alert)

        # Start monitoring thread
        self._monitoring_active = True
        self._monitoring_thread = threading.Thread(
            target=self._monitoring_loop, daemon=True
        )
        self._monitoring_thread.start()

        self.logger.info("Production monitoring started")

    def stop_monitoring(self):
        """Stop production monitoring."""
        if not self._monitoring_active:
            return

        self.logger.info("Stopping production monitoring")

        self._monitoring_active = False
        if self._monitoring_thread:
            self._monitoring_thread.join()

        self.metrics_collector.stop_collection()
        self.logger.info("Production monitoring stopped")

    def _monitoring_loop(self):
        """Main monitoring loop."""
        while self._monitoring_active:
            try:
                # Collect latest metrics
                system_metrics = self.metrics_collector.get_latest_metrics()

                # Add inference engine metrics if available
                if self.inference_engine:
                    inference_metrics = self.inference_engine.get_metrics()
                    system_metrics.update(inference_metrics)

                # Check alerts
                self.alert_manager.check_alerts(system_metrics)

                # Update Prometheus metrics
                if self.enable_prometheus:
                    self._update_prometheus_metrics()

                # Sleep until next monitoring cycle
                time.sleep(30)

            except Exception as e:
                self.logger.error(f"Monitoring loop error: {e}")

    def _update_prometheus_metrics(self):
        """Update Prometheus metrics."""
        try:
            # Update active models count
            active_models = len(self.performance_monitor.get_all_performance_metrics())
            self.prom_active_models.set(active_models)

            # Update model-specific metrics
            for (
                model_id,
                metrics,
            ) in self.performance_monitor.get_all_performance_metrics().items():
                if metrics.prediction_accuracy is not None:
                    self.prom_model_accuracy.labels(model_id=model_id).set(
                        metrics.prediction_accuracy
                    )

        except Exception as e:
            self.logger.error(f"Prometheus metrics update failed: {e}")

    def _handle_alert(self, metric_name: str, alert_data: dict[str, Any]):
        """Handle alert notifications."""
        self.logger.warning(f"ALERT: {alert_data['message']}")

        # Here you could add additional alert handling:
        # - Send to Slack/Teams
        # - Send email
        # - Create incident in monitoring system
        # - Trigger automated rollback

    def record_inference(
        self,
        model_id: str,
        deployment_id: str,
        prediction: float,
        confidence: float | None,
        features: dict[str, float],
        actual: float | None = None,
        latency_ms: float = 0.0,
    ):
        """Record inference for monitoring."""
        # Update performance monitor
        self.performance_monitor.record_prediction(
            model_id=model_id,
            deployment_id=deployment_id,
            prediction=prediction,
            confidence=confidence,
            features=features,
            actual=actual,
            latency_ms=latency_ms,
        )

        # Update Prometheus metrics
        if self.enable_prometheus:
            self.prom_requests_total.labels(model_id=model_id, status="success").inc()
            self.prom_latency_seconds.labels(model_id=model_id).observe(
                latency_ms / 1000.0
            )

    def get_monitoring_dashboard_data(self) -> dict[str, Any]:
        """Get data for monitoring dashboard."""
        return {
            "system_metrics": self.metrics_collector.get_latest_metrics(),
            "performance_metrics": {
                model_id: asdict(metrics)
                for model_id, metrics in self.performance_monitor.get_all_performance_metrics().items()
            },
            "active_alerts": len(
                [s for s in self.alert_manager._alert_states.values() if s["breached"]]
            ),
            "uptime": time.time() if self._monitoring_active else 0,
        }
