Below is a detailed, explicit set of step‑by‑step instructions for a developer to implement **all four recommendations** in the `wienbej01/quantstack` repository.  Each step references the exact files/methods to be modified and includes guidelines for writing tests.  **Do not include any synthetic/mock data in the code or tests.**

---

### 1. Enable the computation of enhanced features

**File to modify:** `test_regime_pilot.py` (located at the root of the repo or under the `scripts/tests/` directory, depending on project layout).

**Steps:**

1. Locate the `prepare_features` function.  Currently it calls `compute_all_core_features` and `compute_all_regime_features`, then prints a message saying enhanced features are skipped.

2. **Uncomment or add** a call to `compute_all_regime_enhanced_features` immediately after computing the basic regime features:

   ```python
   from qx_features.regime_enhanced import compute_all_regime_enhanced_features
   ...
   features = compute_all_core_features(bars)
   regime_features = compute_all_regime_features(features)
   # compute enhanced features
   enhanced_features = compute_all_regime_enhanced_features(features)
   # merge or update features with enhanced_features as required
   ```

3. Remove or comment out the print statement that says “Enhanced features skipped…”.

4. Ensure that the enhanced features are merged or assigned correctly into the feature DataFrame (e.g. `features.update(enhanced_features)`) so that policies can access fields like `f__anchor__session_avwap`, `f__profile__poc`, etc.

---

### 2. Moderate the default regime thresholds

**File to modify:** `qx_core/regime/detector.py`

**Steps:**

1. Find the `RegimeDetectorConfig` dataclass.  It defines default values for regime classification.
2. Update the default parameters as follows (or to the specific values recommended by domain experts):

   * `variance_ratio_bull` **→** `1.2`
   * `variance_ratio_bear` **→** `0.8`
   * `adx_trend_threshold` **→** `20.0`
   * `volatility_high_threshold` **→** `1.6`
   * `volatility_low_threshold` **→** `0.8`
   * If the class sets `persistence_bars`, set it to `2` or `3` as recommended for faster regime transitions.
3. Ensure these defaults propagate through `create_default_detector()` (which likely instantiates `RegimeDetectorConfig()` internally).  If values are hard‑coded in `create_default_detector`, update them there too.

---

### 3. Adjust risk thresholds used in policies

**File to modify:** `qx_backtest/policies/regime_aligned.py`

**Steps:**

1. Locate the `PolicyParameters` dataclass at the top of this file.
2. Change the default values for risk parameters:

   * `min_risk_reward` **→** `1.0`  (lower risk/reward requirement to capture more trades)
   * `min_atr_value` **→** `0.005`  (lower minimum ATR requirement to allow trades in low‑volatility markets)
3. If any strategy‑specific parameter classes (e.g. `MomentumParameters`, `PullbackParameters`, `ValueRotationParameters`, `SweepReversionParameters`) override these risk parameters, ensure they use the new default values or adjust accordingly.
4. Scan the rest of the file to make sure no hard‑coded fallback checks use the old thresholds.

---

### 4. Remove all synthetic data creation and usage

**File to modify:** `test_regime_pilot.py`

**Steps:**

1. Delete the `create_synthetic_data` function entirely.
2. In `load_test_data`:

   * Remove any calls to `create_synthetic_data` or fallback logic.  The function should **fail fast** if real data isn’t available.  For example, if the expected data file cannot be loaded, it should raise a `FileNotFoundError` or return `None` with a clear error message.
   * Do not generate synthetic random bars under any circumstances.
3. Search the repository for any other references to `create_synthetic_data` or similar synthetic/mock data generators and delete them.
4. Ensure that all tests use **real datasets** or publicly available sample files.  Do not produce or rely on random data for feature calculation or strategy testing.

---

### 5. Write tests to verify the changes

Create new tests under the existing test suite (for example, `tests/test_regime_modifications.py`) using the same testing framework currently in use (pytest).  **Do not use any synthetic/mock data; load real gold data as required.**

#### Test 1 – Enhanced features inclusion

* Load a sample dataset (the same real data used in the pilot).
* Run `prepare_features()` and assert that the output features DataFrame includes **at least one enhanced feature**, such as `f__anchor__session_avwap`, `f__profile__poc`, or another field known to come exclusively from `compute_all_regime_enhanced_features`.
* This ensures the enhanced feature computation is enabled.

#### Test 2 – Regime threshold defaults

* Import `RegimeDetectorConfig` and instantiate it with default arguments.
* Assert that the fields equal the new values:

  ```python
  config = RegimeDetectorConfig()
  assert config.variance_ratio_bull == 1.2
  assert config.variance_ratio_bear == 0.8
  assert config.adx_trend_threshold == 20.0
  assert config.volatility_high_threshold == 1.6
  assert config.volatility_low_threshold == 0.8
  assert config.persistence_bars in (2, 3)
  ```

#### Test 3 – Policy parameter thresholds

* Import `PolicyParameters` (and any relevant subclass if needed).
* Instantiate it with defaults.
* Assert that `min_risk_reward` equals `1.0` and `min_atr_value` equals `0.005`.

#### Test 4 – No synthetic data usage

* Check that `test_regime_pilot.py` no longer defines or references `create_synthetic_data` (e.g. `assert not hasattr(module, 'create_synthetic_data')`).
* Attempt to load data through `load_test_data` in an environment without the gold data and verify that it raises `FileNotFoundError` (or whichever exception you chose) rather than silently creating synthetic data.
* This confirms the fallback is removed.

---

**Important notes for the developer:**

* When modifying dataclasses or defaults, make sure to update any dependent factory functions or tests.
* Keep all docstrings and comments in the code up‑to‑date to reflect the new thresholds and removal of synthetic data.
* After implementing these changes and adding tests, run the entire test suite to confirm that existing functionality still works with real data and the new settings.
