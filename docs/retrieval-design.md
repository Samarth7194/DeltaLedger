# Retrieval Design

## Goals

Retrieval must return source-aware filing passages that can be inspected, cited, and validated. It is not enough to retrieve semantically similar text; results must preserve filing, reporting period, section hierarchy, source anchors, chunk offsets, parser version, and embedding model version.

## Chunking Strategy

SEC filings are chunked with section awareness:

- Filing section boundaries.
- Headings and subheadings.
- Paragraph boundaries.
- Table boundaries where practical.
- Maximum token limits.
- Controlled overlap.

Each chunk stores:

- Filing ID, company ID, reporting period, and section name.
- Section hierarchy and source anchor.
- Chunk index, text offsets, content hash, and parser version.

This is appropriate for financial filings because section meaning and source provenance are more important than arbitrary token windows.

Implemented chunk metadata includes part number, item number, canonical section type,
source anchor or DOM path, offsets, source text hash, content hash, parser version,
chunker version, embedding model/version, and embedded timestamp.

## Hybrid Retrieval

Retrieval pipeline:

1. Metadata filter by company, filing, form type, reporting period, and section category.
2. Dense embedding retrieval from PGVector.
3. Lexical/BM25-style retrieval.
4. Reciprocal Rank Fusion for dense and lexical candidates.
5. Cross-encoder reranking.
6. Return source-aware results with retrieval traces.

Dense search uses cosine similarity through PGVector. The default configured embedding
dimension is 1024 for BGE-M3. The embedding service validates model output dimensions
and fails clearly instead of truncating or padding vectors.

Lexical search uses PostgreSQL `websearch_to_tsquery('english', query)` against a
generated `tsvector` column on `filing_chunks.text`, indexed with GIN.

Rank fusion uses Reciprocal Rank Fusion:

```text
fusion_score = sum(1 / (rank_constant + rank))
```

The default rank constant is 60. Dense and lexical candidates are deduplicated by
chunk ID before optional reranking.

Reranking uses a provider abstraction. Production can use a sentence-transformers
CrossEncoder; tests use a deterministic overlap-based fake. Reranking is limited by
`RERANKER_CANDIDATE_LIMIT` and can be disabled.

Embedding providers:

- `fake`: deterministic offline vectors for unit tests and ordinary local development.
- `huggingface_inference`: hosted Hugging Face Inference Provider using `HF_TOKEN`.
- `sentence_transformers`: optional local model provider for model smoke tests.

## Integration Evidence

Phase 2.5 adds marker-gated integration tests that execute dense and lexical
retrieval against PostgreSQL instead of mocks:

- `tests/test_postgres_retrieval_integration.py` inserts known 1024-dimension
  vectors and asserts PGVector cosine ordering, top-k limiting, thresholds, and
  metadata filters.
- The same file exercises PostgreSQL full-text search with
  `websearch_to_tsquery`, `ts_rank_cd`, stemming-oriented query terms, metadata
  filters, and an `EXPLAIN` check that the GIN index can be used.
- `tests/test_hybrid_retrieval_integration.py` stores real rows, runs dense
  retrieval, runs lexical retrieval, applies RRF, deduplicates candidate chunks,
  and reranks with a deterministic local reranker.
- `tests/test_api_postgres_integration.py` sends an HTTP request through
  `/api/v1/retrieval/search` while the route reads records from the real test
  database.

Run them with:

```bash
RUN_INTEGRATION_TESTS=1 RUN_POSTGRES_TESTS=1 python -m pytest -m "integration and postgres" -q
```

## API Example

```json
{
  "query": "customer concentration increased",
  "company_id": "00000000-0000-0000-0000-000000000001",
  "section_types": ["risk_factors", "mda"],
  "top_k": 10,
  "candidate_k": 40,
  "use_reranker": true
}
```

## Trace Data

For each retrieval request, track:

- Query text and normalized filters.
- Candidate IDs.
- Dense scores.
- Lexical scores.
- Fusion ranks.
- Reranker scores.
- Selected result IDs.
- Embedding and reranker model versions.
