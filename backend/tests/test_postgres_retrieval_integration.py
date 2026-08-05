from __future__ import annotations

import pytest
from sqlalchemy import text

from app.repositories.chunk_repository import ChunkRepository, RetrievalFilters
from tests.integration_helpers import create_retrieval_corpus, unit_vector

pytestmark = [pytest.mark.integration, pytest.mark.postgres]


@pytest.mark.asyncio
async def test_pgvector_cosine_ordering_filters_and_threshold(integration_session) -> None:
    corpus = await create_retrieval_corpus(integration_session)
    repo = ChunkRepository(integration_session)

    results = await repo.dense_search(
        query_embedding=unit_vector(0),
        filters=RetrievalFilters(company_id=corpus["company_id"]),
        top_k=3,
        min_similarity=0.5,
    )

    assert [result.chunk_id for result in results] == [corpus["customer_chunk_id"]]
    assert results[0].score > 0.99
    assert results[0].source_metadata["section_type"] == "risk_factors"


@pytest.mark.asyncio
async def test_pgvector_metadata_filters(integration_session) -> None:
    corpus = await create_retrieval_corpus(integration_session)
    repo = ChunkRepository(integration_session)

    by_filing = await repo.dense_search(
        query_embedding=unit_vector(3),
        filters=RetrievalFilters(filing_ids=[corpus["other_filing_id"]]),
        top_k=5,
    )
    by_section = await repo.dense_search(
        query_embedding=unit_vector(0),
        filters=RetrievalFilters(section_types=["mda"]),
        top_k=5,
    )

    assert [result.chunk_id for result in by_filing] == [corpus["revenue_chunk_id"]]
    assert corpus["customer_chunk_id"] not in [result.chunk_id for result in by_section]


@pytest.mark.asyncio
async def test_postgres_full_text_search_and_gin_index(integration_session) -> None:
    corpus = await create_retrieval_corpus(integration_session)
    repo = ChunkRepository(integration_session)

    results = await repo.lexical_search(
        query="customer concentrations increase",
        filters=RetrievalFilters(company_id=corpus["company_id"]),
        top_k=5,
    )

    assert results[0].chunk_id == corpus["customer_chunk_id"]
    assert "customer concentration" in results[0].text

    await integration_session.execute(text("SET enable_seqscan = off"))
    explain = await integration_session.execute(
        text(
            "EXPLAIN SELECT id FROM filing_chunks "
            "WHERE search_vector @@ websearch_to_tsquery('english', 'customer concentration')"
        )
    )
    plan = "\n".join(row[0] for row in explain)
    assert "ix_filing_chunks_search_vector_gin" in plan or "Bitmap Index Scan" in plan
