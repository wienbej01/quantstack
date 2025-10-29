"""Model version management and lifecycle tracking."""

import hashlib
import json
import logging
import time
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
import sqlite3
import threading
from enum import Enum

from extensions.intraday_ml_models.schemas import ModelMetadata, ModelType
from extensions.intraday_ml_models.registry import MLModelRegistry


class ModelStatus(Enum):
    """Model lifecycle status."""
    TRAINING = "training"
    VALIDATING = "validating"
    STAGING = "staging"
    PRODUCTION = "production"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"
    FAILED = "failed"


@dataclass
class ModelVersion:
    """Model version information."""
    model_id: str
    version: str
    model_type: ModelType
    status: ModelStatus
    created_at: datetime
    updated_at: datetime
    created_by: str
    metadata: ModelMetadata
    file_path: str
    file_hash: str
    config_hash: str
    data_hash: str
    training_metrics: Dict[str, float] = field(default_factory=dict)
    validation_metrics: Dict[str, float] = field(default_factory=dict)
    production_metrics: Dict[str, float] = field(default_factory=dict)
    parent_version: Optional[str] = None
    child_versions: List[str] = field(default_factory=list)
    tags: Set[str] = field(default_factory=set)
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        data = asdict(self)
        data["status"] = self.status.value
        data["model_type"] = self.model_type.value
        data["created_at"] = self.created_at.isoformat()
        data["updated_at"] = self.updated_at.isoformat()
        data["tags"] = list(self.tags)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelVersion":
        """Create from dictionary."""
        data["status"] = ModelStatus(data["status"])
        data["model_type"] = ModelType(data["model_type"])
        data["created_at"] = datetime.fromisoformat(data["created_at"])
        data["updated_at"] = datetime.fromisoformat(data["updated_at"])
        data["tags"] = set(data["tags"])
        return cls(**data)


class VersionDatabase:
    """SQLite database for storing model version information."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
        self._lock = threading.Lock()
        self._init_database()

    def _init_database(self):
        """Initialize database schema."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Create model_versions table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS model_versions (
                    model_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    model_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    file_hash TEXT NOT NULL,
                    config_hash TEXT NOT NULL,
                    data_hash TEXT NOT NULL,
                    training_metrics TEXT,
                    validation_metrics TEXT,
                    production_metrics TEXT,
                    parent_version TEXT,
                    child_versions TEXT,
                    tags TEXT,
                    notes TEXT,
                    PRIMARY KEY (model_id, version)
                )
            """)

            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_model_status ON model_versions (status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_model_created_at ON model_versions (created_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_model_updated_at ON model_versions (updated_at)")

            conn.commit()
            conn.close()

    def save_version(self, version: ModelVersion):
        """Save model version to database."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            data = version.to_dict()
            data["metadata"] = json.dumps(asdict(version.metadata))
            data["training_metrics"] = json.dumps(version.training_metrics)
            data["validation_metrics"] = json.dumps(version.validation_metrics)
            data["production_metrics"] = json.dumps(version.production_metrics)
            data["child_versions"] = json.dumps(version.child_versions)

            # UPSERT operation
            cursor.execute("""
                INSERT OR REPLACE INTO model_versions VALUES (
                    :model_id, :version, :model_type, :status, :created_at, :updated_at,
                    :created_by, :metadata, :file_path, :file_hash, :config_hash, :data_hash,
                    :training_metrics, :validation_metrics, :production_metrics,
                    :parent_version, :child_versions, :tags, :notes
                )
            """, data)

            conn.commit()
            conn.close()

        self.logger.info(f"Saved model version {version.model_id}:{version.version}")

    def get_version(self, model_id: str, version: str) -> Optional[ModelVersion]:
        """Get specific model version."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM model_versions WHERE model_id = ? AND version = ?
            """, (model_id, version))

            row = cursor.fetchone()
            conn.close()

            if row:
                return self._row_to_version(row)
            return None

    def get_latest_version(self, model_id: str) -> Optional[ModelVersion]:
        """Get latest version of a model."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM model_versions
                WHERE model_id = ?
                ORDER BY created_at DESC
                LIMIT 1
            """, (model_id,))

            row = cursor.fetchone()
            conn.close()

            if row:
                return self._row_to_version(row)
            return None

    def get_versions_by_status(self, status: ModelStatus) -> List[ModelVersion]:
        """Get all versions with specific status."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM model_versions WHERE status = ? ORDER BY created_at DESC
            """, (status.value,))

            rows = cursor.fetchall()
            conn.close()

            return [self._row_to_version(row) for row in rows]

    def get_production_versions(self) -> List[ModelVersion]:
        """Get all models in production."""
        return self.get_versions_by_status(ModelStatus.PRODUCTION)

    def get_child_versions(self, model_id: str, version: str) -> List[ModelVersion]:
        """Get child versions of a specific version."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM model_versions
                WHERE parent_version = ?
                ORDER BY created_at DESC
            """, (f"{model_id}:{version}",))

            rows = cursor.fetchall()
            conn.close()

            return [self._row_to_version(row) for row in rows]

    def update_status(self, model_id: str, version: str, new_status: ModelStatus):
        """Update model version status."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                UPDATE model_versions
                SET status = ?, updated_at = ?
                WHERE model_id = ? AND version = ?
            """, (new_status.value, datetime.now().isoformat(), model_id, version))

            conn.commit()
            conn.close()

        self.logger.info(f"Updated {model_id}:{version} status to {new_status.value}")

    def delete_version(self, model_id: str, version: str):
        """Delete model version."""
        with self._lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                DELETE FROM model_versions WHERE model_id = ? AND version = ?
            """, (model_id, version))

            conn.commit()
            conn.close()

        self.logger.info(f"Deleted model version {model_id}:{version}")

    def _row_to_version(self, row) -> ModelVersion:
        """Convert database row to ModelVersion."""
        return ModelVersion(
            model_id=row[0],
            version=row[1],
            model_type=ModelType(row[2]),
            status=ModelStatus(row[3]),
            created_at=datetime.fromisoformat(row[4]),
            updated_at=datetime.fromisoformat(row[5]),
            created_by=row[6],
            metadata=ModelMetadata(**json.loads(row[7])),
            file_path=row[8],
            file_hash=row[9],
            config_hash=row[10],
            data_hash=row[11],
            training_metrics=json.loads(row[12]) if row[12] else {},
            validation_metrics=json.loads(row[13]) if row[13] else {},
            production_metrics=json.loads(row[14]) if row[14] else {},
            parent_version=row[15],
            child_versions=json.loads(row[16]) if row[16] else [],
            tags=set(json.loads(row[17])) if row[17] else set(),
            notes=row[18] or ""
        )


class VersionManager:
    """Manages model versions and lifecycle."""

    def __init__(
        self,
        registry: Optional[MLModelRegistry] = None,
        storage_path: str = "model_versions.db"
    ):
        self.registry = registry or MLModelRegistry()
        self.db = VersionDatabase(storage_path)
        self.logger = logging.getLogger(__name__)

    def create_version(
        self,
        model_id: str,
        model_type: ModelType,
        file_path: str,
        config: Dict[str, Any],
        training_data_hash: str,
        created_by: str,
        parent_version: Optional[str] = None,
        notes: str = ""
    ) -> ModelVersion:
        """Create a new model version."""
        self.logger.info(f"Creating new version for model {model_id}")

        # Generate version number
        latest_version = self.db.get_latest_version(model_id)
        if latest_version:
            # Increment version number (semantic versioning)
            version_parts = latest_version.version.split(".")
            patch = int(version_parts[-1]) + 1
            new_version = f"1.0.{patch}"
        else:
            new_version = "1.0.0"

        # Calculate file hash
        file_hash = self._calculate_file_hash(file_path)

        # Calculate config hash
        config_hash = self._calculate_config_hash(config)

        # Load model metadata
        metadata = self.registry.get_metadata(f"{model_id}:{new_version}")

        # Create version object
        version = ModelVersion(
            model_id=model_id,
            version=new_version,
            model_type=model_type,
            status=ModelStatus.TRAINING,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            created_by=created_by,
            metadata=metadata,
            file_path=file_path,
            file_hash=file_hash,
            config_hash=config_hash,
            data_hash=training_data_hash,
            parent_version=parent_version,
            notes=notes
        )

        # Save to database
        self.db.save_version(version)

        # Update parent version if provided
        if parent_version:
            parent_model_id, parent_version_num = parent_version.split(":")
            parent = self.db.get_version(parent_model_id, parent_version_num)
            if parent:
                parent.child_versions.append(f"{model_id}:{new_version}")
                self.db.save_version(parent)

        self.logger.info(f"Created version {model_id}:{new_version}")
        return version

    def update_version_status(
        self,
        model_id: str,
        version: str,
        new_status: ModelStatus,
        metrics: Optional[Dict[str, float]] = None
    ):
        """Update version status and optionally metrics."""
        version_obj = self.db.get_version(model_id, version)
        if not version_obj:
            raise ValueError(f"Version {model_id}:{version} not found")

        # Update status
        self.db.update_status(model_id, version, new_status)

        # Update metrics if provided
        if metrics:
            version_obj.status = new_status
            version_obj.updated_at = datetime.now()

            if new_status == ModelStatus.PRODUCTION:
                version_obj.production_metrics.update(metrics)
            elif new_status == ModelStatus.VALIDATING:
                version_obj.validation_metrics.update(metrics)

            self.db.save_version(version_obj)

    def promote_to_production(self, model_id: str, version: str, metrics: Dict[str, float]):
        """Promote model version to production."""
        # Check if model is in staging
        current_version = self.db.get_version(model_id, version)
        if not current_version or current_version.status != ModelStatus.STAGING:
            raise ValueError(f"Model {model_id}:{version} must be in staging before production")

        # Demote current production version if exists
        current_production = self.db.get_production_versions()
        for prod_version in current_production:
            if prod_version.model_id == model_id:
                self.update_version_status(model_id, prod_version.version, ModelStatus.DEPRECATED)
                break

        # Promote new version
        self.update_version_status(model_id, version, ModelStatus.PRODUCTION, metrics)

    def rollback_version(self, model_id: str, target_version: str) -> ModelVersion:
        """Rollback to a previous version."""
        target = self.db.get_version(model_id, target_version)
        if not target:
            raise ValueError(f"Target version {model_id}:{target_version} not found")

        # Get current production version
        current_production = None
        for prod_version in self.db.get_production_versions():
            if prod_version.model_id == model_id:
                current_production = prod_version
                break

        if current_production:
            # Demote current production
            self.update_version_status(model_id, current_production.version, ModelStatus.DEPRECATED)

        # Promote target version
        self.update_version_status(model_id, target_version, ModelStatus.PRODUCTION)

        self.logger.info(f"Rolled back {model_id} to version {target_version}")
        return target

    def get_version_history(self, model_id: str) -> List[ModelVersion]:
        """Get complete version history for a model."""
        with self.db._lock:
            conn = sqlite3.connect(self.db.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM model_versions
                WHERE model_id = ?
                ORDER BY created_at DESC
            """, (model_id,))

            rows = cursor.fetchall()
            conn.close()

            return [self.db._row_to_version(row) for row in rows]

    def get_production_models(self) -> List[ModelVersion]:
        """Get all models currently in production."""
        return self.db.get_production_versions()

    def compare_versions(self, model_id: str, version1: str, version2: str) -> Dict[str, Any]:
        """Compare two model versions."""
        v1 = self.db.get_version(model_id, version1)
        v2 = self.db.get_version(model_id, version2)

        if not v1 or not v2:
            raise ValueError("One or both versions not found")

        comparison = {
            "version1": {
                "version": v1.version,
                "created_at": v1.created_at,
                "status": v1.status.value,
                "training_metrics": v1.training_metrics,
                "validation_metrics": v1.validation_metrics
            },
            "version2": {
                "version": v2.version,
                "created_at": v2.created_at,
                "status": v2.status.value,
                "training_metrics": v2.training_metrics,
                "validation_metrics": v2.validation_metrics
            }
        }

        # Calculate metric differences
        for metric_name in v1.training_metrics:
            if metric_name in v2.training_metrics:
                diff = v2.training_metrics[metric_name] - v1.training_metrics[metric_name]
                comparison[f"{metric_name}_difference"] = diff

        return comparison

    def cleanup_old_versions(self, model_id: str, keep_count: int = 5):
        """Clean up old versions, keeping only the most recent ones."""
        versions = self.get_version_history(model_id)

        # Keep production, staging, and recent versions
        versions_to_keep = []
        versions_to_delete = []

        for version in versions:
            if version.status in [ModelStatus.PRODUCTION, ModelStatus.STAGING]:
                versions_to_keep.append(version)
            elif len(versions_to_keep) < keep_count:
                versions_to_keep.append(version)
            else:
                versions_to_delete.append(version)

        # Delete old versions
        for version in versions_to_delete:
            self.db.delete_version(version.model_id, version.version)
            self.logger.info(f"Deleted old version {version.model_id}:{version.version}")

        return len(versions_to_delete)

    def _calculate_file_hash(self, file_path: str) -> str:
        """Calculate SHA-256 hash of model file."""
        hash_sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_sha256.update(chunk)
        return hash_sha256.hexdigest()

    def _calculate_config_hash(self, config: Dict[str, Any]) -> str:
        """Calculate SHA-256 hash of configuration."""
        config_str = json.dumps(config, sort_keys=True)
        return hashlib.sha256(config_str.encode()).hexdigest()

    def export_versions(self, model_id: str, output_path: str):
        """Export version history to JSON file."""
        versions = self.get_version_history(model_id)
        data = [version.to_dict() for version in versions]

        with open(output_path, 'w') as f:
            json.dump(data, f, indent=2, default=str)

        self.logger.info(f"Exported {len(versions)} versions to {output_path}")

    def import_versions(self, input_path: str):
        """Import version history from JSON file."""
        with open(input_path, 'r') as f:
            data = json.load(f)

        imported_count = 0
        for version_data in data:
            try:
                version = ModelVersion.from_dict(version_data)
                self.db.save_version(version)
                imported_count += 1
            except Exception as e:
                self.logger.error(f"Failed to import version: {e}")

        self.logger.info(f"Imported {imported_count} versions from {input_path}")