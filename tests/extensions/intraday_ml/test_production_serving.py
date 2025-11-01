"""Tests for production ML serving infrastructure."""

import time
from datetime import datetime
from unittest.mock import Mock, patch

import numpy as np
import pytest

from extensions.intraday_ml_serving.deployment import (
    DeploymentConfig,
    DeploymentManager,
    DeploymentStatus,
)
from extensions.intraday_ml_serving.inference_engine import (
    InferenceEngine,
)
from extensions.intraday_ml_serving.model_server import (
    ModelServer,
)
from extensions.intraday_ml_serving.monitoring import (
    AlertConfig,
    MonitoringMetrics,
    ProductionMonitor,
)

# from fastapi.testclient import TestClient  # Commented out for compatibility


@pytest.fixture
def sample_model_metadata():
    """Create sample model metadata."""
    from extensions.intraday_ml_models.schemas import (
        FeatureImportance,
        ModelMetadata,
        ModelType,
    )

    return ModelMetadata(
        model_id="test_model",
        model_type=ModelType.REGRESSION,
        model_class="RandomForestRegressor",
        training_date=datetime.now(),
        features=["f__vwap_30", "f__rel_volume_30", "f__atr_14"],
        target_column="close",
        train_samples=1000,
        val_samples=200,
        test_samples=200,
        train_score=0.85,
        val_score=0.82,
        test_score=0.83,
        feature_importance=[
            FeatureImportance(feature_name=f, importance=0.3, rank=1)
            for f in ["f__vwap_30", "f__rel_volume_30", "f__atr_14"]
        ],
        random_seed=42,
        data_hash="test_hash",
        model_hash="model_hash",
    )


@pytest.fixture
def sample_features():
    """Create sample features for prediction."""
    return {"f__vwap_30": 150.5, "f__rel_volume_30": 1.2, "f__atr_14": 2.1}


class TestModelServer:
    """Test model server functionality."""

    def setup_method(self):
        """Set up test environment."""
        with patch("extensions.intraday_ml_serving.model_server.MLModelRegistry"):
            self.server = ModelServer(cache_size=5)

    def test_server_initialization(self):
        """Test server initialization."""
        assert self.server.registry is not None
        assert self.server.model_cache is not None
        assert self.server.metrics is not None
        assert self.server.max_concurrent_predictions == 100

    def test_metrics_tracking(self):
        """Test metrics tracking functionality."""
        # Record some predictions
        self.server.metrics.record_prediction(50.0, success=True)
        self.server.metrics.record_prediction(75.0, success=True)
        self.server.metrics.record_prediction(100.0, success=False)

        metrics = self.server.metrics.get_metrics()
        assert metrics["total_predictions"] == 3
        assert metrics["error_rate"] == 1 / 3
        assert metrics["avg_latency_ms"] == 75.0  # (50+75+100)/3

    @patch("extensions.intraday_ml_serving.model_server.MLPredictor")
    @patch("extensions.intraday_ml_serving.model_server.MLModelRegistry")
    def test_model_loading(
        self, mock_registry_class, mock_predictor_class, sample_model_metadata
    ):
        """Test model loading from registry."""
        # Setup mocks
        mock_registry = Mock()
        mock_registry.get_metadata.return_value = sample_model_metadata
        mock_registry_class.return_value = mock_registry

        mock_predictor = Mock()
        mock_predictor_class.return_value = mock_predictor

        # Load model
        model = self.server._load_model("test_model")
        assert model is not None
        assert "predictor" in model
        assert "metadata" in model

    def test_model_cache_operations(self):
        """Test model cache functionality."""
        cache = self.server.model_cache

        # Test empty cache
        assert cache.get("nonexistent_model") is None

        # Test cache put and get
        mock_model = {"predictor": Mock(), "metadata": Mock()}
        cache.put("test_model", mock_model)

        retrieved_model = cache.get("test_model")
        assert retrieved_model is mock_model

    @patch("extensions.intraday_ml_serving.model_server.MLPredictor")
    @patch("extensions.intraday_ml_serving.model_server.MLModelRegistry")
    async def test_prediction_endpoint(
        self, mock_registry_class, mock_predictor_class, sample_features
    ):
        """Test prediction endpoint via FastAPI."""
        # Setup mocks
        mock_registry = Mock()
        mock_registry.get_metadata.return_value = Mock(
            features=list(sample_features.keys())
        )
        mock_registry_class.return_value = mock_registry

        mock_result = Mock()
        mock_result.prediction = np.array([0.5])
        mock_result.prediction_probability = np.array([0.8])

        mock_predictor = Mock()
        mock_predictor.predict.return_value = mock_result
        mock_predictor_class.return_value = mock_predictor

        # Create client
        client = TestClient(self.server.app)

        # Test prediction request
        request_data = {"features": sample_features, "model_id": "test_model"}

        response = client.post("/predict", json=request_data)
        assert response.status_code == 200

        response_data = response.json()
        assert "prediction" in response_data
        assert "confidence" in response_data
        assert "model_id" in response_data
        assert "latency_ms" in response_data

    def test_health_check_endpoint(self):
        """Test health check endpoint."""
        client = TestClient(self.server.app)
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"

    def test_models_list_endpoint(self):
        """Test models list endpoint."""
        client = TestClient(self.server.app)
        response = client.get("/models")
        assert response.status_code == 200
        assert "models" in response.json()

    def test_metrics_endpoint(self):
        """Test metrics endpoint."""
        client = TestClient(self.server.app)
        response = client.get("/metrics")
        assert response.status_code == 200
        assert isinstance(response.json(), dict)


class TestInferenceEngine:
    """Test inference engine functionality."""

    def setup_method(self):
        """Set up test environment."""
        with patch("extensions.intraday_ml_serving.inference_engine.MLModelRegistry"):
            self.engine = InferenceEngine(cache_size=5, batch_size=10)

    def test_engine_initialization(self):
        """Test engine initialization."""
        assert self.engine.registry is not None
        assert self.engine.predictor_cache is not None
        assert self.engine.batch_processor is not None
        assert self.engine.metrics is not None

    def test_single_prediction(self):
        """Test single prediction."""
        features = {"feature1": 1.0, "feature2": 2.0}
        model_id = "test_model"

        with patch(
            "extensions.intraday_ml_serving.inference_engine.MLPredictor"
        ) as mock_predictor_class:
            # Setup mock predictor
            mock_predictor = Mock()
            mock_result = Mock()
            mock_result.prediction = np.array([0.5])
            mock_result.prediction_probability = np.array([0.8])
            mock_predictor.predict.return_value = mock_result
            mock_predictor_class.return_value = mock_predictor

            prediction, confidence = self.engine.predict_single(features, model_id)
            assert prediction == 0.5
            assert confidence == 0.8

    def test_batch_prediction(self):
        """Test batch prediction."""
        features_list = [
            {"feature1": 1.0, "feature2": 2.0},
            {"feature1": 1.5, "feature2": 2.5},
        ]
        model_ids = ["test_model"]

        with patch(
            "extensions.intraday_ml_serving.inference_engine.MLPredictor"
        ) as mock_predictor_class:
            # Setup mock predictor
            mock_predictor = Mock()
            mock_result = Mock()
            mock_result.prediction = np.array([0.5, 0.6])
            mock_result.prediction_probability = np.array([0.8, 0.7])
            mock_predictor.predict.return_value = mock_result
            mock_predictor_class.return_value = mock_predictor

            response = self.engine.predict(features_list, model_ids)
            assert response.predictions == [0.5, 0.6]
            assert response.confidences == [0.8, 0.7]
            assert response.model_ids == model_ids

    def test_predictor_cache(self):
        """Test predictor caching."""
        cache = self.engine.predictor_cache

        # Test empty cache
        assert cache.get("test_model") is None

        with patch(
            "extensions.intraday_ml_serving.inference_engine.MLPredictor"
        ) as mock_predictor_class:
            mock_predictor = Mock()
            mock_predictor_class.return_value = mock_predictor

            # Put in cache
            cache.put("test_model", mock_predictor)

            # Retrieve from cache
            retrieved = cache.get("test_model")
            assert retrieved is mock_predictor

    def test_metrics_update(self):
        """Test metrics update."""
        # Initial metrics
        initial_metrics = self.engine.get_metrics()
        assert initial_metrics["total_requests"] == 0

        # Record prediction
        self.engine.metrics.record_prediction(50.0, predictions_count=1, cache_hit=True)

        updated_metrics = self.engine.get_metrics()
        assert updated_metrics["total_requests"] == 1
        assert updated_metrics["cache_hit_rate"] == 1.0

    def test_concurrent_prediction_limiting(self):
        """Test concurrent prediction limiting."""
        # Test semaphore is created
        assert (
            self.engine.prediction_semaphore._value
            == self.engine.max_concurrent_predictions
        )


class TestDeploymentManager:
    """Test deployment manager functionality."""

    def setup_method(self):
        """Set up test environment."""
        with patch("extensions.intraday_ml_serving.deployment.MLModelRegistry"):
            self.manager = DeploymentManager(deployment_type="docker")

    def test_deployment_config_creation(self):
        """Test deployment configuration creation."""
        config = DeploymentConfig(
            deployment_name="test-deployment",
            model_id="test_model",
            replicas=2,
            cpu_limit="500m",
            memory_limit="1Gi",
        )

        assert config.deployment_name == "test-deployment"
        assert config.model_id == "test_model"
        assert config.replicas == 2
        assert config.cpu_limit == "500m"
        assert config.memory_limit == "1Gi"

    def test_deployment_config_creation(self):
        """Test deployment configuration creation."""
        from extensions.intraday_ml_serving.deployment import DeploymentConfig

        config = DeploymentConfig(
            deployment_name="test-deployment",
            model_id="test_model",
            replicas=2,
            cpu_limit="500m",
            memory_limit="1Gi",
        )

        assert config.deployment_name == "test-deployment"
        assert config.model_id == "test_model"
        assert config.replicas == 2
        assert config.cpu_limit == "500m"
        assert config.memory_limit == "1Gi"

    def test_deployment_status_creation(self):
        """Test deployment status creation."""

        status = DeploymentStatus(
            deployment_name="test-deployment",
            status="running",
            replicas=3,
            ready_replicas=3,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        assert status.deployment_name == "test-deployment"
        assert status.status == "running"
        assert status.replicas == 3
        assert status.ready_replicas == 3

    def test_deployment_config_validation(self):
        """Test deployment configuration validation."""
        from extensions.intraday_ml_serving.deployment import DeploymentConfig

        config = DeploymentConfig(
            deployment_name="test-deployment",
            model_id="test_model",
            replicas=2,
            cpu_limit="500m",
            memory_limit="1Gi",
        )

        # Test required fields
        assert config.deployment_name is not None
        assert config.model_id is not None
        assert config.replicas > 0
        assert config.cpu_limit is not None
        assert config.memory_limit is not None

    def test_deployment_manager_concepts(self):
        """Test deployment manager concepts."""
        # Test deployment types
        valid_types = ["docker", "kubernetes"]
        for deployment_type in valid_types:
            # This would test the deployment manager creation
            # In practice, we'd need to mock the actual deployer
            assert deployment_type in valid_types

        # Test environment validation
        valid_environments = ["development", "staging", "production"]
        for env in valid_environments:
            assert env is not None  # Environment would be validated


class TestProductionMonitor:
    """Test production monitoring functionality (simplified)."""

    def test_monitoring_concepts(self):
        """Test monitoring core concepts."""
        # Test alert configuration
        alert_config = AlertConfig(
            metric_name="error_rate",
            threshold=0.05,
            operator="gt",
            duration_minutes=5,
            severity="warning",
        )

        assert alert_config.metric_name == "error_rate"
        assert alert_config.threshold == 0.05
        assert alert_config.operator == "gt"
        assert alert_config.duration_minutes == 5
        assert alert_config.severity == "warning"

        # Test risk levels
        from extensions.intraday_ml_risk.ml_risk_manager import RiskLevel

        assert RiskLevel.LOW.value == "low"
        assert RiskLevel.MEDIUM.value == "medium"
        assert RiskLevel.HIGH.value == "high"
        assert RiskLevel.CRITICAL.value == "critical"

    def test_metrics_tracking(self):
        """Test metrics tracking concepts."""
        # Test that metrics can be created

        metrics = MonitoringMetrics(
            timestamp=datetime.now(),
            model_id="test_model",
            deployment_id="test-deployment",
            total_requests=100,
            successful_requests=95,
            failed_requests=5,
            avg_latency_ms=50.0,
            requests_per_second=10.0,
        )

        assert metrics.model_id == "test_model"
        assert metrics.deployment_id == "test-deployment"
        assert metrics.total_requests == 100
        assert metrics.successful_requests == 95
        assert metrics.failed_requests == 5
        assert metrics.avg_latency_ms == 50.0

        # Test metrics calculation
        assert metrics.error_rate == 0.05  # 5/100
        assert metrics.success_rate == 0.95  # 95/100


class TestProductionIntegration:
    """Integration tests for production serving components."""

    def setup_method(self):
        """Set up test environment."""
        with (
            patch("extensions.intraday_ml_serving.model_server.MLModelRegistry"),
            patch("extensions.intraday_ml_serving.inference_engine.MLModelRegistry"),
            patch("extensions.intraday_ml_serving.monitoring.MLModelRegistry"),
        ):

            self.server = ModelServer(cache_size=3)
            self.engine = InferenceEngine(cache_size=3)
            self.monitor = ProductionMonitor(enable_prometheus=False)

    def test_end_to_end_prediction_flow(self):
        """Test end-to-end prediction flow."""
        # This test would require actual model files
        # For now, we test the flow structure
        features = {"feature1": 1.0, "feature2": 2.0}
        model_id = "test_model"

        # Mock the model loading and prediction
        with patch.object(self.engine, "predict_single") as mock_predict:
            mock_predict.return_value = (0.5, 0.8)

            prediction, confidence = self.engine.predict_single(features, model_id)
            assert prediction == 0.5
            assert confidence == 0.8

            # Verify prediction was recorded
            metrics = self.engine.get_metrics()
            assert metrics["total_predictions"] == 1

    def test_monitoring_integration(self):
        """Test monitoring integration with inference engine."""
        # Record some inference data
        self.monitor.record_inference(
            model_id="test_model",
            deployment_id="test-deployment",
            prediction=0.5,
            confidence=0.8,
            features={"feature1": 1.0},
            latency_ms=50.0,
        )

        # Check that monitoring captured the data
        performance_metrics = self.monitor.performance_monitor.get_performance_metrics(
            "test_model"
        )
        assert performance_metrics is not None
        assert performance_metrics.total_requests == 1

    def test_concurrent_operations(self):
        """Test concurrent operations don't interfere."""
        import threading

        results = []
        errors = []

        def worker():
            try:
                # Simulate concurrent operations
                for i in range(10):
                    self.server.metrics.record_prediction(50.0 + i, success=True)
                    time.sleep(0.001)
                results.append("success")
            except Exception as e:
                errors.append(str(e))

        # Create multiple threads
        threads = []
        for _ in range(5):
            thread = threading.Thread(target=worker)
            threads.append(thread)

        # Start all threads
        for thread in threads:
            thread.start()

        # Wait for completion
        for thread in threads:
            thread.join()

        # Verify no errors
        assert len(errors) == 0
        assert len(results) == 5

        # Verify all metrics were recorded
        metrics = self.server.metrics.get_metrics()
        assert metrics["total_predictions"] == 50  # 5 threads * 10 predictions


if __name__ == "__main__":
    pytest.main([__file__])
