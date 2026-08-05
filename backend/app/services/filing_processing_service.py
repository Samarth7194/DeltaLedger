from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embeddings import EmbeddingService, create_embedding_service
from app.core.config import Settings
from app.core.exceptions import DeltaLedgerError
from app.integrations.storage import ObjectStorageClient
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.filing_repository import FilingRepository
from app.repositories.processing_repository import ProcessingRepository
from app.repositories.section_repository import SectionRepository
from app.services.chunking_service import ChunkingService
from app.services.document_parser_service import DocumentParserService, ParsedDocument


class FilingProcessingService:
    STAGES = ("load_document", "parse_document", "chunk_sections", "embed_chunks")

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        storage_client: ObjectStorageClient | None = None,
        parser: DocumentParserService | None = None,
        chunker: ChunkingService | None = None,
        embedding_service: EmbeddingService | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.storage_client = storage_client or ObjectStorageClient(settings)
        self.parser = parser or DocumentParserService(
            parser_version=settings.parser_version,
            table_extraction_version=settings.table_extraction_version,
        )
        self.chunker = chunker or ChunkingService(
            max_tokens=settings.chunk_max_tokens,
            overlap_tokens=settings.chunk_overlap_tokens,
            chunker_version=settings.chunker_version,
        )
        self.embedding_service = embedding_service or create_embedding_service(settings)
        self.filings = FilingRepository(session)
        self.sections = SectionRepository(session)
        self.chunks = ChunkRepository(session)
        self.processing = ProcessingRepository(session)

    async def process_filing(self, filing_id: uuid.UUID) -> dict[str, object]:
        lock_acquired = await self.processing.try_acquire_filing_lock(filing_id)
        if not lock_acquired:
            stages = await self.processing.list_stages(filing_id)
            return {
                "filing_id": str(filing_id),
                "status": "already_running",
                "stages": [
                    {"stage_name": stage.stage_name, "status": stage.status}
                    for stage in stages
                ],
            }
        try:
            return await self._process_filing_locked(filing_id)
        finally:
            await self.processing.release_filing_lock(filing_id)

    async def _process_filing_locked(self, filing_id: uuid.UUID) -> dict[str, object]:
        filing = await self.filings.get(filing_id)
        if filing is None:
            raise DeltaLedgerError(f"Filing not found: {filing_id}")
        if not filing.storage_key:
            raise DeltaLedgerError(f"Filing has no stored document: {filing_id}")

        document_bytes = await self._run_stage(
            filing_id,
            "load_document",
            lambda: self.storage_client.get_bytes(
                bucket=self.settings.minio_bucket_filings,
                key=filing.storage_key or "",
            ),
        )
        parsed = await self._run_stage(
            filing_id,
            "parse_document",
            lambda: self._parse_document(document_bytes),
        )
        section_by_order = await self.sections.replace_sections_and_tables(
            filing_id=filing.id,
            sections=parsed.sections,
            tables=parsed.tables,
        )
        chunks = await self._run_stage(
            filing_id,
            "chunk_sections",
            lambda: self._create_chunks(parsed, section_by_order),
        )
        await self._run_stage(
            filing_id,
            "embed_chunks",
            lambda: self._embed_chunks(chunks),
        )
        filing.ingestion_status = "processed"
        filing.parser_version = self.settings.parser_version
        filing.raw_metadata = {
            **filing.raw_metadata,
            "processing": {
                "parser_version": self.settings.parser_version,
                "chunker_version": self.settings.chunker_version,
                "embedding_model": self.embedding_service.model_name,
                "embedding_version": self.embedding_service.model_version,
                "section_count": len(parsed.sections),
                "table_count": len(parsed.tables),
                "chunk_count": len(chunks),
            },
        }
        await self.session.commit()
        return {
            "filing_id": str(filing.id),
            "status": filing.ingestion_status,
            "sections": len(parsed.sections),
            "tables": len(parsed.tables),
            "chunks": len(chunks),
        }

    async def _run_stage(
        self,
        filing_id: uuid.UUID,
        stage_name: str,
        operation: Callable[[], Awaitable[object]],
    ) -> object:
        started = await self.processing.start_stage(filing_id, stage_name)
        try:
            result = await operation()
            metrics = self._stage_metrics(result)
            await self.processing.complete_stage(filing_id, stage_name, started, metrics)
            await self.session.flush()
            return result
        except Exception as exc:
            await self.processing.fail_stage(filing_id, stage_name, started, exc)
            await self.session.commit()
            raise

    async def _parse_document(self, document_bytes: bytes) -> ParsedDocument:
        return self.parser.parse(document_bytes)

    async def _create_chunks(
        self,
        parsed: ParsedDocument,
        section_by_order: dict[int, object],
    ) -> list[object]:
        specs = self.chunker.chunk_sections(sections=parsed.sections, tables=parsed.tables)
        return await self.chunks.replace_chunks(section_by_order=section_by_order, chunks=specs)

    async def _embed_chunks(self, chunks: list[object]) -> list[object]:
        unchanged = [
            chunk
            for chunk in chunks
            if chunk.embedding is not None
            and chunk.embedding_model == self.embedding_service.model_name
            and chunk.embedding_version == self.embedding_service.model_version
        ]
        to_embed = [chunk for chunk in chunks if chunk not in unchanged]
        vectors = await self.embedding_service.embed_documents([chunk.text for chunk in to_embed])
        await self.chunks.update_embeddings(
            to_embed,
            vectors,
            model_name=self.embedding_service.model_name,
            model_version=self.embedding_service.model_version,
        )
        return chunks

    def _stage_metrics(self, result: object) -> dict[str, object]:
        if isinstance(result, ParsedDocument):
            return {"sections": len(result.sections), "tables": len(result.tables)}
        if isinstance(result, list):
            return {"count": len(result)}
        if isinstance(result, bytes):
            return {"bytes": len(result)}
        return {}
