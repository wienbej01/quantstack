from pathlib import Path

from qx_l2.storage import L2Storage


def test_write_batch_partitions_by_symbol(tmp_path):
    cfg = {"storage": {"base_dir": str(tmp_path)}}
    storage = L2Storage(cfg)

    records = [
        {"date_et": "2025-01-02", "symbol": "HAL", "ts_epoch": 1.0},
        {"date_et": "2025-01-02", "symbol": "PFE", "ts_epoch": 2.0},
        {"date_et": "2025-01-03", "symbol": "HAL", "ts_epoch": 3.0},
    ]

    files = storage.write_batch(records, "raw")
    assert len(files) == 3

    for path in files:
        assert Path(path).exists()
