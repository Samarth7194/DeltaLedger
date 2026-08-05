# Model Card

## Purpose

DeltaLedger AI uses models for retrieval, classification, structured extraction, explanation, and report drafting. Models support evidence-grounded analysis; they do not provide investment advice or authoritative financial calculations.

## Planned Model Roles

- Embeddings: BGE-M3 or another strong open embedding model.
- Reranking: cross-encoder or BGE reranker.
- Financial language classification: FinBERT.
- Risk categorization: zero-shot classifier for initial risk routing.
- LLM provider interface: at least one hosted LLM and one Hugging Face/local option.

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

