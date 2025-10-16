"""Test documentation completeness and accessibility."""

import os
import subprocess

import pytest

MIN_CONTENT_LENGTH = 1000


def test_documentation_completeness() -> None:
    """Test that required documentation exists."""
    # Check that documentation file exists
    assert os.path.exists(
        "docs/vwap_momentum_guide.md"
    ), "VWAP momentum guide should exist"

    # Check that README mentions momentum policy
    readme_path = "README.md"
    if os.path.exists(readme_path):
        with open(readme_path) as f:
            readme_content = f.read()
            assert (
                "VwapMomentum" in readme_content
            ), "README should mention VwapMomentum policy"
            assert (
                "momentum" in readme_content.lower()
            ), "README should mention momentum strategy"
    else:
        pytest.skip("README.md not found")


def test_documentation_content() -> None:
    """Test that documentation contains required sections."""
    guide_path = "docs/vwap_momentum_guide.md"
    assert os.path.exists(guide_path), "VWAP momentum guide should exist"

    with open(guide_path) as f:
        content = f.read()

    # Check for required sections
    required_sections = [
        "# VWAP Momentum Breakout Strategy Guide",
        "## Overview",
        "## Strategy Logic",
        "## Entry Signals",
        "## Exit Signals",
        "## Parameters",
        "## Enhanced Version",
        "## Usage",
        "## Comparison with VWAP Reversion",
    ]

    for section in required_sections:
        assert section in content, f"Documentation should contain section: {section}"


def test_documentation_examples() -> None:
    """Test that documentation contains working code examples."""
    guide_path = "docs/vwap_momentum_guide.md"
    assert os.path.exists(guide_path), "VWAP momentum guide should exist"

    with open(guide_path) as f:
        content = f.read()

    # Check for Python code examples
    assert "```python" in content, "Documentation should contain Python code examples"
    assert (
        "VwapMomentumPolicy(" in content
    ), "Documentation should show policy instantiation"
    assert (
        "VwapMomentumPolicyEnhanced(" in content
    ), "Documentation should show enhanced policy usage"


def test_experiment_configurations() -> None:
    """Test that experiment configurations exist and are valid."""
    # Check that experiment configs exist
    assert os.path.exists(
        "experiments/vwap_momentum_test/strategy.yaml"
    ), "Test strategy config should exist"
    assert os.path.exists(
        "experiments/vwap_comparison/manifest.json"
    ), "Comparison manifest should exist"

    # Check that comparison configs exist
    comparison_configs = [
        "experiments/vwap_comparison/base_strategy.yaml",
        "experiments/vwap_comparison/revert_overlay.yaml",
        "experiments/vwap_comparison/momentum_overlay.yaml",
    ]

    for config_path in comparison_configs:
        assert os.path.exists(
            config_path
        ), f"Comparison config should exist: {config_path}"


def test_documentation_readability() -> None:
    """Test that documentation is readable and well-structured."""
    guide_path = "docs/vwap_momentum_guide.md"
    assert os.path.exists(guide_path), "VWAP momentum guide should exist"

    with open(guide_path) as f:
        content = f.read()

    # Check minimum content length
    assert (
        len(content) > MIN_CONTENT_LENGTH
    ), f"Documentation should be comprehensive ({MIN_CONTENT_LENGTH}+ characters)"

    # Check for tables or comparison sections
    assert (
        "|" in content or "###" in content
    ), "Documentation should contain structured comparison"

    # Check for parameter descriptions
    assert (
        "vwap_window" in content
    ), "Documentation should describe vwap_window parameter"
    assert (
        "min_breakout_strength" in content
    ), "Documentation should describe min_breakout_strength parameter"


def test_documentation_accessibility() -> None:
    """Test that documentation is accessible from the project root."""

    # Test that guide can be accessed
    try:
        result = subprocess.run(
            ["head", "-20", "docs/vwap_momentum_guide.md"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0, "Should be able to read documentation"
        assert (
            "VWAP Momentum" in result.stdout
        ), "Documentation should contain expected content"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        # Command not available, test file directly
        with open("docs/vwap_momentum_guide.md") as f:
            content = f.read(500)  # Read first 500 characters
            assert "VWAP Momentum" in content, "Documentation should be accessible"
