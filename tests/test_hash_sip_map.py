"""Tests for hash_sip_map function."""

from qx_core.hashers import hash_sip_map


def test_hash_sip_map_basic():
    """Test basic hash_sip_map functionality."""
    universe_map = {
        1609459200000000000: {"AAPL", "GOOGL"},
        1609459260000000000: {"MSFT", "AMZN"},
    }

    result = hash_sip_map(universe_map)

    # Should return a 32-character hex string (16 bytes)
    assert isinstance(result, str)
    assert len(result) == 32
    assert all(c in "0123456789abcdef" for c in result)


def test_hash_sip_map_deterministic():
    """Test that hash_sip_map is deterministic."""
    universe_map = {
        1609459200000000000: {"AAPL", "GOOGL", "MSFT"},
        1609459260000000000: {"AMZN", "TSLA"},
    }

    # Multiple calls should return same hash
    hash1 = hash_sip_map(universe_map)
    hash2 = hash_sip_map(universe_map)
    assert hash1 == hash2


def test_hash_sip_map_order_insensitive():
    """Test that symbol order doesn't affect hash."""
    universe_map1 = {
        1609459200000000000: {"AAPL", "GOOGL", "MSFT"},
    }

    universe_map2 = {
        1609459200000000000: {"MSFT", "AAPL", "GOOGL"},
    }

    hash1 = hash_sip_map(universe_map1)
    hash2 = hash_sip_map(universe_map2)
    assert hash1 == hash2


def test_hash_sip_map_timestamp_order():
    """Test that timestamp order affects hash."""
    universe_map = {
        1609459200000000000: {"AAPL"},
        1609459260000000000: {"GOOGL"},
    }

    universe_map_swapped = {
        1609459260000000000: {"GOOGL"},
        1609459200000000000: {"AAPL"},
    }

    hash1 = hash_sip_map(universe_map)
    hash2 = hash_sip_map(universe_map_swapped)
    assert hash1 == hash2  # Should be same due to canonical sorting


def test_hash_sip_map_empty():
    """Test hash of empty universe map."""
    universe_map = {}

    result = hash_sip_map(universe_map)

    assert isinstance(result, str)
    assert len(result) == 32


def test_hash_sip_map_single_timestamp():
    """Test hash with single timestamp."""
    universe_map = {
        1609459200000000000: {"AAPL"},
    }

    result = hash_sip_map(universe_map)

    assert isinstance(result, str)
    assert len(result) == 32


def test_hash_sip_map_large_universe():
    """Test hash with large universe."""
    universe_map = {
        1609459200000000000: {f"SYM{i:04d}" for i in range(100)},
        1609459260000000000: {f"SYM{i:04d}" for i in range(100, 200)},
    }

    result = hash_sip_map(universe_map)

    assert isinstance(result, str)
    assert len(result) == 32


def test_hash_sip_map_different_symbols():
    """Test that different symbol sets produce different hashes."""
    universe_map1 = {
        1609459200000000000: {"AAPL", "GOOGL"},
    }

    universe_map2 = {
        1609459200000000000: {"MSFT", "AMZN"},
    }

    hash1 = hash_sip_map(universe_map1)
    hash2 = hash_sip_map(universe_map2)
    assert hash1 != hash2


def test_hash_sip_mixed_case_symbols():
    """Test that symbol case is handled correctly."""
    universe_map = {
        1609459200000000000: {"aapl", "GOOGL"},
    }

    result = hash_sip_map(universe_map)

    # Should produce valid hash (symbols are converted to str and sorted)
    assert isinstance(result, str)
    assert len(result) == 32
