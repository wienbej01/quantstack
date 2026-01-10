# Sprint Plan: Refactoring the Intraday ML Data Pipeline

**Date:** 2025-10-29

**Author:** Gemini Quant Team

**Context:** This document outlines the sprint plan to rectify a critical design flaw in the intraday machine learning pipeline. The current system generates features and labels from non-overlapping time periods, making model training impossible. This plan details the steps required to refactor the data preparation process to produce correctly aligned time-series data suitable for robust model training and validation.

---

## 1. Guiding Principles & Compliance Rules

This refactoring is a critical system modification. All work must adhere to the following principles:

*   **Preservation of Core Modules:** The `qx-*` modules (`qx-core`, `qx-data`, `qx-features`, etc.) are considered stable and are used by other trading systems. **Under no circumstances should the code within these modules be modified.** All new logic should be contained within the `extensions/intraday_ml/` directory, creating wrappers or new workflows that *use* the core modules.
*   **Market Reality Compliance:** All testing and validation must be performed on real historical market data. The use of synthetic or mock data is **strictly prohibited**, except for isolated unit tests of simple, non-market-facing functions (e.g., utility functions for data transformation).
*   **No Lookahead Bias:** The new pipeline must be rigorously designed and tested to ensure there is no lookahead bias. At any given timestamp `t`, only information available at or before `t` should be used for feature generation.
*   **Reproducibility:** The entire data preparation and model training process must be fully reproducible. All data sources, configurations, and code versions must be tracked.
*   **Performance:** The new data pipeline should be designed with performance in mind, but correctness and robustness are the primary priorities. Performance optimization can be addressed in a later phase if necessary.

---

## 2. Sprint Breakdown

This project is divided into two main sprints, followed by a final validation and documentation phase.

### **Sprint 1: Core Data Pipeline Refactoring (1 week)**

**Goal:** Create a new, robust data preparation pipeline that generates correctly aligned feature-label pairs.

*   **Sub-task 1.1: Design New Data Preparation Workflow**
    *   **Action:** Create a new module, e.g., `extensions/intraday_ml/data_prep.py`.
    *   **Details:** This module will contain a primary function, e.g., `create_training_dataset`, that takes a date range and a set of symbols and returns a single Pandas DataFrame with aligned features and labels.
    *   **Acceptance Criteria:** The design is documented and reviewed by the team before implementation.

*   **Sub-task 1.2: Implement the "Sliding Window" Data Loader**
    *   **Action:** Within `data_prep.py`, implement the logic to load a continuous block of historical data for the specified date range.
    *   **Details:** This loader will iterate through the data, providing a "sliding window" of data for each timestamp. For each timestamp `t`, it will provide the historical data up to `t` and the future data for the labeling horizon.
    *   **Acceptance Criteria:** The loader correctly loads data and provides the correct data windows for given timestamps.

*   **Sub-task 1.3: Adapt Feature Generation**
    *   **Action:** Create a function in `data_prep.py` that, for a given timestamp `t`, takes the historical data window and calls the existing `qx-features` library to generate a feature vector.
    *   **Details:** This will involve calling `intraday_ml_apply_features` (or the underlying `qx-features` functions) repeatedly for each timestamp. The performance implications of this should be noted.
    *   **Acceptance Criteria:** The function returns a correct feature vector for a given timestamp, using only data from before that timestamp.

*   **Sub-task 1.4: Adapt Label Generation**
    *   **Action:** Refactor the `IntradayMLLabeler` in `extensions/intraday_ml/labeling.py`.
    *   **Details:** Create a new method, e.g., `compute_label_for_timestamp`, that takes the data for the prediction horizon *after* a timestamp `t` and returns a single label. The existing `create_labels` method, which is based on `ts_cut`, should be marked as deprecated.
    *   **Acceptance Criteria:** The new method correctly calculates a single label based on future price movement.

*   **Sub-task 1.5: Combine Features and Labels**
    *   **Action:** In the main `create_training_dataset` function, combine the generated features and labels into a single DataFrame.
    *   **Details:** The resulting DataFrame should have columns for all features and a final column for the label, indexed by timestamp.
    *   **Acceptance Criteria:** The output is a single, correctly indexed DataFrame with no misalignment between features and labels.

### **Sprint 2: Integration, Training, and Validation (1 week)**

**Goal:** Integrate the new data pipeline into the training and backtesting workflow and validate the end-to-end process.

*   **Sub-task 2.1: Update `run_phaseA_pipeline.py`**
    *   **Action:** Modify the main pipeline script to use the new `create_training_dataset` function.
    *   **Details:** The old steps for separate feature and label generation will be replaced by a single call to the new data preparation function.
    *   **Acceptance Criteria:** The script runs without errors and successfully generates a training dataset.

*   **Sub-task 2.2: Run Model Training**
    *   **Action:** Use the newly generated dataset to train the LightGBM model using the existing `LightGBMTrainer`.
    *   **Details:** The trainer should now receive a correctly aligned DataFrame and should be able to train the model successfully.
    *   **Acceptance Criteria:** The model trains successfully, and the training metrics (e.g., accuracy, ROC AUC) are reasonable and indicate that the model is learning from the data.

*   **Sub-task 2.3: End-to-End Validation**
    *   **Action:** Perform a full end-to-end run of the pipeline, from data preparation to model training and evaluation.
    *   **Details:** Use a defined historical period (e.g., 2023) for training and a subsequent period (e.g., Q1 2024) for out-of-sample validation.
    *   **Acceptance Criteria:** The pipeline completes successfully, and the out-of-sample performance of the trained model is evaluated and documented.

*   **Sub-task 2.4: Update Cross-Validation**
    *   **Action:** Update the `TimeSeriesCVRunner` to work with the new aligned dataset.
    *   **Details:** The cross-validation logic should now be simpler, as it can operate on a single, pre-aligned DataFrame.
    *   **Acceptance Criteria:** The cross-validation process runs correctly and produces a meaningful report.

---

## 3. Full Test Regime

A comprehensive testing strategy is required to ensure the correctness and robustness of the new pipeline.

*   **Unit Tests:**
    *   Test the `compute_label_for_timestamp` function in `labeling.py` with known price movements to ensure it produces the correct labels (+1, -1, 0).
    *   Test the feature generation wrapper to ensure it correctly handles edge cases (e.g., start of the dataset).
    *   Use real, but very short, snippets of historical data for these tests.

*   **Integration Tests:**
    *   Write a test that runs the `create_training_dataset` function on a small, controlled dataset (e.g., one week of data for one symbol).
    *   Manually verify a few rows of the output DataFrame to ensure that the features and labels are correctly aligned and that the "no lookahead" rule is not violated.

*   **End-to-End (E2E) Test:**
    *   The successful execution of the updated `run_phaseA_pipeline.py` on a multi-month dataset will serve as the primary E2E test.
    *   The results of this run (trained model, performance metrics, etc.) should be saved as artifacts for comparison with future runs.

---

## 4. Code Review and Release Checklist

Before merging the changes into the main branch, the following checklist must be completed:

*   [ ] All new code is peer-reviewed by at least one other member of the quant team.
*   [ ] All unit and integration tests are passing.
*   [ ] The full end-to-end pipeline has been run successfully on a representative dataset.
*   [ ] The "no lookahead" principle has been manually verified in the integration test.
*   [ ] No core `qx-*` modules have been modified.
*   [ ] All new configuration options are documented.
*   [ ] The `README.md` for the `intraday_ml` extension is updated to reflect the new data preparation workflow.
*   [ ] The old, incorrect data preparation logic in `run_phaseA_pipeline.py` has been removed.
*   [ ] The deprecated `create_labels` method in `labeling.py` is clearly marked with a `DeprecationWarning`.
