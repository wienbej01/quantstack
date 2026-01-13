# CLI REFERENCE (qx-cli)

```
python -m qx_cli exp --help
```

### Examples
- A/B:
  ```bash
  python -m qx_cli exp entry-ab --cfg config/strategy.yaml --variants overlays/policy_*.yaml --name exp_ab
  ```
- Compare:
  ```bash
  python -m qx_cli exp compare --exp experiments/exp_ab
  ```
