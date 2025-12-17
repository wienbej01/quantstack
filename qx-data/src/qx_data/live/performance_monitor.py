"""Performance monitoring for live trading cycles."""
import logging
import time
from collections import deque
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class PerformanceMonitor:
    """Monitor and track trading cycle performance."""

    def __init__(self, max_history: int = 100):
        self.max_history = max_history
        self.cycle_times = deque(maxlen=max_history)
        self.feature_times = deque(maxlen=max_history)
        self.prediction_times = deque(maxlen=max_history)
        self.order_times = deque(maxlen=max_history)
        self.skipped_cycles = 0
        self.total_cycles = 0
        self.current_cycle_start: Optional[float] = None
        self.phase_start: Optional[float] = None

    def start_cycle(self):
        """Mark the start of a trading cycle."""
        self.current_cycle_start = time.time()
        self.total_cycles += 1

    def record_phase(self, phase: str, duration: float):
        """Record timing for a specific phase."""
        if phase == "features":
            self.feature_times.append(duration)
        elif phase == "predictions":
            self.prediction_times.append(duration)
        elif phase == "orders":
            self.order_times.append(duration)

    def end_cycle(self) -> float:
        """Mark the end of a cycle and return total duration."""
        if self.current_cycle_start is None:
            return 0.0
        
        duration = time.time() - self.current_cycle_start
        self.cycle_times.append(duration)
        self.current_cycle_start = None
        
        if duration > 60:
            logger.warning(f"Cycle exceeded 60s: {duration:.2f}s")
        
        return duration

    def record_skipped_cycle(self):
        """Record a skipped cycle due to timeout."""
        self.skipped_cycles += 1
        logger.warning(f"Cycle skipped (total: {self.skipped_cycles})")

    def get_stats(self) -> Dict[str, float]:
        """Get performance statistics."""
        if not self.cycle_times:
            return {}
        
        return {
            "avg_cycle_time": sum(self.cycle_times) / len(self.cycle_times),
            "max_cycle_time": max(self.cycle_times),
            "min_cycle_time": min(self.cycle_times),
            "avg_feature_time": sum(self.feature_times) / len(self.feature_times) if self.feature_times else 0,
            "avg_prediction_time": sum(self.prediction_times) / len(self.prediction_times) if self.prediction_times else 0,
            "avg_order_time": sum(self.order_times) / len(self.order_times) if self.order_times else 0,
            "skip_rate": self.skipped_cycles / self.total_cycles if self.total_cycles > 0 else 0,
            "total_cycles": self.total_cycles,
            "skipped_cycles": self.skipped_cycles,
        }

    def log_stats(self):
        """Log current performance statistics."""
        stats = self.get_stats()
        if not stats:
            return
        
        logger.info(
            f"Performance: avg={stats['avg_cycle_time']:.1f}s, "
            f"max={stats['max_cycle_time']:.1f}s, "
            f"skip_rate={stats['skip_rate']*100:.1f}%, "
            f"cycles={stats['total_cycles']}"
        )

    def should_skip_cycle(self) -> bool:
        """Check if current cycle should be skipped due to timeout."""
        if self.current_cycle_start is None:
            return False
        
        elapsed = time.time() - self.current_cycle_start
        return elapsed > 60
