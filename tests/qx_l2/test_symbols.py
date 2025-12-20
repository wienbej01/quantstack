from qx_l2.symbols import L2SymbolSelector


def test_rotation_is_deterministic():
    cfg = {
        "symbols": {
            "mode": "rotating",
            "rotating_pool": ["HAL", "PFE", "LUV", "MOS"],
            "max_symbols": 2,
        }
    }
    selector = L2SymbolSelector(cfg)

    first = selector.get_symbols("2025-01-02")
    second = selector.get_symbols("2025-01-02")

    assert first == second
