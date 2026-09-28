# Model Card

## Purpose

DeltaLedger AI uses models for embeddings (section/passage matching and the standalone search API), disclosure-change classification, and structured financial-claim extraction. It does not use a model for contradiction detection, arithmetic, or report writing. Models support evidence-grounded analysis; they do not provide investment advice or authoritative financial calculations. No model is trained or fine-tuned in this project.

## Models In Use (verified against the code)

- Embeddings: `BAAI/bge-large-en-v1.5`, 1024 dimensions. The provider is selectable: local `sentence_transformers`, Hugging Face inference (`huggingface_inference`), an OpenAI-compatible endpoint, or a deterministic fake for CI. Stored on `filing_chunks.embedding`.
- Reranker (optional, off by default): `BAAI/bge-reranker-base` cross-encoder via `sentence_transformers`. Scores section-title pairs during section matching and re-orders results in the standalone search API.
- Generative model: any OpenAI-compatible chat endpoint (the author's configuration uses Gemini). Used for (1) disclosure-change classification and (2) financial-claim extraction, both with structured (Pydantic-validated) output, batching, and versioned prompts. A deterministic fake is used in CI.

## Not Implemented

- FinBERT or any other fine-tuned financial classifier.
- A zero-shot risk classifier (risk category comes from the change classifier and deterministic signals).
- BGE-M3 (an earlier plan; the code and database use `bge-large-en-v1.5`).
- LLM contradiction classification (an unused provider class was removed; contradictions come from rule-based detectors).
- LLM-written report prose (reports are assembled deterministically from stored findings).

## Evaluation Status

No real-model quality measurement is claimed here. Checked-in offline metrics use deterministic baselines on small author-written fixtures. See docs/evaluation-suite.md for the real-provider evaluation procedure and results.

## Guardrails

- Structured Pydantic outputs.
- Prompt and model version tracking.
- Deterministic arithmetic outside the LLM.
- Citation validation before publication.
- Abstention when evidence is insufficient.
- Human review for findings.

## Known Model Risks

- Narrative overinterpretation.
- Metric alias ambiguity.
- Period mismatch in financial claims.
- False contradiction flags.
- Unsupported report prose if citation validation is bypassed.

