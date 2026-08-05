# Contradiction Detection

## Product Role

Contradiction intelligence is the flagship feature. It detects potential inconsistencies between management narrative, prior-period narrative, reported XBRL facts, financial tables, and observed deterioration.

Contradiction flags are potential inconsistencies, not accusations.

## Initial Types

- Direction contradiction.
- Magnitude overstatement.
- Magnitude understatement.
- Narrative inconsistency.
- Period mismatch.
- Unsupported qualitative claim.

## Two-Stage Design

Stage 1: deterministic and rule-based candidate generation.

- Compare narrative direction with calculated XBRL direction.
- Compare qualitative magnitude words against measured movement.
- Compare current narrative with previous narrative.
- Require source passages and structured values before candidate creation.

Stage 2: LLM-assisted explanation and classification.

- Input is constrained to evidence-backed candidates.
- Output is structured and validated.
- The LLM cannot invent contradictions without evidence.

## Required Finding Fields

- Deterministic evidence.
- Current and previous source passages.
- Current and previous structured values.
- Calculation formula.
- Contradiction type.
- Severity.
- Confidence.
- Limitations.
- Human-review status.

