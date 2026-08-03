"""
Main ingestion script for processing documents into Supabase (PostgreSQL + pgvector).

This adapts the MongoDB ingestion pipeline to use PostgreSQL with pgvector,
changing only the database layer while preserving all document processing logic.
"""

import os
import asyncio
import logging
import glob
import json
from io import BytesIO
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
import argparse
from dataclasses import dataclass
import uuid

import asyncpg
from dotenv import load_dotenv
import openai

from src.ingestion.chunker import ChunkingConfig, create_chunker, DocumentChunk
from src.settings_supabase import load_settings

# Load environment variables
load_dotenv()


def read_plaquette_markdown(path: Path) -> tuple[str, Dict[str, Any]]:
    """Lit un markdown de plaquette en separant son front-matter.

    Args:
        path: Chemin du fichier markdown.

    Returns:
        Tuple (contenu sans front-matter, metadonnees du front-matter).
        Les metadonnees sont vides si le fichier n'en porte pas.
    """
    import frontmatter

    post = frontmatter.loads(path.read_text(encoding="utf-8"))
    return post.content, dict(post.metadata)


logger = logging.getLogger(__name__)


@dataclass
class IngestionConfig:
    """Configuration for document ingestion."""
    chunk_size: int = 1000
    chunk_overlap: int = 200
    max_chunk_size: int = 2000
    max_tokens: int = 512


@dataclass
class IngestionResult:
    """Result of document ingestion."""
    file_id: str
    title: str
    document_parts: int
    chunks_created: int
    processing_time_ms: float
    errors: List[str]


class DocumentIngestionPipeline:
    """Pipeline for ingesting documents into Supabase (PostgreSQL + pgvector)."""

    def __init__(
        self,
        config: IngestionConfig,
        documents_folder: str = "documents",
        clean_before_ingest: bool = True
    ):
        """
        Initialize ingestion pipeline.

        Args:
            config: Ingestion configuration
            documents_folder: Folder containing documents
            clean_before_ingest: Whether to clean existing data before ingestion
        """
        self.config = config
        self.documents_folder = documents_folder
        self.clean_before_ingest = clean_before_ingest

        # Front-matter du markdown en cours de lecture, memorise par
        # _read_document et reutilise par _ingest_document (voir plus bas)
        # pour eviter de relire le meme fichier deux fois.
        self._current_front_matter: Dict[str, Any] = {}

        # Load settings
        self.settings = load_settings()

        # Initialize PostgreSQL connection pool
        self.pg_pool: Optional[asyncpg.Pool] = None

        # Initialize components
        self.chunker = create_chunker(
            ChunkingConfig(max_tokens=config.max_tokens)
        )

        # Initialize OpenAI client for embeddings (using Ollama)
        self.embedding_client = openai.AsyncOpenAI(
            api_key=self.settings.embedding_api_key,
            base_url=self.settings.embedding_base_url
        )
        self.embedding_model = self.settings.embedding_model

    async def connect(self) -> None:
        """Establish PostgreSQL connection pool."""
        if not self.pg_pool:
            try:
                self.pg_pool = await asyncpg.create_pool(
                    self.settings.database_url,
                    min_size=1,
                    max_size=10,
                    command_timeout=60,
                    statement_cache_size=0,  # required for Supabase pooler (pgbouncer)
                )
                logger.info("PostgreSQL connection pool created")

                # Verify connection
                async with self.pg_pool.acquire() as conn:
                    await conn.fetchval("SELECT 1")
                logger.info("PostgreSQL connection verified")

            except asyncpg.PostgresError as e:
                logger.exception(f"Failed to connect to PostgreSQL: {e}")
                raise

    async def disconnect(self) -> None:
        """Close PostgreSQL connection pool."""
        if self.pg_pool:
            await self.pg_pool.close()
            self.pg_pool = None
            logger.info("PostgreSQL connection pool closed")

    async def ingest_all_documents(self) -> List[IngestionResult]:
        """
        Ingest all documents from the documents folder.

        Returns:
            List of ingestion results for each document

        Raises:
            Exception: If ingestion fails
        """
        await self.connect()

        try:
            # Clean existing data if requested
            if self.clean_before_ingest:
                await self._clean_databases()

            # Find all supported document files
            files = self._find_documents()
            logger.info(f"Found {len(files)} documents to ingest")

            if not files:
                logger.warning(
                    f"No documents found in {self.documents_folder}. "
                    f"Supported formats: PDF, Word, PowerPoint, Excel, Markdown, Audio"
                )
                return []

            # Process documents
            results = []
            for file_path in files:
                try:
                    result = await self._ingest_document(file_path)
                    results.append(result)
                except Exception as e:
                    logger.exception(f"Failed to ingest {file_path}: {e}")
                    results.append(
                        IngestionResult(
                            file_id="",
                            title=os.path.basename(file_path),
                            document_parts=0,
                            chunks_created=0,
                            processing_time_ms=0,
                            errors=[str(e)],
                        )
                    )

            # Summary
            successful = sum(1 for r in results if not r.errors)
            total_chunks = sum(r.chunks_created for r in results)

            logger.info(
                f"Ingestion complete: {successful}/{len(results)} documents, "
                f"{total_chunks} chunks created"
            )

            return results

        finally:
            await self.disconnect()

    def _find_documents(self) -> List[str]:
        """
        Find all supported document files in the documents folder.

        Returns:
            List of file paths
        """
        patterns = [
            "*.md", "*.markdown",  # Markdown
            "*.pdf",  # PDF
            "*.docx", "*.doc",  # Word
            "*.pptx", "*.ppt",  # PowerPoint
            "*.xlsx", "*.xls",  # Excel
            "*.html", "*.htm",  # HTML
            "*.mp3", "*.wav", "*.m4a", "*.flac",  # Audio formats
        ]
        files = []

        for pattern in patterns:
            files.extend(
                glob.glob(
                    os.path.join(self.documents_folder, "**", pattern),
                    recursive=True
                )
            )

        return sorted(files)

    def _read_document(self, file_path: str) -> tuple[str, Optional[Any]]:
        """
        Read document content from file - supports multiple formats via Docling.

        Args:
            file_path: Path to the document file

        Returns:
            Tuple of (markdown_content, docling_document).
            docling_document is None when the format has no Docling
            converter (plain text), or when Docling conversion failed and
            the reader fell back to raw text.
        """
        file_ext = os.path.splitext(file_path)[1].lower()

        # Reinitialise a chaque lecture : seul le format markdown le
        # renseigne ci-dessous, ce qui permet a _ingest_document de
        # recuperer le front-matter sans relire le fichier une seconde fois.
        self._current_front_matter = {}

        # Audio formats - transcribe with Whisper ASR
        audio_formats = ['.mp3', '.wav', '.m4a', '.flac']
        if file_ext in audio_formats:
            return self._transcribe_audio(file_path)

        # Les plaquettes extraites portent un front-matter : le retirer avant
        # Docling (sinon les cles YAML seraient injectees dans le texte
        # indexe), puis convertir le contenu restant en memoire pour obtenir
        # un DoclingDocument et beneficier du HybridChunker (chunking
        # conscient de la hierarchie des titres) plutot que du fallback
        # par fenetre glissante.
        if file_ext in ('.md', '.markdown'):
            content, front_matter = read_plaquette_markdown(Path(file_path))
            self._current_front_matter = front_matter
            try:
                from docling.datamodel.base_models import DocumentStream
                from docling.document_converter import DocumentConverter

                stream = DocumentStream(
                    name=os.path.basename(file_path),
                    stream=BytesIO(content.encode("utf-8")),
                )
                result = DocumentConverter().convert(stream)
                return (content, result.document)
            except Exception as e:
                logger.error(
                    f"Failed to convert {file_path} with Docling: {e}"
                )
                return (content, None)

        # Docling-supported formats (convert to markdown)
        docling_formats = [
            '.pdf', '.docx', '.doc', '.pptx', '.ppt',
            '.xlsx', '.xls', '.html', '.htm',
        ]

        if file_ext in docling_formats:
            try:
                from docling.document_converter import DocumentConverter

                logger.info(
                    f"Converting {file_ext} file using Docling: "
                    f"{os.path.basename(file_path)}"
                )

                converter = DocumentConverter()
                result = converter.convert(file_path)

                # Export to markdown for consistent processing
                markdown_content = result.document.export_to_markdown()
                logger.info(
                    f"Successfully converted {os.path.basename(file_path)} "
                    f"to markdown"
                )

                # Return both markdown and DoclingDocument for HybridChunker
                return (markdown_content, result.document)

            except Exception as e:
                logger.error(f"Failed to convert {file_path} with Docling: {e}")
                # Fall back to raw text if Docling fails
                logger.warning(f"Falling back to raw text extraction for {file_path}")
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        return (f.read(), None)
                except Exception:
                    return (
                        f"[Error: Could not read file {os.path.basename(file_path)}]",
                        None
                    )

        # Text-based formats (read directly)
        else:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    return (f.read(), None)
            except UnicodeDecodeError:
                # Try with different encoding
                with open(file_path, 'r', encoding='latin-1') as f:
                    return (f.read(), None)

    def _transcribe_audio(self, file_path: str) -> tuple[str, Optional[Any]]:
        """
        Transcribe audio file using Whisper ASR via Docling.

        Args:
            file_path: Path to the audio file

        Returns:
            Tuple of (markdown_content, docling_document)
        """
        try:
            from pathlib import Path
            from docling.document_converter import (
                DocumentConverter,
                AudioFormatOption
            )
            from docling.datamodel.pipeline_options import AsrPipelineOptions
            from docling.datamodel import asr_model_specs
            from docling.datamodel.base_models import InputFormat
            from docling.pipeline.asr_pipeline import AsrPipeline

            audio_path = Path(file_path).resolve()
            logger.info(
                f"Transcribing audio file using Whisper Turbo: {audio_path.name}"
            )

            # Verify file exists
            if not audio_path.exists():
                raise FileNotFoundError(f"Audio file not found: {audio_path}")

            # Configure ASR pipeline with Whisper Turbo model
            pipeline_options = AsrPipelineOptions()
            pipeline_options.asr_options = asr_model_specs.WHISPER_TURBO

            converter = DocumentConverter(
                format_options={
                    InputFormat.AUDIO: AudioFormatOption(
                        pipeline_cls=AsrPipeline,
                        pipeline_options=pipeline_options,
                    )
                }
            )

            # Transcribe the audio file
            result = converter.convert(audio_path)

            # Export to markdown with timestamps
            markdown_content = result.document.export_to_markdown()
            logger.info(f"Successfully transcribed {os.path.basename(file_path)}")

            # Return both markdown and DoclingDocument for HybridChunker
            return (markdown_content, result.document)

        except Exception as e:
            logger.error(f"Failed to transcribe {file_path} with Whisper ASR: {e}")
            return (
                f"[Error: Could not transcribe audio file "
                f"{os.path.basename(file_path)}]",
                None
            )

    def _extract_title(self, content: str, file_path: str) -> str:
        """
        Extract title from document content or filename.

        Args:
            content: Document content
            file_path: Path to the document file

        Returns:
            Document title
        """
        # Try to find markdown title
        lines = content.split('\n')
        for line in lines[:10]:  # Check first 10 lines
            line = line.strip()
            if line.startswith('# '):
                return line[2:].strip()

        # Fallback to filename
        return os.path.splitext(os.path.basename(file_path))[0]

    def _extract_document_metadata(
        self,
        content: str,
        file_path: str,
        front_matter: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Extract metadata from document content.

        Args:
            content: Document content
            file_path: Path to the document file
            front_matter: Metadata read from the markdown front-matter, if any

        Returns:
            Document metadata dictionary
        """
        metadata: Dict[str, Any] = {
            "file_name": os.path.basename(file_path),
            "file_extension": os.path.splitext(file_path)[1],
            "file_size": os.path.getsize(file_path),
            "word_count": len(content.split()),
            "doc_type": "chunk",
        }
        if front_matter:
            for cle in (
                "source_file",
                "extraction",
                "image_ratio",
                "extracted_at",
                "doc_type",
                "product",
                "category",
            ):
                if cle in front_matter:
                    metadata[cle] = front_matter[cle]
        return metadata

    async def _ingest_document(self, file_path: str) -> IngestionResult:
        """
        Ingest a single document into PostgreSQL.

        Args:
            file_path: Path to the document file

        Returns:
            Ingestion result

        Raises:
            Exception: If ingestion fails
        """
        start_time = datetime.now()
        errors = []

        try:
            # Read document content
            content, docling_doc = self._read_document(file_path)

            # Le front-matter (provenance des plaquettes) a deja ete lu par
            # _read_document ; on le recupere depuis l'instance plutot que
            # de relire le fichier une seconde fois.
            front_matter = self._current_front_matter

            # Extract metadata
            title = self._extract_title(content, file_path)
            metadata = self._extract_document_metadata(content, file_path, front_matter)

            logger.info(f"Processing document: {title}")

            # Chunk document
            if docling_doc is not None:
                # Use HybridChunker with DoclingDocument
                chunks = await self.chunker.chunk_document(
                    content=content,
                    title=title,
                    source=file_path,
                    metadata=metadata,
                    docling_doc=docling_doc
                )
            else:
                # Fall back to text chunking (for non-Docling files)
                chunks = await self.chunker.chunk_document(
                    content=content,
                    title=title,
                    source=file_path,
                    metadata=metadata,
                    docling_doc=None  # Will use fallback chunking
                )

            logger.info(f"Created {len(chunks)} chunks")

            # Generate embeddings for chunks
            chunks_with_embeddings = await self._embed_chunks(chunks)

            # Calculate document parts count
            content_parts = self._split_content_into_parts(content, max_chars=2000)
            document_parts = len(content_parts)

            # Store in PostgreSQL
            file_id = await self._store_document_and_chunks(
                title=title,
                source=file_path,
                content=content,
                chunks=chunks_with_embeddings,
                metadata=metadata
            )

            # Calculate processing time
            processing_time = (datetime.now() - start_time).total_seconds() * 1000

            return IngestionResult(
                file_id=file_id,
                title=title,
                document_parts=document_parts,
                chunks_created=len(chunks_with_embeddings),
                processing_time_ms=processing_time,
                errors=errors
            )

        except Exception as e:
            logger.exception(f"Error ingesting {file_path}: {e}")
            errors.append(str(e))
            raise

    async def _embed_chunks(self, chunks: List[DocumentChunk]) -> List[DocumentChunk]:
        """
        Generate embeddings for document chunks.

        Args:
            chunks: List of document chunks

        Returns:
            Chunks with embeddings added
        """
        if not chunks:
            return chunks

        logger.info(f"Generating embeddings for {len(chunks)} chunks")

        # Process chunks in batches of 100
        batch_size = 100
        embedded_chunks = []

        for i in range(0, len(chunks), batch_size):
            batch_chunks = chunks[i:i + batch_size]
            batch_texts = [chunk.content for chunk in batch_chunks]

            # Generate embeddings for this batch
            response = await self.embedding_client.embeddings.create(
                model=self.embedding_model,
                input=batch_texts
            )

            embeddings = [data.embedding for data in response.data]

            # Add embeddings to chunks
            for chunk, embedding in zip(batch_chunks, embeddings):
                embedded_chunk = DocumentChunk(
                    content=chunk.content,
                    index=chunk.index,
                    start_char=chunk.start_char,
                    end_char=chunk.end_char,
                    metadata={
                        **chunk.metadata,
                        "embedding_model": self.embedding_model,
                        "embedding_generated_at": datetime.now().isoformat()
                    },
                    token_count=chunk.token_count
                )
                embedded_chunk.embedding = embedding
                embedded_chunks.append(embedded_chunk)

            current_batch = (i // batch_size) + 1
            total_batches = (len(chunks) + batch_size - 1) // batch_size
            logger.info(f"Processed batch {current_batch}/{total_batches}")

        logger.info(f"Generated embeddings for {len(embedded_chunks)} chunks")
        return embedded_chunks

    def _split_content_into_parts(
        self,
        content: str,
        max_chars: int = 2000
    ) -> List[str]:
        """
        Split content into parts of maximum max_chars characters.

        Args:
            content: Full document content
            max_chars: Maximum characters per part (default: 2000)

        Returns:
            List of content parts
        """
        if len(content) <= max_chars:
            return [content]

        parts = []
        start = 0
        while start < len(content):
            end = start + max_chars

            # Try to break at a natural boundary (newline, period, space)
            if end < len(content):
                # Look for newline first
                newline_pos = content.rfind('\n', start, end)
                if newline_pos > start + max_chars // 2:
                    end = newline_pos + 1
                else:
                    # Look for period
                    period_pos = content.rfind('. ', start, end)
                    if period_pos > start + max_chars // 2:
                        end = period_pos + 2
                    else:
                        # Look for space
                        space_pos = content.rfind(' ', start, end)
                        if space_pos > start + max_chars // 2:
                            end = space_pos + 1

            parts.append(content[start:end])
            start = end

        return parts

    async def _store_document_and_chunks(
        self,
        title: str,
        source: str,
        content: str,
        chunks: List[DocumentChunk],
        metadata: Dict[str, Any]
    ) -> str:
        """
        Store document and chunks in PostgreSQL.

        The document content is split into multiple rows (max 2000 chars each).

        Args:
            title: Document title
            source: Document source path
            content: Document content
            chunks: List of document chunks with embeddings
            metadata: Document metadata

        Returns:
            File ID (UUID as string) - shared across all document parts

        Raises:
            asyncpg.PostgresError: If PostgreSQL operations fail
        """
        # Generate a unique file_id for this document
        file_id = uuid.uuid4()

        # Split content into parts of max 2000 characters
        content_parts = self._split_content_into_parts(content, max_chars=2000)
        total_parts = len(content_parts)

        async with self.pg_pool.acquire() as conn:
            # Start transaction
            async with conn.transaction():
                # Insert document parts
                for part_number, part_content in enumerate(content_parts, start=1):
                    await conn.execute(
                        f"""
                        INSERT INTO {self.settings.postgres_table_documents}
                            (title, source, content, part_number, total_parts, file_id, metadata, created_at)
                        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8)
                        """,
                        title,
                        source,
                        part_content,
                        part_number,
                        total_parts,
                        file_id,
                        json.dumps(metadata),
                        datetime.now()
                    )

                logger.info(
                    f"Inserted document '{title}' in {total_parts} parts (file_id: {file_id})"
                )

                # Insert chunks with embeddings (reference file_id)
                for chunk in chunks:
                    # Convert embedding list to PostgreSQL vector format string
                    # asyncpg doesn't auto-convert list to vector type
                    embedding_str = '[' + ','.join(str(x) for x in chunk.embedding) + ']'

                    await conn.execute(
                        f"""
                        INSERT INTO {self.settings.postgres_table_chunks}
                            (file_id, content, embedding, token_count, metadata, created_at)
                        VALUES ($1, $2, $3::vector, $4, $5::jsonb, $6)
                        """,
                        file_id,
                        chunk.content,
                        embedding_str,  # Formatted as string for PostgreSQL
                        chunk.token_count,
                        json.dumps(chunk.metadata),  # Convert metadata to JSON string
                        datetime.now()
                    )

                logger.info(f"Inserted {len(chunks)} chunks")

                return str(file_id)

    async def _clean_databases(self) -> None:
        """Clean existing data from PostgreSQL tables."""
        logger.warning("Cleaning existing data from PostgreSQL...")

        async with self.pg_pool.acquire() as conn:
            # Count before deleting
            chunks_count = await conn.fetchval(
                f"SELECT COUNT(*) FROM {self.settings.postgres_table_chunks}"
            )
            docs_count = await conn.fetchval(
                f"SELECT COUNT(*) FROM {self.settings.postgres_table_documents}"
            )

            # Delete chunks first (foreign key constraint)
            await conn.execute(
                f"DELETE FROM {self.settings.postgres_table_chunks}"
            )
            logger.info(f"Deleted {chunks_count} chunks")

            # Delete documents
            await conn.execute(
                f"DELETE FROM {self.settings.postgres_table_documents}"
            )
            logger.info(f"Deleted {docs_count} documents")


async def main():
    """Main entry point for CLI."""
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    # Parse arguments
    parser = argparse.ArgumentParser(
        description="Ingest documents into Supabase (PostgreSQL + pgvector)"
    )
    parser.add_argument(
        "-d",
        "--documents-folder",
        default="documents",
        help="Folder containing documents to ingest (default: documents)",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=1000,
        help="Maximum chunk size in characters (default: 1000)",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=512,
        help="Maximum tokens per chunk (default: 512)",
    )
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="Do not clean existing data before ingestion",
    )

    args = parser.parse_args()

    # Create config
    config = IngestionConfig(
        chunk_size=args.chunk_size,
        max_tokens=args.max_tokens
    )

    # Create and run pipeline
    pipeline = DocumentIngestionPipeline(
        config=config,
        documents_folder=args.documents_folder,
        clean_before_ingest=not args.no_clean
    )

    try:
        results = await pipeline.ingest_all_documents()

        # Display results
        print("\n" + "=" * 60)
        print("INGESTION SUMMARY")
        print("=" * 60)

        for result in results:
            status = "✅ SUCCESS" if not result.errors else "❌ FAILED"
            print(f"\n{status}: {result.title}")
            print(f"  File ID: {result.file_id}")
            print(f"  Document parts: {result.document_parts} (max 2000 chars each)")
            print(f"  Chunks: {result.chunks_created}")
            print(f"  Time: {result.processing_time_ms:.2f}ms")

            if result.errors:
                print("  Errors:")
                for error in result.errors:
                    print(f"    - {error}")

        # Overall stats
        successful = sum(1 for r in results if not r.errors)
        total_chunks = sum(r.chunks_created for r in results)
        total_parts = sum(r.document_parts for r in results)

        print("\n" + "=" * 60)
        print(f"Total: {successful}/{len(results)} documents")
        print(f"Total document parts: {total_parts}")
        print(f"Total chunks: {total_chunks}")
        print("=" * 60 + "\n")

    except Exception as e:
        logger.exception(f"Ingestion failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
