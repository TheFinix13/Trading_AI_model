"""ML-driven candidate discovery + labeling. Sits between the rule engine and the backtester:

  enumerate_candidates -> label_candidates -> train -> score -> trade

Hand-rules become FEATURES, not gates. The model decides which patterns work."""
