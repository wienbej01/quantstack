  Sprint 1: Core Data Pipeline Refactoring

  Prompt 1.1: Design the Data Preparation Module
  "We are starting Sprint 1, Sub-task 1.1 from 20251029_ML-logic-fix.md.

  Based on the principles in that document, propose the file structure and function signatures for the new extensions/intraday_ml/data_prep.py module.
  This module's primary goal is to implement the 'Sliding Window' approach to generate a single, aligned feature-label DataFrame. Ensure the design is
  modular and includes functions for loading data, generating a feature vector for a single timestamp, and computing a label for a single timestamp."

  Prompt 1.2: Implement the Labeling Function (TDD)
  "Now, let's implement Sprint 1, Sub-task 1.4. We are modifying extensions/intraday_ml/labeling.py.

  First, write the unit tests for a new method compute_label_for_timestamp. These tests must use a small, real historical data sample and verify that the
   function correctly calculates labels (+1, -1, 0) for given future price movements.

  After I approve the tests, you will write the compute_label_for_timestamp method itself and mark the old create_labels method with a
  DeprecationWarning."

  Prompt 1.3: Implement the Feature & Label Generation Loop (TDD)
  "We are now on Sprint 1, Sub-tasks 1.2, 1.3, and 1.5. We will implement the core logic in extensions/intraday_ml/data_prep.py.

  First, write an integration test for the main function create_training_dataset. This test should:
   1. Load one week of real 'BAC' data.
   2. Call create_training_dataset.
   3. Assert that the output is a single DataFrame.
   4. Assert that there are no NaN values in the label column.
   5. Manually check and print the feature vector and label for a specific, known timestamp in the middle of the week to prove there is no lookahead bias.

  After I approve the test, write the create_training_dataset function. This function must strictly adhere to the sprint plan: load data once, iterate
  through each timestamp, and for each timestamp, call the feature generation and the new compute_label_for_timestamp function to build a single, aligned
   DataFrame."

  Sprint 2: Integration and Validation

  Prompt 2.1: Update the Main Pipeline
  "We are on Sprint 2, Sub-task 2.1. Here is the content of run_phaseA_pipeline.py. Modify it to use the new create_training_dataset function from
  extensions/intraday_ml/data_prep.py. Remove the old, separate steps for feature and label generation. The script should now have a single step for data
   preparation."

  Prompt 2.2: End-to-End Validation Run
  "Now for Sprint 2, Sub-task 2.3. I am going to execute the modified run_phaseA_pipeline.py.

  (You run the script and paste the full output, including any errors or tracebacks)

  Based on the output above, analyze the results. If there are errors, debug and provide the necessary code corrections. If it is successful, confirm
  that the training metrics are reasonable and that the process is complete."

  Prompt 2.3: Final Code Review and Cleanup
  "The pipeline is now functional. Your final task is to perform a code review and cleanup based on the checklist in 20251029_ML-logic-fix.md.

  Generate the necessary changes to:
   1. Ensure all new functions have clear docstrings.
   2. Add comments where the logic is complex.
   3. Verify that all old, incorrect code paths have been removed.
   4. Update the README.md in extensions/intraday_ml/ to explain the new data preparation workflow."

  By following this rigorous, step-by-step prompt-and-verify process, you are not just asking the model to write code; you are forcing it to comply with
  a pre-approved engineering plan, leading to a robust and functional system.
