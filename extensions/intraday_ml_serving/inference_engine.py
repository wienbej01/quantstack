"""High-performance inference engine for real-time ML predictions."""

import asyncio
import logging
import time
from typing import Dict, Any, List, Optional, Callable, Union
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock, Event, Semaphore
import queue
import multiprocessing as mp

import pandas as pd
import numpy as np
try:
    from numba import jit, prange
    NUMBA_AVAILABLE = True
except ImportError:
    NUMBA_AVAILABLE = False
    def jit(func=None, *args, **kwargs):
        if func is None:
            return lambda f: f
        return func
    def prange(range_obj):
        return range(range_obj)

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    psutil = None

from extensions.intraday_ml_models.predictors import MLPredictor
from extensions.intraday_ml_models.registry import MLModelRegistry
from extensions.intraday_ml_features.pipeline import FeaturePipeline


@dataclass
class InferenceRequest:
    """Request for batch inference."""
    features: List[Dict[str, float]]
    model_ids: List[str]
    request_id: str
    timestamp: datetime = field(default_factory=datetime.now)
    priority: int = 0  # Higher priority = processed first


@dataclass
class InferenceResponse:
    """Response from batch inference."""
    predictions: List[float]
    confidences: List[Optional[float]]
    model_ids: List[str]
    request_id: str
    timestamp: datetime
    processing_time_ms: float
    throughput_per_second: float


@dataclass
class InferenceMetrics:
    """Inference engine performance metrics."""
    total_requests: int = 0
    total_predictions: int = 0
    avg_processing_time_ms: float = 0.0
    throughput_per_second: float = 0.0
    cpu_usage_percent: float = 0.0
    memory_usage_mb: float = 0.0
    cache_hit_rate: float = 0.0
    error_rate: float = 0.0
    last_request_time: Optional[datetime] = None

    def update(self, processing_time_ms: float, predictions_count: int, cache_hit: bool, error: bool = False):
        """Update metrics with new request."""
        self.total_requests += 1
        self.total_predictions += predictions_count
        self.last_request_time = datetime.now()

        # Update processing time (running average)
        if self.total_requests == 1:
            self.avg_processing_time_ms = processing_time_ms
        else:
            alpha = 0.1  # Smoothing factor
            self.avg_processing_time_ms = (
                alpha * processing_time_ms +
                (1 - alpha) * self.avg_processing_time_ms
            )

        # Update cache hit rate
        if cache_hit:
            if self.total_requests == 1:
                self.cache_hit_rate = 1.0
            else:
                alpha = 0.1
                self.cache_hit_rate = (
                    alpha * 1.0 +
                    (1 - alpha) * self.cache_hit_rate
                )
        else:
            if self.total_requests == 1:
                self.cache_hit_rate = 0.0
            else:
                alpha = 0.1
                self.cache_hit_rate = (
                    alpha * 0.0 +
                    (1 - alpha) * self.cache_hit_rate
                )

        # Update error rate
        if error:
            if self.total_requests == 1:
                self.error_rate = 1.0
            else:
                alpha = 0.1
                self.error_rate = (
                    alpha * 1.0 +
                    (1 - alpha) * self.error_rate
                )
        else:
            if self.total_requests == 1:
                self.error_rate = 0.0
            else:
                alpha = 0.1
                self.error_rate = (
                    alpha * 0.0 +
                    (1 - alpha) * self.error_rate
                )

        # Update system metrics
        if PSUTIL_AVAILABLE:
            self.cpu_usage_percent = psutil.cpu_percent()
            self.memory_usage_mb = psutil.virtual_memory().used / (1024 * 1024)
        else:
            # Mock system metrics when psutil not available
            self.cpu_usage_percent = 50.0  # Mock 50% CPU usage
            self.memory_usage_mb = 512.0  # Mock 512MB memory usage

        # Calculate throughput
        if self.avg_processing_time_ms > 0:
            self.throughput_per_second = 1000.0 / self.avg_processing_time_ms

    def record_prediction(self, processing_time_ms: float, predictions_count: int = 1, cache_hit: bool = False):
        """Record a prediction for metrics tracking (alias for update)."""
        self.update(processing_time_ms, predictions_count, cache_hit, error=False)


class ModelPredictorCache:
    """High-performance cache for model predictors."""

    def __init__(self, max_size: int = 50, ttl_seconds: int = 1800):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._access_times: Dict[str, float] = {}
        self._lock = Lock()

    def get(self, model_id: str) -> Optional[MLPredictor]:
        """Get predictor from cache."""
        with self._lock:
            if model_id not in self._cache:
                return None

            cache_entry = self._cache[model_id]
            now = time.time()

            # Check TTL
            if now - cache_entry["timestamp"] > self.ttl_seconds:
                del self._cache[model_id]
                self._access_times.pop(model_id, None)
                return None

            # Update access time
            self._access_times[model_id] = now
            return cache_entry["predictor"]

    def put(self, model_id: str, predictor: MLPredictor):
        """Put predictor in cache."""
        with self._lock:
            # Evict if cache is full
            if len(self._cache) >= self.max_size:
                self._evict_lru()

            self._cache[model_id] = {
                "predictor": predictor,
                "timestamp": time.time()
            }
            self._access_times[model_id] = time.time()

    def _evict_lru(self):
        """Evict least recently used predictor."""
        if not self._access_times:
            return

        lru_model_id = min(self._access_times.keys(), key=lambda k: self._access_times[k])
        del self._cache[lru_model_id]
        del self._access_times[lru_model_id]


class BatchProcessor:
    """Process batch inference requests efficiently."""

    def __init__(self, max_workers: int = None, batch_size: int = 100):
        self.max_workers = max_workers or min(32, mp.cpu_count() + 4)
        self.batch_size = batch_size
        self.executor = ThreadPoolExecutor(max_workers=self.max_workers)

    def process_batch(
        self,
        requests: List[InferenceRequest],
        predictors: Dict[str, MLPredictor]
    ) -> List[InferenceResponse]:
        """Process multiple inference requests in parallel."""
        futures = []

        for request in requests:
            future = self.executor.submit(
                self._process_single_request,
                request,
                predictors
            )
            futures.append(future)

        responses = []
        for future in as_completed(futures):
            try:
                response = future.result()
                responses.append(response)
            except Exception as e:
                logging.error(f"Batch processing error: {e}")
                # Create error response
                responses.append(InferenceResponse(
                    predictions=[],
                    confidences=[],
                    model_ids=[],
                    request_id="error",
                    timestamp=datetime.now(),
                    processing_time_ms=0.0,
                    throughput_per_second=0.0
                ))

        return responses

    def _process_single_request(
        self,
        request: InferenceRequest,
        predictors: Dict[str, MLPredictor]
    ) -> InferenceResponse:
        """Process a single inference request."""
        start_time = time.time()

        predictions = []
        confidences = []

        try:
            # Convert features to DataFrame
            feature_df = pd.DataFrame(request.features)

            for model_id in request.model_ids:
                if model_id not in predictors:
                    raise ValueError(f"Predictor for model {model_id} not found")

                predictor = predictors[model_id]
                result = predictor.predict(feature_df)

                if len(result.prediction) > 0:
                    predictions.append(result.prediction[0])
                    confidences.append(result.prediction_probability[0] if result.prediction_probability else None)
                else:
                    predictions.append(0.0)
                    confidences.append(None)

            processing_time_ms = (time.time() - start_time) * 1000
            throughput_per_second = len(request.model_ids) / (processing_time_ms / 1000.0)

            return InferenceResponse(
                predictions=predictions,
                confidences=confidences,
                model_ids=request.model_ids,
                request_id=request.request_id,
                timestamp=request.timestamp,
                processing_time_ms=processing_time_ms,
                throughput_per_second=throughput_per_second
            )

        except Exception as e:
            processing_time_ms = (time.time() - start_time) * 1000
            logging.error(f"Request processing failed: {e}")

            return InferenceResponse(
                predictions=[0.0] * len(request.model_ids),
                confidences=[None] * len(request.model_ids),
                model_ids=request.model_ids,
                request_id=request.request_id,
                timestamp=request.timestamp,
                processing_time_ms=processing_time_ms,
                throughput_per_second=0.0
            )


class InferenceEngine:
    """High-performance inference engine for real-time ML predictions."""

    def __init__(
        self,
        registry: Optional[MLModelRegistry] = None,
        max_workers: int = None,
        cache_size: int = 50,
        cache_ttl_seconds: int = 1800,
        batch_size: int = 100,
        enable_async: bool = True
    ):
        """
        Initialize inference engine.

        Args:
            registry: Model registry instance
            max_workers: Maximum worker threads
            cache_size: Maximum predictors to cache
            cache_ttl_seconds: Cache TTL in seconds
            batch_size: Default batch size for processing
            enable_async: Enable async processing
        """
        self.registry = registry or MLModelRegistry()
        self.predictor_cache = ModelPredictorCache(cache_size, cache_ttl_seconds)
        self.batch_processor = BatchProcessor(max_workers, batch_size)
        self.enable_async = enable_async

        self.metrics = InferenceMetrics()
        self.logger = logging.getLogger(__name__)

        # Concurrency control
        self.max_concurrent_predictions = max_workers or min(32, mp.cpu_count() + 4)
        self.prediction_semaphore = Semaphore(self.max_concurrent_predictions)

        # Request queue for async processing
        if enable_async:
            self.request_queue = asyncio.Queue()
            self.response_queue = asyncio.Queue()
            self._processing_task = None
            self._stop_event = Event()

    async def start_async_processing(self):
        """Start async processing loop."""
        if not self.enable_async:
            return

        self._processing_task = asyncio.create_task(self._async_processing_loop())
        self.logger.info("Async inference processing started")

    async def stop_async_processing(self):
        """Stop async processing loop."""
        if not self.enable_async:
            return

        self._stop_event.set()
        if self._processing_task:
            await self._processing_task
        self.logger.info("Async inference processing stopped")

    async def _async_processing_loop(self):
        """Async processing loop for requests."""
        while not self._stop_event.is_set():
            try:
                # Wait for requests with timeout
                requests = []
                try:
                    # Get first request
                    request = await asyncio.wait_for(
                        self.request_queue.get(),
                        timeout=0.1
                    )
                    requests.append(request)

                    # Get additional requests for batching
                    for _ in range(self.batch_processor.batch_size - 1):
                        try:
                            additional_request = await asyncio.wait_for(
                                self.request_queue.get(),
                                timeout=0.01
                            )
                            requests.append(additional_request)
                        except asyncio.TimeoutError:
                            break

                except asyncio.TimeoutError:
                    continue

                if requests:
                    # Process batch
                    responses = await self._process_batch_async(requests)

                    # Put responses in queue
                    for response in responses:
                        await self.response_queue.put(response)

            except Exception as e:
                self.logger.error(f"Async processing error: {e}")

    async def predict_async(
        self,
        features: List[Dict[str, float]],
        model_ids: List[str],
        priority: int = 0
    ) -> InferenceResponse:
        """Make async prediction."""
        if not self.enable_async:
            raise RuntimeError("Async processing not enabled")

        request = InferenceRequest(
            features=features,
            model_ids=model_ids,
            request_id=f"async_{int(time.time() * 1000)}",
            priority=priority
        )

        await self.request_queue.put(request)

        # Wait for response
        response = await self.response_queue.get()
        return response

    def predict(
        self,
        features: List[Dict[str, float]],
        model_ids: List[str],
        batch_size: Optional[int] = None
    ) -> InferenceResponse:
        """Make synchronous prediction."""
        start_time = time.time()

        request = InferenceRequest(
            features=features,
            model_ids=model_ids,
            request_id=f"sync_{int(time.time() * 1000)}"
        )

        # Load predictors
        predictors = {}
        cache_hits = 0

        for model_id in model_ids:
            predictor = self.predictor_cache.get(model_id)
            if predictor is None:
                # Load from registry
                predictor = MLPredictor(model_id, self.registry)
                self.predictor_cache.put(model_id, predictor)
            else:
                cache_hits += 1

            predictors[model_id] = predictor

        # Process request
        if batch_size and len(model_ids) > batch_size:
            # Process in batches
            all_predictions = []
            all_confidences = []

            for i in range(0, len(model_ids), batch_size):
                batch_ids = model_ids[i:i + batch_size]
                batch_request = InferenceRequest(
                    features=features,
                    model_ids=batch_ids,
                    request_id=f"{request.request_id}_batch_{i // batch_size}"
                )

                batch_response = self.batch_processor.process_batch([batch_request], predictors)
                if batch_response:
                    batch_result = batch_response[0]
                    all_predictions.extend(batch_result.predictions)
                    all_confidences.extend(batch_result.confidences)

            processing_time_ms = (time.time() - start_time) * 1000
            throughput_per_second = len(model_ids) / (processing_time_ms / 1000.0)

            response = InferenceResponse(
                predictions=all_predictions,
                confidences=all_confidences,
                model_ids=model_ids,
                request_id=request.request_id,
                timestamp=request.timestamp,
                processing_time_ms=processing_time_ms,
                throughput_per_second=throughput_per_second
            )

        else:
            # Process single batch
            responses = self.batch_processor.process_batch([request], predictors)
            response = responses[0] if responses else InferenceResponse(
                predictions=[],
                confidences=[],
                model_ids=model_ids,
                request_id=request.request_id,
                timestamp=request.timestamp,
                processing_time_ms=0.0,
                throughput_per_second=0.0
            )

        # Update metrics
        cache_hit = cache_hits == len(model_ids)
        self.metrics.update(
            response.processing_time_ms,
            len(response.predictions),
            cache_hit
        )

        return response

    def predict_single(
        self,
        features: Dict[str, float],
        model_id: str
    ) -> tuple[float, Optional[float]]:
        """Make single prediction."""
        response = self.predict([features], [model_id])
        if response.predictions:
            return response.predictions[0], response.confidences[0]
        else:
            return 0.0, None

    def get_metrics(self) -> Dict[str, Any]:
        """Get inference engine metrics."""
        return {
            "total_requests": self.metrics.total_requests,
            "total_predictions": self.metrics.total_predictions,
            "avg_processing_time_ms": self.metrics.avg_processing_time_ms,
            "throughput_per_second": self.metrics.throughput_per_second,
            "cpu_usage_percent": self.metrics.cpu_usage_percent,
            "memory_usage_mb": self.metrics.memory_usage_mb,
            "cache_hit_rate": self.metrics.cache_hit_rate,
            "error_rate": self.metrics.error_rate,
            "cache_size": len(self.predictor_cache._cache),
            "max_workers": self.batch_processor.max_workers,
            "batch_size": self.batch_processor.batch_size
        }

    def clear_cache(self):
        """Clear predictor cache."""
        with self.predictor_cache._lock:
            self.predictor_cache._cache.clear()
            self.predictor_cache._access_times.clear()
        self.logger.info("Predictor cache cleared")

    def warm_up_cache(self, model_ids: List[str]):
        """Warm up cache with specified models."""
        for model_id in model_ids:
            try:
                predictor = MLPredictor(model_id, self.registry)
                self.predictor_cache.put(model_id, predictor)
                self.logger.info(f"Warmed up cache for model {model_id}")
            except Exception as e:
                self.logger.error(f"Failed to warm up model {model_id}: {e}")


# JIT-compiled functions for performance optimization
@jit(nopython=True, parallel=True)
def batch_normalize_features(features: np.ndarray, means: np.ndarray, stds: np.ndarray) -> np.ndarray:
    """Normalize batch of features using JIT compilation."""
    normalized = np.empty_like(features)
    for i in prange(features.shape[0]):
        normalized[i] = (features[i] - means) / (stds + 1e-8)
    return normalized


@jit(nopython=True)
def fast_ensemble_predictions(predictions: np.ndarray, weights: np.ndarray) -> float:
    """Fast ensemble prediction using JIT compilation."""
    return np.sum(predictions * weights) / np.sum(weights)