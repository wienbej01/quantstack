"""Base experiment framework for QuantStack."""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
from pydantic import BaseModel


@dataclass
class ExperimentConfig:
    """Base configuration for experiments."""

    # Experiment metadata
    name: str
    description: str = ""
    tags: List[str] = field(default_factory=list)

    # Data parameters
    symbols: List[str] = field(default_factory=list)
    start_date: Optional[str] = None
    end_date: Optional[str] = None

    # Output parameters
    output_dir: str = "runs"
    save_artifacts: bool = True

    # Execution parameters
    parallel: bool = False
    max_workers: int = 4

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "tags": self.tags,
            "symbols": self.symbols,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "output_dir": self.output_dir,
            "save_artifacts": self.save_artifacts,
            "parallel": self.parallel,
            "max_workers": self.max_workers,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExperimentConfig":
        """Create config from dictionary."""
        return cls(**data)


@dataclass
class ExperimentResult:
    """Results from experiment execution."""

    # Experiment metadata
    experiment_id: str
    config: ExperimentConfig
    start_time: datetime
    end_time: Optional[datetime] = None

    # Results data
    results: Dict[str, Any] = field(default_factory=dict)
    artifacts: Dict[str, str] = field(default_factory=dict)  # file paths

    # Status
    status: str = "pending"  # pending, running, completed, failed
    error_message: Optional[str] = None

    # Performance metrics
    duration_seconds: float = 0.0
    memory_usage_mb: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary."""
        return {
            "experiment_id": self.experiment_id,
            "config": self.config.to_dict(),
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "results": self.results,
            "artifacts": self.artifacts,
            "status": self.status,
            "error_message": self.error_message,
            "duration_seconds": self.duration_seconds,
            "memory_usage_mb": self.memory_usage_mb,
        }

    def save_artifact(self, name: str, data: Any, format: str = "json") -> str:
        """Save an artifact and return the file path."""
        if not self.config.save_artifacts:
            return ""

        import os

        os.makedirs(self.config.output_dir, exist_ok=True)

        timestamp = self.start_time.strftime("%Y%m%d_%H%M%S")
        filename = f"{self.experiment_id}_{name}_{timestamp}.{format}"
        filepath = os.path.join(self.config.output_dir, filename)

        if format == "json":
            with open(filepath, "w") as f:
                json.dump(data, f, indent=2, default=str)
        elif format == "csv" and isinstance(data, pd.DataFrame):
            data.to_csv(filepath, index=False)
        elif format == "parquet" and isinstance(data, pd.DataFrame):
            data.to_parquet(filepath, index=False)
        else:
            raise ValueError(f"Unsupported format: {format}")

        self.artifacts[name] = filepath
        return filepath


class BaseExperiment(ABC):
    """Base class for all experiments."""

    def __init__(self, config: ExperimentConfig):
        """Initialize experiment.

        Args:
            config: Experiment configuration
        """
        self.config = config
        self.experiment_id = f"{config.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    @abstractmethod
    def run(self) -> ExperimentResult:
        """Run the experiment.

        Returns:
            ExperimentResult with execution results
        """
        pass

    @abstractmethod
    def validate_config(self) -> None:
        """Validate experiment configuration."""
        pass

    def execute(self) -> ExperimentResult:
        """Execute the experiment with proper setup/teardown."""
        # Validate configuration
        self.validate_config()

        # Create result object
        result = ExperimentResult(
            experiment_id=self.experiment_id,
            config=self.config,
            start_time=datetime.now(),
            status="running",
        )

        try:
            # Run the experiment
            self._log_start()
            actual_result = self.run()

            # Update result with actual results
            result.results = actual_result.results
            result.artifacts = actual_result.artifacts
            result.status = "completed"

            self._log_success()

        except Exception as e:
            result.status = "failed"
            result.error_message = str(e)
            self._log_error(e)
            raise

        finally:
            # Finalize result
            result.end_time = datetime.now()
            if result.start_time:
                result.duration_seconds = (
                    result.end_time - result.start_time
                ).total_seconds()

            self._log_end(result)

        return result

    def _log_start(self) -> None:
        """Log experiment start."""
        print(f"Starting experiment: {self.config.name}")
        print(f"Experiment ID: {self.experiment_id}")
        print(f"Symbols: {self.config.symbols}")
        if self.config.start_date and self.config.end_date:
            print(f"Date range: {self.config.start_date} to {self.config.end_date}")
        print("-" * 50)

    def _log_success(self) -> None:
        """Log successful completion."""
        print(f"✓ Experiment completed successfully")

    def _log_error(self, error: Exception) -> None:
        """Log experiment error."""
        print(f"✗ Experiment failed: {error}")

    def _log_end(self, result: ExperimentResult) -> None:
        """Log experiment end."""
        print(f"Duration: {result.duration_seconds:.2f} seconds")
        print(f"Status: {result.status}")
        if result.artifacts:
            print(f"Artifacts saved: {len(result.artifacts)}")
        print("=" * 50)
