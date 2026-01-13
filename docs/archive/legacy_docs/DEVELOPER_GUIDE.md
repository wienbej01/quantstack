# DEVELOPER GUIDE

## Environment
```bash
cd ~/quantstack
python -m venv .venv && source .venv/bin/activate
make install   # or pip install -e 'qx-core qx-cli qx-backtest qx-features qx-report'
```

## Coding standards
- Type hints for all public APIs; docstrings with input/output contract.
- Strict schema validation at all IO boundaries.
- No side effects in features; reproducibility mandatory.

## Tests
```bash
pytest -q
python test_exp_artifacts.py --runs-root runs
```
