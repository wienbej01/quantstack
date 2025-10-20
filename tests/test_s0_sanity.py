"""
S0 Sprint Sanity Tests
Tests to verify the development environment is properly configured.
"""

import duckdb
import numpy as np
import pandas as pd
import pydantic
import rich
import typer


def test_python_imports():
    """Test that core dependencies can be imported."""
    assert pd.__version__ is not None
    assert np.__version__ is not None
    assert pydantic.__version__ is not None
    assert duckdb.__version__ is not None
    assert typer.__version__ is not None
    # Rich doesn't expose __version__ in the same way, just check it's importable
    assert rich is not None


def test_basic_pandas_functionality():
    """Test basic pandas functionality."""
    df = pd.DataFrame({"a": [1, 2, 3], "b": [4.0, 5.0, 6.0]})
    assert len(df) == 3
    assert df["a"].sum() == 6


def test_basic_numpy_functionality():
    """Test basic numpy functionality."""
    arr = np.array([1, 2, 3])
    assert arr.sum() == 6
    assert arr.mean() == 2.0


def test_basic_pydantic_functionality():
    """Test basic pydantic functionality."""
    from pydantic import BaseModel

    class TestModel(BaseModel):
        name: str
        value: int

    model = TestModel(name="test", value=42)
    assert model.name == "test"
    assert model.value == 42


def test_basic_duckdb_functionality():
    """Test basic duckdb functionality."""
    conn = duckdb.connect(":memory:")
    result = conn.execute("SELECT 1 as test_col").fetchall()
    assert result == [(1,)]
    conn.close()


def test_environment_setup():
    """Test that environment markers are present."""
    import os

    # Check that we're running from the quantstack directory
    assert os.path.exists("pyproject.toml")
    assert os.path.exists(".pre-commit-config.yaml")
    assert os.path.exists("tests/")
