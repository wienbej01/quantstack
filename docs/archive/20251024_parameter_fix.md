Below is a concrete implementation plan—broken into sprints—to adjust your intraday trading gates.  File names and function names are based on the documented structure of the repository; please adapt if your code uses slightly different names.

---

### 📦 **Sprint 1 – Extend the ATR look‑back and calibrate the low‑volatility gate**

1. **Update the configuration**
   Open `configs/settings.yaml`.  Locate the `features` section and change the ATR period from `14` to `30` (or up to `60` if you prefer a full hour).  In the example, the default period is `14`; adjust that value so all modules pick up the longer look‑back.

   ```yaml
   features:
     atr:
       period: 30      # extended look‑back for 15–90 min trades
     ema:
       short_period: 8
       long_period: 21
   ```
2. **Modify ATR calculation defaults**
   Open `src/features/indicators.py` (or `src/features/price_vol.py`, whichever defines the ATR).  Find the `atr` function or the constant `ATR_PERIOD`.  Change its default argument from `period=14` to `period=30`.  If a constant drives the look‑back, update that constant accordingly.

   > *Example:*
   >
   > ```python
   > def atr(high, low, close, period=30):
   >     ...
   > ```
3. **Adjust the “ATR too low” filter**
   In your gating module (`src/policy/filters.py` or `src/signals/detectors.py`), locate the function enforcing the `atr_too_low` gate.  Reduce the minimum ATR threshold to align with the new ATR values.  For instance, if the filter currently skips bars when `atr < 0.2`, lower it to `0.1` or even a percentage of price.

---

### 🚀 **Sprint 2 – Tune the displacement and order‑flow filters**

4. **Relax displacement requirements**
   Find the displacement gate in the same gating module—often named `_displacement_filter` or `check_displacement`.  This gate likely requires the price to be at least *N × ATR* away from an anchor (VWAP or range).  Reduce the multiplier (e.g., from `2 × ATR` to `1 × ATR` or `0.5 × ATR`) to allow trades with smaller price moves while keeping the logic:

   ```
   displacement = abs(price - anchor)
   threshold    = multiplier * ATR
   return displacement > threshold
   ```
5. **Shorten the order‑flow look‑back**
   Locate the order‑flow imbalance filter (gate labelled `ofi_trend`).  Identify the window used to compute the OFI trend.  Replace it with a shorter window—e.g., 5 to 10 minutes (5–10 bars)—so the trend is based on recent order‑flow rather than a multi‑hour average.  Adjust the threshold so that moderate positive or negative trends pass.

---

### 🎯 **Sprint 3 – Ease VWAP/fair‑value‑gap filters**

6. **Add tolerance to the VWAP alignment**
   In `src/signals/detectors.py`, find the function implementing the `avwap_position` gate.  Instead of requiring strict above/below VWAP, allow a tolerance band:

   ```
   # original logic
   long_ok  = price > vwap
   short_ok = price < vwap
   # new logic with tolerance
   tolerance = 0.001  # 0.1 %
   long_ok  = (price - vwap) / price >  tolerance
   short_ok = (vwap - price) / price > tolerance
   ```

   This passes bars where price is within ±0.1 % of VWAP.
7. **Disable or make optional the fair‑value‑gap gate**
   If a fair‑value‑gap check (ICT liquidity sweep) is present—likely in `src/signals/detectors.py`—remove the requirement that `f__ict__fvg_bull_active` or `f__ict__fvg_bear_active` be `True`, or add a configuration flag to bypass this gate.  Fair‑value gaps are rare and can prevent trades entirely.

---

### 🧠 **Sprint 4 – Loosen regime filters and test**

8. **Expand regime thresholds**
   In `src/features/market_context.py` or `src/features/regime.py`, identify the parameters for variance‑ratio (`var_ratio`), ADX proxy (`adx_proxy`) and modified volume (`mod_vol`).  Widen the accepted range—e.g., permit `var_ratio` between `0.5` and `2.0` and lower the ADX threshold from `25` to `15`—so more bars pass the regime filter.
9. **Expose thresholds via configuration**
   Add new entries under `regime` in `configs/settings.yaml`, such as:

   ```yaml
   regime:
     var_ratio_min: 0.5
     var_ratio_max: 2.0
     adx_min: 15
     mod_vol_max: 2500
   ```

   Modify the regime detector code to read these values from the config rather than hard‑coding them.
10. **Re‑run the backtest and iteratively tune**
    After completing the above changes, run `python test_regime_pilot.py` again.  Check the number of trades and adjust the thresholds iteratively until trade frequency and performance align with your 15–90 minute intraday objectives.

---

These instructions align with the repository’s documented structure: `settings.yaml` controls feature periods and thresholds, and trading stops use ATR multiples.  Implementing them should relax overly strict gates and make the strategy suitable for intraday trading on 1‑minute data.
