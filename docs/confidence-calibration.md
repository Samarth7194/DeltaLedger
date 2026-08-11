# Confidence Calibration

Phase 8 implements calibration utilities for tasks with confidence scores and
correctness labels.

Supported metrics:

- reliability buckets
- Expected Calibration Error
- Brier score for binary correctness labels

Calibration is only reported when prediction rows contain both:

- `confidence`
- `correct`

Small datasets should be interpreted cautiously. Calibration output includes
sample count and bucket counts so a high or low value is not overstated.

For current offline suites, Phase 3 change detection emits calibration from the
deterministic classifier confidence and curated change labels. Human-review
agreement calibration remains `no_data` until labelled review outcomes exist.
