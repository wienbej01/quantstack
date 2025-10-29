"""Production ML model server for real-time intraday inference."""

import asyncio
import logging
import queue
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd

try:
    import uvicorn
    from fastapi import BackgroundTasks, FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    FastAPI = None
    HTTPException = None
    BackgroundTasks = None
    CORSMiddleware = None
    uvicorn = None

from pydantic import BaseModel, Field

from extensions.intraday_ml_features.pipeline import FeaturePipeline
from extensions.intraday_ml_models.predictors import MLPredictor
from extensions.intraday_ml_models.registry import MLModelRegistry


@dataclass
class PredictionRequest:
    """Request for model prediction."""

    features: Dict[str, float]
    model_id: str
    request_id: Optional[str] = None
    timestamp: Optional[datetime] = None


@dataclass
class PredictionResponse:
    """Response from model prediction."""

    prediction: float
    confidence: Optional[float]
    model_id: str
    request_id: str
    timestamp: datetime
    latency_ms: float
    metadata: Dict[str, Any]


class PredictionMetrics:
    """Track prediction performance metrics."""

    def __init__(self):
        self.total_predictions = 0
        self.total_latency_ms = 0.0
        self.error_count = 0
        self.last_prediction_time = None
        self.predictions_per_minute = 0.0
        self.avg_latency_ms = 0.0
        self.error_rate = 0.0
        self._recent_predictions = []
        self._lock = threading.Lock()

    def record_prediction(self, latency_ms: float, success: bool = True):
        """Record a prediction attempt."""
        with self._lock:
            self.total_predictions += 1
            self.total_latency_ms += latency_ms
            self.last_prediction_time = datetime.now()

            if not success:
                self.error_count += 1

            # Track recent predictions for rate calculation
            now = datetime.now()
            self._recent_predictions.append((now, latency_ms))

            # Keep only last minute of predictions
            self._recent_predictions = [
                (t, l)
                for t, l in self._recent_predictions
                if now - t < timedelta(minutes=1)
            ]

            self._update_metrics()

    def _update_metrics(self):
        """Update calculated metrics."""
        if self.total_predictions > 0:
            self.avg_latency_ms = self.total_latency_ms / self.total_predictions
            self.error_rate = self.error_count / self.total_predictions
            self.predictions_per_minute = len(self._recent_predictions)

    def get_metrics(self) -> Dict[str, float]:
        """Get current metrics."""
        with self._lock:
            return {
                "total_predictions": self.total_predictions,
                "avg_latency_ms": self.avg_latency_ms,
                "error_rate": self.error_rate,
                "predictions_per_minute": self.predictions_per_minute,
                "last_prediction_time": (
                    self.last_prediction_time.isoformat()
                    if self.last_prediction_time
                    else None
                ),
            }


class ModelCache:
    """Cache loaded models for fast inference."""

    def __init__(self, max_size: int = 10, ttl_seconds: int = 3600):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._access_times: Dict[str, datetime] = {}
        self._lock = threading.Lock()

    def get(self, model_id: str) -> Optional[Dict[str, Any]]:
        """Get cached model."""
        with self._lock:
            if model_id not in self._cache:
                return None

            cache_entry = self._cache[model_id]
            now = datetime.now()

            # Check TTL
            if now - cache_entry["loaded_at"] > timedelta(seconds=self.ttl_seconds):
                del self._cache[model_id]
                if model_id in self._access_times:
                    del self._access_times[model_id]
                return None

            # Update access time
            self._access_times[model_id] = now
            return cache_entry["model"]

    def put(self, model_id: str, model: Dict[str, Any]):
        """Put model in cache."""
        with self._lock:
            # Evict if cache is full
            if len(self._cache) >= self.max_size:
                self._evict_lru()

            self._cache[model_id] = {"model": model, "loaded_at": datetime.now()}
            self._access_times[model_id] = datetime.now()

    def _evict_lru(self):
        """Evict least recently used model."""
        if not self._access_times:
            return

        lru_model_id = min(
            self._access_times.keys(), key=lambda k: self._access_times[k]
        )
        del self._cache[lru_model_id]
        del self._access_times[lru_model_id]


class ModelServer:
    """Production model server for real-time inference."""

    def __init__(
        self,
        registry: Optional[MLModelRegistry] = None,
        cache_size: int = 10,
        cache_ttl_seconds: int = 3600,
        max_concurrent_predictions: int = 100,
    ):
        """
        Initialize model server.

        Args:
            registry: Model registry instance
            cache_size: Maximum models to cache
            cache_ttl_seconds: Cache TTL in seconds
            max_concurrent_predictions: Maximum concurrent predictions
        """
        self.registry = registry or MLModelRegistry()
        self.model_cache = ModelCache(cache_size, cache_ttl_seconds)
        self.metrics = PredictionMetrics()
        self.max_concurrent_predictions = max_concurrent_predictions

        # Semaphore for concurrent prediction limiting
        self.prediction_semaphore = threading.Semaphore(max_concurrent_predictions)

        # Thread-safe request queue for async processing
        self.request_queue = queue.Queue(maxsize=max_concurrent_predictions * 2)

        # Initialize FastAPI app if available
        if FASTAPI_AVAILABLE:
            self.app = FastAPI(
                title="Intraday ML Model Server",
                description="Production ML serving for intraday trading",
                version="1.0.0",
            )

            # Add CORS middleware
            self.app.add_middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            )

            # Setup routes
            self._setup_routes()
        else:
            self.app = None

        # Setup logging
        self.logger = logging.getLogger(__name__)

    def _setup_routes(self):
        """Setup FastAPI routes."""
        if not FASTAPI_AVAILABLE:
            return

        @self.app.post("/predict")
        async def predict(request: PredictionRequest) -> PredictionResponse:
            """Make prediction with specified model."""
            return await self._predict_async(request)

        @self.app.get("/models")
        async def list_models() -> Dict[str, Any]:
            """List available models."""
            return {"models": self.registry.list_models()}

        @self.app.get("/models/{model_id}/info")
        async def get_model_info(model_id: str) -> Dict[str, Any]:
            """Get model information."""
            try:
                metadata = self.registry.get_metadata(model_id)
                return asdict(metadata)
            except Exception as e:
                raise HTTPException(
                    status_code=404, detail=f"Model {model_id} not found"
                )

        @self.app.get("/metrics")
        async def get_metrics() -> Dict[str, float]:
            """Get server metrics."""
            return self.metrics.get_metrics()

        @self.app.post("/models/{model_id}/reload")
        async def reload_model(
            model_id: str, background_tasks: BackgroundTasks
        ) -> Dict[str, str]:
            """Reload model in background."""
            background_tasks.add_task(self._reload_model_background, model_id)
            return {"message": f"Model {model_id} reload started"}

        @self.app.get("/health")
        async def health_check() -> Dict[str, str]:
            """Health check endpoint."""
            return {"status": "healthy", "timestamp": datetime.now().isoformat()}

    async def _predict_async(self, request: PredictionRequest) -> PredictionResponse:
        """Handle async prediction request."""
        start_time = time.time()
        request_id = request.request_id or f"{int(time.time() * 1000)}"
        timestamp = request.timestamp or datetime.now()

        try:
            # Acquire semaphore for concurrency control
            with self.prediction_semaphore:
                # Load model (from cache or registry)
                model = self._load_model(request.model_id)
                if model is None:
                    raise HTTPException(
                        status_code=404, detail=f"Model {request.model_id} not found"
                    )

                # Make prediction
                prediction, confidence = await self._make_prediction(
                    model, request.features, request.model_id
                )

                # Calculate latency
                latency_ms = (time.time() - start_time) * 1000

                # Record metrics
                self.metrics.record_prediction(latency_ms, success=True)

                return PredictionResponse(
                    prediction=prediction,
                    confidence=confidence,
                    model_id=request.model_id,
                    request_id=request_id,
                    timestamp=timestamp,
                    latency_ms=latency_ms,
                    metadata={
                        "server_timestamp": datetime.now().isoformat(),
                        "model_version": model.get("metadata", {}).get(
                            "version", "unknown"
                        ),
                    },
                )

        except Exception as e:
            # Record error metrics
            latency_ms = (time.time() - start_time) * 1000
            self.metrics.record_prediction(latency_ms, success=False)

            self.logger.error(f"Prediction failed for model {request.model_id}: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    def _load_model(self, model_id: str) -> Optional[Dict[str, Any]]:
        """Load model from cache or registry."""
        # Try cache first
        model = self.model_cache.get(model_id)
        if model is not None:
            return model

        # Load from registry
        try:
            metadata = self.registry.get_metadata(model_id)
            predictor = MLPredictor(model_id, self.registry)

            model = {
                "predictor": predictor,
                "metadata": metadata,
                "loaded_at": datetime.now(),
            }

            # Cache the model
            self.model_cache.put(model_id, model)
            return model

        except Exception as e:
            self.logger.error(f"Failed to load model {model_id}: {e}")
            return None

    async def _make_prediction(
        self, model: Dict[str, Any], features: Dict[str, float], model_id: str
    ) -> tuple[float, Optional[float]]:
        """Make prediction with loaded model."""
        predictor = model["predictor"]
        metadata = model["metadata"]

        # Convert features to DataFrame
        feature_df = pd.DataFrame([features])

        # Ensure all required features are present
        required_features = metadata.features
        missing_features = set(required_features) - set(features.keys())
        if missing_features:
            raise ValueError(f"Missing required features: {missing_features}")

        # Make prediction
        try:
            result = predictor.predict(feature_df)

            if result.prediction_probability is not None:
                return result.prediction, result.prediction_probability
            else:
                return result.prediction, None

        except Exception as e:
            raise RuntimeError(f"Prediction failed: {e}")

    async def _reload_model_background(self, model_id: str):
        """Reload model in background."""
        try:
            # Remove from cache to force reload
            self.model_cache._cache.pop(model_id, None)
            self.model_cache._access_times.pop(model_id, None)

            # Preload model
            self._load_model(model_id)

            self.logger.info(f"Successfully reloaded model {model_id}")

        except Exception as e:
            self.logger.error(f"Failed to reload model {model_id}: {e}")

    def run(self, host: str = "0.0.0.0", port: int = 8000, log_level: str = "info"):
        """Run the model server."""
        uvicorn.run(self.app, host=host, port=port, log_level=log_level)

    def get_status(self) -> Dict[str, Any]:
        """Get server status."""
        return {
            "cache_size": len(self.model_cache._cache),
            "metrics": self.metrics.get_metrics(),
            "available_models": len(self.registry.list_models()),
            "max_concurrent_predictions": self.max_concurrent_predictions,
        }
