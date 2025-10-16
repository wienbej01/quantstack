"""Policy registry and imports for qx-backtest."""

from .base import Policy
from .vwap_momentum import VwapMomentumPolicy, VwapMomentumPolicyEnhanced
from .vwap_revert import VwapRevertPolicy, VwapRevertPolicyEnhanced

# Policy registry
POLICY_REGISTRY = {
    "VwapRevert": VwapRevertPolicy,
    "VwapRevertEnhanced": VwapRevertPolicyEnhanced,
    "VwapMomentum": VwapMomentumPolicy,
    "VwapMomentumEnhanced": VwapMomentumPolicyEnhanced,
}


def get_policy_class(name: str | None) -> type[Policy] | None:
    """Get policy class by name."""
    if not name:
        return None
    return POLICY_REGISTRY.get(name)


def list_policies() -> list[str]:
    """List all available policy names."""
    return list(POLICY_REGISTRY.keys())


__all__ = [
    "Policy",
    "VwapRevertPolicy",
    "VwapRevertPolicyEnhanced",
    "VwapMomentumPolicy",
    "VwapMomentumPolicyEnhanced",
    "POLICY_REGISTRY",
    "get_policy_class",
    "list_policies",
]
