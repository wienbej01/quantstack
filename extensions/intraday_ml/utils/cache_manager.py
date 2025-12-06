"""Cache manager for SIP filtering and feature data."""
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd


class CacheManager:
    """Manage cached data for SIP and features."""
    
    def __init__(self, cache_root: Path = Path("artefacts/cache")):
        self.cache_root = Path(cache_root)
        self.cache_root.mkdir(parents=True, exist_ok=True)
    
    def _compute_hash(self, config: dict[str, Any]) -> str:
        """Compute hash of configuration."""
        config_str = json.dumps(config, sort_keys=True)
        return hashlib.sha256(config_str.encode()).hexdigest()[:16]
    
    def get_cache_path(self, cache_type: str, config: dict[str, Any]) -> Path:
        """Get cache file path for given config."""
        config_hash = self._compute_hash(config)
        return self.cache_root / f"{cache_type}_{config_hash}.parquet"
    
    def exists(self, cache_type: str, config: dict[str, Any]) -> bool:
        """Check if cache exists."""
        return self.get_cache_path(cache_type, config).exists()
    
    def load(self, cache_type: str, config: dict[str, Any]) -> pd.DataFrame | None:
        """Load cached data."""
        path = self.get_cache_path(cache_type, config)
        if path.exists():
            return pd.read_parquet(path)
        return None
    
    def save(self, data: pd.DataFrame, cache_type: str, config: dict[str, Any]) -> Path:
        """Save data to cache."""
        path = self.get_cache_path(cache_type, config)
        data.to_parquet(path, index=False)
        return path
    
    def clear(self, cache_type: str | None = None):
        """Clear cache files."""
        if cache_type:
            for f in self.cache_root.glob(f"{cache_type}_*.parquet"):
                f.unlink()
        else:
            for f in self.cache_root.glob("*.parquet"):
                f.unlink()
