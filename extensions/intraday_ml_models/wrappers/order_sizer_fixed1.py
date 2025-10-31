from typing import Any, Dict


class FixedSizeOrderSizer:
    """A simple order sizer that always returns a fixed quantity of 1."""

    def __init__(self, size: int = 1):
        self._size = int(size)

    def __call__(self, signal: Dict[str, Any]) -> int:
        """Returns the fixed order size, ignoring the signal."""
        return self._size


def get_sizer(**kwargs: Any) -> FixedSizeOrderSizer:
    """Factory function for the FixedSizeOrderSizer."""
    return FixedSizeOrderSizer(size=kwargs.get("position_size", 1))
