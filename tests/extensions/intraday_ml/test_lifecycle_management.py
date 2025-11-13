"""Tests for model lifecycle management."""

import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from extensions.intraday_ml_lifecycle.version_manager import (
    ModelStatus,
    ModelVersion,
    VersionDatabase,
    VersionManager,
)
from extensions.intraday_ml_models.schemas import (
    FeatureImportance,
    ModelMetadata,
    ModelType,
)


@pytest.fixture
def sample_model_metadata():
    """Create sample model metadata."""
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
def temp_db():
    """Create temporary database for testing."""
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    yield db_path
    Path(db_path).unlink()  # Clean up


class TestModelVersion:
    """Test ModelVersion dataclass."""

    def test_model_version_creation(self):
        """Test ModelVersion creation."""
        version = ModelVersion(
            model_id="test_model",
            version="1.0.0",
            model_type=ModelType.REGRESSION,
            status=ModelStatus.TRAINING,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            created_by="test_user",
            metadata=Mock(),
            file_path="/path/to/model.pkl",
            file_hash="abc123",
            config_hash="def456",
            data_hash="ghi789",
        )

        assert version.model_id == "test_model"
        assert version.version == "1.0.0"
        assert version.status == ModelStatus.TRAINING

    def test_model_version_to_dict(self):
        """Test ModelVersion to_dict conversion."""
        version = ModelVersion(
            model_id="test_model",
            version="1.0.0",
            model_type=ModelType.REGRESSION,
            status=ModelStatus.TRAINING,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            created_by="test_user",
            metadata=Mock(),
            file_path="/path/to/model.pkl",
            file_hash="abc123",
            config_hash="def456",
            data_hash="ghi789",
        )

        data = version.to_dict()
        assert data["model_id"] == "test_model"
        assert data["version"] == "1.0.0"
        assert data["status"] == "training"
        assert data["model_type"] == "regression"
        assert isinstance(data["created_at"], str)
        assert isinstance(data["updated_at"], str)
        assert isinstance(data["tags"], list)

    def test_model_version_from_dict(self):
        """Test ModelVersion from_dict creation."""
        data = {
            "model_id": "test_model",
            "version": "1.0.0",
            "model_type": "regression",
            "status": "training",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "created_by": "test_user",
            "metadata": {"model_id": "test_model"},
            "file_path": "/path/to/model.pkl",
            "file_hash": "abc123",
            "config_hash": "def456",
            "data_hash": "ghi789",
            "tags": ["tag1", "tag2"],
        }

        version = ModelVersion.from_dict(data)
        assert version.model_id == "test_model"
        assert version.version == "1.0.0"
        assert version.status == ModelStatus.TRAINING
        assert version.model_type == ModelType.REGRESSION
        assert isinstance(version.created_at, datetime)
        assert isinstance(version.updated_at, datetime)
        assert version.tags == {"tag1", "tag2"}


class TestVersionDatabase:
    """Test VersionDatabase functionality."""

    def test_database_initialization(self, temp_db):
        """Test database initialization."""
        VersionDatabase(temp_db)

        # Verify tables were created
        conn = sqlite3.connect(temp_db)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()

        assert "model_versions" in tables

    def test_save_and_get_version(self, temp_db, sample_model_metadata):
        """Test saving and retrieving a version."""
        db = VersionDatabase(temp_db)

        version = ModelVersion(
            model_id="test_model",
            version="1.0.0",
            model_type=ModelType.REGRESSION,
            status=ModelStatus.TRAINING,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            created_by="test_user",
            metadata=sample_model_metadata,
            file_path="/path/to/model.pkl",
            file_hash="abc123",
            config_hash="def456",
            data_hash="ghi789",
        )

        # Save version
        db.save_version(version)

        # Retrieve version
        retrieved = db.get_version("test_model", "1.0.0")
        assert retrieved is not None
        assert retrieved.model_id == "test_model"
        assert retrieved.version == "1.0.0"
        assert retrieved.status == ModelStatus.TRAINING

    def test_get_latest_version(self, temp_db, sample_model_metadata):
        """Test getting latest version."""
        db = VersionDatabase(temp_db)

        # Create multiple versions
        versions = [
            ModelVersion(
                model_id="test_model",
                version="1.0.0",
                model_type=ModelType.REGRESSION,
                status=ModelStatus.PRODUCTION,
                created_at=datetime.now() - timedelta(days=2),
                updated_at=datetime.now() - timedelta(days=2),
                created_by="test_user",
                metadata=sample_model_metadata,
                file_path="/path/to/model1.pkl",
                file_hash="abc123",
                config_hash="def456",
                data_hash="ghi789",
            ),
            ModelVersion(
                model_id="test_model",
                version="1.1.0",
                model_type=ModelType.REGRESSION,
                status=ModelStatus.STAGING,
                created_at=datetime.now() - timedelta(days=1),
                updated_at=datetime.now() - timedelta(days=1),
                created_by="test_user",
                metadata=sample_model_metadata,
                file_path="/path/to/model2.pkl",
                file_hash="xyz789",
                config_hash="uvw456",
                data_hash="rst123",
            ),
        ]

        for version in versions:
            db.save_version(version)

        # Get latest version
        latest = db.get_latest_version("test_model")
        assert latest is not None
        assert latest.version == "1.1.0"
        assert latest.status == ModelStatus.STAGING

    def test_update_status(self, temp_db, sample_model_metadata):
        """Test updating version status."""
        db = VersionDatabase(temp_db)

        version = ModelVersion(
            model_id="test_model",
            version="1.0.0",
            model_type=ModelType.REGRESSION,
            status=ModelStatus.TRAINING,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            created_by="test_user",
            metadata=sample_model_metadata,
            file_path="/path/to/model.pkl",
            file_hash="abc123",
            config_hash="def456",
            data_hash="ghi789",
        )

        # Save version
        db.save_version(version)

        # Update status
        db.update_status("test_model", "1.0.0", ModelStatus.PRODUCTION)

        # Verify update
        updated = db.get_version("test_model", "1.0.0")
        assert updated.status == ModelStatus.PRODUCTION
        assert updated.updated_at > version.updated_at

    def test_get_versions_by_status(self, temp_db, sample_model_metadata):
        """Test getting versions by status."""
        db = VersionDatabase(temp_db)

        # Create versions with different statuses
        versions = [
            ModelVersion(
                model_id="model_a",
                version="1.0.0",
                model_type=ModelType.REGRESSION,
                status=ModelStatus.PRODUCTION,
                created_at=datetime.now(),
                updated_at=datetime.now(),
                created_by="test_user",
                metadata=sample_model_metadata,
                file_path="/path/to/model_a.pkl",
                file_hash="abc123",
                config_hash="def456",
                data_hash="ghi789",
            ),
            ModelVersion(
                model_id="model_b",
                version="1.0.0",
                model_type=ModelType.CLASSIFICATION,
                status=ModelStatus.PRODUCTION,
                created_at=datetime.now(),
                updated_at=datetime.now(),
                created_by="test_user",
                metadata=sample_model_metadata,
                file_path="/path/to/model_b.pkl",
                file_hash="xyz789",
                config_hash="uvw456",
                data_hash="rst123",
            ),
            ModelVersion(
                model_id="model_c",
                version="1.0.0",
                model_type=ModelType.REGRESSION,
                status=ModelStatus.STAGING,
                created_at=datetime.now(),
                updated_at=datetime.now(),
                created_by="test_user",
                metadata=sample_model_metadata,
                file_path="/path/to/model_c.pkl",
                file_hash="pqr456",
                config_hash="mno789",
                data_hash="stu123",
            ),
        ]

        for version in versions:
            db.save_version(version)

        # Get production versions
        production_versions = db.get_versions_by_status(ModelStatus.PRODUCTION)
        assert len(production_versions) == 2
        assert all(v.status == ModelStatus.PRODUCTION for v in production_versions)

        # Get staging versions
        staging_versions = db.get_versions_by_status(ModelStatus.STAGING)
        assert len(staging_versions) == 1
        assert staging_versions[0].status == ModelStatus.STAGING

    def test_delete_version(self, temp_db, sample_model_metadata):
        """Test deleting a version."""
        db = VersionDatabase(temp_db)

        version = ModelVersion(
            model_id="test_model",
            version="1.0.0",
            model_type=ModelType.REGRESSION,
            status=ModelStatus.TRAINING,
            created_at=datetime.now(),
            updated_at=datetime.now(),
            created_by="test_user",
            metadata=sample_model_metadata,
            file_path="/path/to/model.pkl",
            file_hash="abc123",
            config_hash="def456",
            data_hash="ghi789",
        )

        # Save version
        db.save_version(version)

        # Verify it exists
        assert db.get_version("test_model", "1.0.0") is not None

        # Delete version
        db.delete_version("test_model", "1.0.0")

        # Verify it's gone
        assert db.get_version("test_model", "1.0.0") is None

    def test_get_child_versions(self, temp_db, sample_model_metadata):
        """Test getting child versions."""
        db = VersionDatabase(temp_db)

        # Create parent version
        parent = ModelVersion(
            model_id="test_model",
            version="1.0.0",
            model_type=ModelType.REGRESSION,
            status=ModelStatus.PRODUCTION,
            created_at=datetime.now() - timedelta(days=2),
            updated_at=datetime.now() - timedelta(days=2),
            created_by="test_user",
            metadata=sample_model_metadata,
            file_path="/path/to/model1.pkl",
            file_hash="abc123",
            config_hash="def456",
            data_hash="ghi789",
        )

        # Create child version
        child = ModelVersion(
            model_id="test_model",
            version="1.1.0",
            model_type=ModelType.REGRESSION,
            status=ModelStatus.STAGING,
            created_at=datetime.now() - timedelta(days=1),
            updated_at=datetime.now() - timedelta(days=1),
            created_by="test_user",
            metadata=sample_model_metadata,
            file_path="/path/to/model2.pkl",
            file_hash="xyz789",
            config_hash="uvw456",
            data_hash="rst123",
            parent_version="test_model:1.0.0",
        )

        db.save_version(parent)
        db.save_version(child)

        # Get child versions
        children = db.get_child_versions("test_model", "1.0.0")
        assert len(children) == 1
        assert children[0].version == "1.1.0"
        assert children[0].parent_version == "test_model:1.0.0"


class TestVersionManager:
    """Test VersionManager functionality."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_db = tempfile.mktemp(suffix=".db")
        self.addCleanup(
            lambda: Path(self.temp_db).unlink() if Path(self.temp_db).exists() else None
        )

    @patch("extensions.intraday_ml_lifecycle.version_manager.MLModelRegistry")
    def test_version_manager_initialization(self, mock_registry_class):
        """Test VersionManager initialization."""
        manager = VersionManager(storage_path=self.temp_db)
        assert manager.registry is not None
        assert manager.db is not None

    @patch("extensions.intraday_ml_lifecycle.version_manager.MLModelRegistry")
    def test_create_version(self, mock_registry_class, sample_model_metadata):
        """Test creating a new version."""
        # Setup mock
        mock_registry = Mock()
        mock_registry.get_metadata.return_value = sample_model_metadata
        mock_registry_class.return_value = mock_registry

        manager = VersionManager(storage_path=self.temp_db)

        # Create temporary model file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pkl") as f:
            f.write(b"mock model data")
            model_file_path = f.name

        try:
            version = manager.create_version(
                model_id="test_model",
                model_type=ModelType.REGRESSION,
                file_path=model_file_path,
                config={"param1": "value1"},
                training_data_hash="data_hash_123",
                created_by="test_user",
            )

            assert version.model_id == "test_model"
            assert version.version == "1.0.0"
            assert version.model_type == ModelType.REGRESSION
            assert version.status == ModelStatus.TRAINING
            assert version.created_by == "test_user"

        finally:
            Path(model_file_path).unlink()

    @patch("extensions.intraday_ml_lifecycle.version_manager.MLModelRegistry")
    def test_create_version_with_parent(self, mock_registry_class, sample_model_metadata):
        """Test creating a version with a parent."""
        # Setup mock
        mock_registry = Mock()
        mock_registry.get_metadata.return_value = sample_model_metadata
        mock_registry_class.return_value = mock_registry

        manager = VersionManager(storage_path=self.temp_db)

        # Create temporary model file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pkl") as f:
            f.write(b"mock model data")
            model_file_path = f.name

        try:
            # Create parent version
            manager.create_version(
                model_id="test_model",
                model_type=ModelType.REGRESSION,
                file_path=model_file_path,
                config={"param1": "value1"},
                training_data_hash="data_hash_123",
                created_by="test_user",
            )

            # Create child version
            child = manager.create_version(
                model_id="test_model",
                model_type=ModelType.REGRESSION,
                file_path=model_file_path,
                config={"param1": "value2"},
                training_data_hash="data_hash_456",
                created_by="test_user",
                parent_version="test_model:1.0.0",
            )

            assert child.parent_version == "test_model:1.0.0"

        finally:
            Path(model_file_path).unlink()

    @patch("extensions.intraday_ml_lifecycle.version_manager.MLModelRegistry")
    def test_update_version_status(self, mock_registry_class, sample_model_metadata):
        """Test updating version status."""
        # Setup mock
        mock_registry = Mock()
        mock_registry.get_metadata.return_value = sample_model_metadata
        mock_registry_class.return_value = mock_registry

        manager = VersionManager(storage_path=self.temp_db)

        # Create temporary model file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pkl") as f:
            f.write(b"mock model data")
            model_file_path = f.name

        try:
            # Create version
            manager.create_version(
                model_id="test_model",
                model_type=ModelType.REGRESSION,
                file_path=model_file_path,
                config={"param1": "value1"},
                training_data_hash="data_hash_123",
                created_by="test_user",
            )

            # Update status
            manager.update_version_status("test_model", "1.0.0", ModelStatus.PRODUCTION)

            # Verify update
            updated = manager.db.get_version("test_model", "1.0.0")
            assert updated.status == ModelStatus.PRODUCTION

        finally:
            Path(model_file_path).unlink()

    @patch("extensions.intraday_ml_lifecycle.version_manager.MLModelRegistry")
    def test_promote_to_production(self, mock_registry_class, sample_model_metadata):
        """Test promoting a version to production."""
        # Setup mock
        mock_registry = Mock()
        mock_registry.get_metadata.return_value = sample_model_metadata
        mock_registry_class.return_value = mock_registry

        manager = VersionManager(storage_path=self.temp_db)

        # Create temporary model file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pkl") as f:
            f.write(b"mock model data")
            model_file_path = f.name

        try:
            # Create version
            manager.create_version(
                model_id="test_model",
                model_type=ModelType.REGRESSION,
                file_path=model_file_path,
                config={"param1": "value1"},
                training_data_hash="data_hash_123",
                created_by="test_user",
            )

            # Update to staging first
            manager.update_version_status("test_model", "1.0.0", ModelStatus.STAGING)

            # Promote to production
            manager.promote_to_production("test_model", "1.0.0", {"accuracy": 0.85})

            # Verify promotion
            promoted = manager.db.get_version("test_model", "1.0.0")
            assert promoted.status == ModelStatus.PRODUCTION

        finally:
            Path(model_file_path).unlink()

    @patch("extensions.intraday_ml_lifecycle.version_manager.MLModelRegistry")
    def test_get_version_history(self, mock_registry_class, sample_model_metadata):
        """Test getting version history."""
        # Setup mock
        mock_registry = Mock()
        mock_registry.get_metadata.return_value = sample_model_metadata
        mock_registry_class.return_value = mock_registry

        manager = VersionManager(storage_path=self.temp_db)

        # Create temporary model file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pkl") as f:
            f.write(b"mock model data")
            model_file_path = f.name

        try:
            # Create multiple versions
            for i in range(3):
                manager.create_version(
                    model_id="test_model",
                    model_type=ModelType.REGRESSION,
                    file_path=model_file_path,
                    config={"param1": f"value{i}"},
                    training_data_hash=f"data_hash_{i}",
                    created_by="test_user",
                )

            # Get history
            history = manager.get_version_history("test_model")
            assert len(history) == 3
            assert all(v.model_id == "test_model" for v in history)

            # Should be ordered by created_at descending
            for i in range(len(history) - 1):
                assert history[i].created_at <= history[i + 1].created_at

        finally:
            Path(model_file_path).unlink()

    @patch("extensions.intraday_ml_lifecycle.version_manager.MLModelRegistry")
    def test_get_production_models(self, mock_registry_class, sample_model_metadata):
        """Test getting production models."""
        # Setup mock
        mock_registry = Mock()
        mock_registry.get_metadata.return_value = sample_model_metadata
        mock_registry_class.return_value = mock_registry

        manager = VersionManager(storage_path=self.temp_db)

        # Create temporary model file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pkl") as f:
            f.write(b"mock model data")
            model_file_path = f.name

        try:
            # Create versions with different statuses
            models_data = [
                ("model_a", ModelStatus.PRODUCTION),
                ("model_b", ModelStatus.STAGING),
                ("model_c", ModelStatus.PRODUCTION),
            ]

            for model_id, status in models_data:
                manager.create_version(
                    model_id=model_id,
                    model_type=ModelType.REGRESSION,
                    file_path=model_file_path,
                    config={"param1": "value1"},
                    training_data_hash="data_hash_123",
                    created_by="test_user",
                )
                manager.update_version_status(model_id, "1.0.0", status)

            # Get production models
            production_models = manager.get_production_models()
            assert len(production_models) == 2
            assert all(v.status == ModelStatus.PRODUCTION for v in production_models)
            assert {v.model_id for v in production_models} == {"model_a", "model_c"}

        finally:
            Path(model_file_path).unlink()

    @patch("extensions.intraday_ml_lifecycle.version_manager.MLModelRegistry")
    def test_cleanup_old_versions(self, mock_registry_class, sample_model_metadata):
        """Test cleaning up old versions."""
        # Setup mock
        mock_registry = Mock()
        mock_registry.get_metadata.return_value = sample_model_metadata
        mock_registry_class.return_value = mock_registry

        manager = VersionManager(storage_path=self.temp_db)

        # Create temporary model file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pkl") as f:
            f.write(b"mock model data")
            model_file_path = f.name

        try:
            # Create many versions
            for i in range(10):
                manager.create_version(
                    model_id="test_model",
                    model_type=ModelType.REGRESSION,
                    file_path=model_file_path,
                    config={"param1": f"value{i}"},
                    training_data_hash=f"data_hash_{i}",
                    created_by="test_user",
                )

            # Should have 10 versions initially
            history = manager.get_version_history("test_model")
            assert len(history) == 10

            # Cleanup keeping only 3
            deleted_count = manager.cleanup_old_versions("test_model", keep_count=3)
            assert deleted_count == 7

            # Should have only 3 versions remaining
            history = manager.get_version_history("test_model")
            assert len(history) == 3

        finally:
            Path(model_file_path).unlink()

    def test_file_hash_calculation(self):
        """Test file hash calculation."""
        manager = VersionManager(storage_path=self.temp_db)

        # Create temporary file with known content
        with tempfile.NamedTemporaryFile(delete=False) as f:
            test_content = b"test content for hashing"
            f.write(test_content)
            temp_path = f.name

        try:
            # Calculate hash
            file_hash = manager._calculate_file_hash(temp_path)

            # Verify it's a valid SHA-256 hash (64 hex characters)
            assert len(file_hash) == 64
            assert all(c in "0123456789abcdef" for c in file_hash)

        finally:
            Path(temp_path).unlink()

    def test_config_hash_calculation(self):
        """Test config hash calculation."""
        manager = VersionManager(storage_path=self.temp_db)

        config1 = {"param1": "value1", "param2": "value2"}
        config2 = {
            "param2": "value2",
            "param1": "value1",
        }  # Same content, different order
        config3 = {"param1": "value1", "param2": "value3"}  # Different content

        hash1 = manager._calculate_config_hash(config1)
        hash2 = manager._calculate_config_hash(config2)
        hash3 = manager._calculate_config_hash(config3)

        # Same content should produce same hash
        assert hash1 == hash2

        # Different content should produce different hash
        assert hash1 != hash3

        # Verify it's a valid SHA-256 hash
        assert len(hash1) == 64
        assert all(c in "0123456789abcdef" for c in hash1)


if __name__ == "__main__":
    pytest.main([__file__])
