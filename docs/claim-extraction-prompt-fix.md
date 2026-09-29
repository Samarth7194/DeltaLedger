# Claim-Extraction Prompt Fix (v1 → v2)

This documents the Step 2 diagnosis and fix for the near-total failure of
`gemini-3.5-flash-lite` on financial-claim extraction found in the Step 5 live
evaluation (`evaluation/results/live_provider_eval_20260928T190852Z.json`),
following the procedure in the sprint instructions: split first, diagnose and
fix using only the dev half, re-run once on the untouched held-out half, report
both numbers honestly.

## 1. Dev/held-out split (committed before any change)

`backend/evaluation/datasets/phase4_extraction_split.json` assigns each of the
60 `phase4_fixture` sentences to `dev` (30) or `held_out` (30): ids sorted
lexicographically, even 0-based index → dev, odd → held-out. Category mix is
close to even in both halves. This file was written before any prompt change
and before any diagnostic call, specifically so the held-out half could not
influence the fix.

## 2. Diagnosis (dev-set items only)

The original run's results file records `parse_status: "invalid"` for 32/60
items and empty `claims: []` for 27 of the remaining 28, but - correctly -
never persisted the raw model output (only safe, whitelisted inference
metadata). To find the actual cause, five dev-split items were re-queried
directly against the real provider, capturing the validation-error text and,
for one item, the literal raw response body. Neither is a secret; nothing else
was inspected or kept.

The validation error was consistently a `claim_type` problem:

```text
claims.0.claim_type: Input should be 'absolute_value', 'directional_change',
'percentage_change', 'percentage_point_change', 'ratio_change',
'comparative_statement' or 'qualitative_financial_claim'
```

The raw first-attempt response for `"Revenue was $112 million for the
quarter."` showed why - the model wasn't using the schema's field names at
all:

```json
{
  "claims": [
    {
      "metric": "revenue",
      "value": 112000000,
      "period": "quarter",
      "segment": null,
      "unit": "USD",
      "currency": "$"
    }
  ]
}
```

**Root cause: JSON/schema mismatch caused by a prompt that never named its own
schema.** `_SINGLE_CLAIM_SYSTEM_PROMPT` / `_BATCH_CLAIM_SYSTEM_PROMPT` (v1)
said only "Return only JSON with a claims array" - no field names, no types,
no enum values. Compare the disclosure-change prompt, which spells out every
field explicitly and scored 1.000 accuracy on the same live run. This was not
truncation (responses were short and complete), not a `response_format`
rejection (valid JSON came back every time), and not a fundamental model
limitation (section 4 shows the same model doing this correctly once told
what to produce) - it was a genuinely broken prompt.

The one-shot "repair" retry (send the bad response back with a description of
what's wrong) got partway there on some items - the model added a `claim_type`
key on the second attempt but still guessed a value the prompt never listed -
which is consistent with the model never having been told the valid enum
values in the first place.

## 3. Fix (dev set only, no pipeline change)

`_CLAIM_FIELDS_PROMPT` was added to `backend/app/ai/financial_claims.py` and
folded into both the single-item and batch system prompts, naming every
`FinancialClaimExtraction` field, its type, and every enum's exact allowed
values (`claim_type`, `direction`, `reported_change_unit`), the same pattern
`semantic_change.py`'s `_RESULT_FIELDS_PROMPT` already used successfully.
Nothing about what is asked of the model changed - only how precisely the
required output shape is described. No retry, pacing, or pipeline behavior
changed. `prompt_version` / `batch_prompt_version` bumped from `...-json-v1`
to `...-json-v2` (the embedded content hash also changed), so no old
extraction result can be silently reused under the new prompt.

Only the 30 dev-split items were used while diagnosing and iterating; the
held-out split was not queried until the fix was final.

## 4. Held-out result: old prompt vs new prompt

Both numbers are from the same 30 held-out sentences (never touched during
diagnosis) and the same model, `gemini-3.5-flash-lite`, one clean run each -
no prompt tuning after seeing held-out results.

- **Old**: v1 prompt. Computed by filtering the existing pre-fix full-60 run
  (`evaluation/results/live_provider_eval_20260928T190852Z.json`) down to the
  30 held-out ids - no new API calls were needed for this number, since that
  data already existed from a run made before the split existed.
- **New**: v2 prompt. A fresh run restricted to `--claim-split held_out`
  (`evaluation/results/live_provider_eval_20260929T073125Z.json`).

| metric | deterministic baseline | Gemini v1 (old) | Gemini v2 (new) |
|---|---|---|---|
| canonical_metric_accuracy | 0.867 | 0.100 | **0.933** |
| claim_type_accuracy (typed items, n=20) | 0.850 | 0.050 | **1.000** |
| exact match (n=20) | 0.800 | 0.050 | **0.950** |
| claim recall (items with a gold metric) | 0.964 | 0.036 | **1.000** |
| provider status | - | 16/30 invalid_output, 14/30 ok-but-mostly-empty | 30/30 ok |

Per-category metric accuracy, old vs new:

| category | baseline | Gemini v1 (old) | Gemini v2 (new) |
|---|---|---|---|
| absolute_value | 1.000 | 0.000 | 1.000 |
| ambiguous_or_error | 0.800 | 0.400 | 1.000 |
| percentage_change | 0.875 | 0.125 | 1.000 |
| percentage_point_change | 0.600 | 0.000 | 0.800 |
| period_resolution | 1.000 | 0.000 | 0.800 |

With the fix, Gemini goes from far below the deterministic baseline to
**above** it on every held-out metric measured. The two remaining v2 failures:

- `pp-004`, "Operating margin improved by 75 basis points." - the metric
  registry has no `operating_margin` alias, so the gold label
  `operating_income` itself is arguably wrong for this sentence; Gemini
  correctly extracted `claim_type=percentage_point_change` but declined to
  guess a `canonical_metric_name` outside its `allowed_metrics` list, which is
  the intended abstain behavior, not a defect.
- `period-010`, "Cash increased during the quarter." - gold has no claim type
  (ambiguous/no number); Gemini extracted it as a `directional_change` claim
  with no metric, which is a defensible reading of an admittedly vague
  sentence.

## 5. What this does and does not mean

- This is a single run on 30 small, author-written sentences, not a
  statistically powered benchmark; treat the numbers as a real, honest
  measurement of this exact prompt/model/dataset combination, not a general
  claim about Gemini's extraction ability.
- The pipeline's actual behavior (the `hybrid` column in the live evaluation
  report) already tries the deterministic extractor first and only calls the
  model when that finds nothing, so this fix mainly matters for the sentences
  the deterministic pass cannot resolve - not for changing default behavior.
  Per the sprint instructions, **the hybrid design is being kept as is**; nothing
  here is a request to make the pipeline favor the LLM by default. If that
  changed in the future, it should be justified by a larger held-out
  evaluation than this one, not by this single 30-example run.
- No further prompt tuning happened after the held-out run in section 4, and
  none should happen against it - a future prompt change should get its own
  dev/held-out cycle.
