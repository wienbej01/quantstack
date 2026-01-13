# Development Environment

## S0 Sprint - Environment Setup

### Python Version
```bash
python --version
```
```
Python 3.12.11
```

### Installed Dependencies
```bash
pip list
```
```
annotated-types          0.7.0
black                    25.9.0
cfgv                     3.4.0
click                    8.3.0
distlib                  0.4.0
duckdb                   1.4.1
filelock                 3.20.0
identify                 2.6.15
iniconfig                2.1.0
isort                    7.0.0
markdown-it-py           4.0.0
mdurl                    0.1.2
mypy                     1.10.0
mypy-extensions          1.1.0
nodeenv                  1.9.1
numpy                    2.3.3
packaging                25.0
pandas                   2.3.3
pathspec                 0.12.1
platformdirs             4.5.0
pluggy                   1.6.0
pre-commit               4.3.0
pyarrow                  21.0.0
pydantic                 2.12.0
pydantic-core            2.41.1
pygments                 2.19.2
pytokens                 0.1.10
python-dateutil          2.9.0.post0
pytz                     2025.2
pytest                   8.4.2
ruff                     0.14.0
rich                     14.2.0
shellingham              1.5.4
six                      1.17.0
typer                    0.19.2
typing-extensions        4.15.0
typing-inspection        0.4.2
tzdata                   2025.2
virtualenv               20.35.3
wheel                    0.45.1
```

### Development Tools Status

- **✅ Virtual Environment**: `.venv` created and activated
- **✅ Dependencies**: All required packages installed
- **✅ Pre-commit hooks**: Configured with black, isort, ruff, mypy
- **✅ Test framework**: pytest configured and running
- **✅ Project configuration**: pyproject.toml created with tool configurations

### Pre-commit Hooks
```bash
pre-commit installed at .git/hooks/pre-commit
```

Configured hooks:
- black (code formatting)
- isort (import sorting)
- ruff (linting)
- mypy (type checking)

### Test Results
```bash
pytest -q tests/test_s0_sanity.py
```
```
......                                                                   [100%]
6 passed in 0.12s
```

### Environment Validation
All S0 sprint acceptance criteria have been met:
- ✅ Stable Python environment with version 3.12.11
- ✅ All required dependencies installed and functional
- ✅ Pre-commit hooks installed and configured
- ✅ Tests directory structure with sanity tests passing
- ✅ Development environment documented

### Next Steps
Ready to proceed with S1 sprint: Core Schemas & Hashing (qx-core)