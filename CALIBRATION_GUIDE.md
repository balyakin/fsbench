# Calibration Guide

MVP calibration uses the included 15-task corpus (`T1 x 3`, `T2 x 5`, `T3 x 7`) and at least two real CLI agents when
credentials are available. Run each agent with several repeats, export reports, then compare `pass_at_1`, mean score,
duration, and cost. Do not use LLM-as-judge for calibration.
