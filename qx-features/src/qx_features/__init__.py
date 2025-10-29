"""qx-features: Feature engineering pipelines and registry."""

from .core_basics import (
    atr_m,
    compute_all_core_features,
    compute_warmup_masks,
    get_feature_name,
    rel_volume_m,
    validate_feature_inputs,
    vwap_m,
)
from .regime_enhanced import (
    compute_all_regime_enhanced_features,
    compute_avwap_features,
    compute_ict_structures,
    compute_intraday_volume_profile,
    compute_order_flow_vpa,
    compute_stress_contraction,
)
from .registry import (
    FeatureRegistry,
    apply,
    apply_feature_packs,
    compute_feature_hashes,
    create_feature_pack_config,
    validate_feature_pack_config,
)

__version__ = "0.1.0"

__all__ = [
    # Core features
    "vwap_m",
    "rel_volume_m",
    "atr_m",
    "compute_all_core_features",
    "compute_warmup_masks",
    "validate_feature_inputs",
    "get_feature_name",
    # Regime-enhanced features
    "compute_all_regime_enhanced_features",
    "compute_avwap_features",
    "compute_ict_structures",
    "compute_intraday_volume_profile",
    "compute_order_flow_vpa",
    "compute_stress_contraction",
    # Registry and application
    "FeatureRegistry",
    "apply",
    "apply_feature_packs",
    "compute_feature_hashes",
    "validate_feature_pack_config",
    "create_feature_pack_config",
]
