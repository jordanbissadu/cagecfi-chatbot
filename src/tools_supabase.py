"""Search tools for Supabase RAG Agent with PostgreSQL + pgvector."""

import asyncio
import json
import logging
from typing import Optional, List, Dict, Any
from pydantic_ai import RunContext
from pydantic import BaseModel, Field
import asyncpg

from src.dependencies_supabase import AgentDependencies

logger = logging.getLogger(__name__)


class SearchResult(BaseModel):
    """Model for search results from chunks table."""

    chunk_id: str = Field(..., description="PostgreSQL UUID of chunk as string")
    file_id: str = Field(..., description="File UUID shared across document parts")
    content: str = Field(..., description="Chunk text content")
    similarity: float = Field(..., description="Relevance score (0-1)")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Chunk metadata")
    document_title: str = Field(..., description="Title from document lookup")
    document_source: str = Field(..., description="Source from document lookup")


class DocumentSearchResult(BaseModel):
    """Model for search results from documents table."""

    document_id: str = Field(..., description="PostgreSQL UUID of document part")
    file_id: str = Field(..., description="File UUID shared across all parts")
    title: str = Field(..., description="Document title")
    source: str = Field(..., description="Document source path")
    content: str = Field(..., description="Document content (this part)")
    part_number: int = Field(..., description="Part number (1-indexed)")
    total_parts: int = Field(..., description="Total number of parts")
    similarity: float = Field(..., description="Relevance score")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Document metadata")


async def semantic_search(
    ctx: RunContext[AgentDependencies],
    query: str,
    match_count: Optional[int] = None
) -> List[SearchResult]:
    """
    Perform pure semantic search using pgvector cosine similarity.

    Args:
        ctx: Agent runtime context with dependencies
        query: Search query text
        match_count: Number of results to return (default: 10)

    Returns:
        List of search results ordered by similarity

    Raises:
        asyncpg.PostgresError: If PostgreSQL operation fails
    """
    try:
        # Validate query is not empty
        if not query or not query.strip():
            logger.warning("semantic_search called with empty query, returning empty results")
            return []

        deps = ctx.deps

        # Use default if not specified
        if match_count is None:
            match_count = deps.settings.default_match_count

        # Validate match count
        match_count = min(match_count, deps.settings.max_match_count)

        # Generate embedding for query
        query_embedding = await deps.get_embedding(query)

        # Convert embedding list to PostgreSQL vector format string
        # asyncpg doesn't auto-convert list to vector type
        embedding_str = '[' + ','.join(str(x) for x in query_embedding) + ']'

        # PostgreSQL query with pgvector cosine distance
        # <=> is the cosine distance operator (0 = identical, 2 = opposite)
        # We convert to similarity: 1 - (distance / 2) to get 0-1 range
        # Join with documents using file_id (get first part for title/source)
        sql = f"""
            SELECT
                c.id::text AS chunk_id,
                c.file_id::text,
                c.content,
                1 - (c.embedding <=> $1::vector) / 2 AS similarity,
                c.metadata,
                d.title AS document_title,
                d.source AS document_source
            FROM {deps.settings.postgres_table_chunks} c
            JOIN {deps.settings.postgres_table_documents} d ON c.file_id = d.file_id AND d.part_number = 1
            ORDER BY c.embedding <=> $1::vector
            LIMIT $2
        """

        # Execute query
        rows = await deps.execute_query(sql, embedding_str, match_count, fetch_mode="all")

        # Convert to SearchResult objects
        search_results = [
            SearchResult(
                chunk_id=row['chunk_id'],
                file_id=row['file_id'],
                content=row['content'],
                similarity=float(row['similarity']),
                metadata=json.loads(row['metadata']) if isinstance(row['metadata'], str) else (row['metadata'] or {}),
                document_title=row['document_title'],
                document_source=row['document_source']
            )
            for row in rows
        ]

        logger.info(
            f"semantic_search_completed: query={query}, results={len(search_results)}, match_count={match_count}"
        )

        return search_results

    except asyncpg.PostgresError as e:
        logger.error(f"semantic_search_failed: query={query}, error={str(e)}")
        # Return empty list on error (graceful degradation)
        return []
    except Exception as e:
        logger.exception(f"semantic_search_error: query={query}, error={str(e)}")
        return []


async def text_search(
    ctx: RunContext[AgentDependencies],
    query: str,
    match_count: Optional[int] = None
) -> List[SearchResult]:
    """
    Perform full-text search using PostgreSQL tsvector/tsquery with French config.

    Args:
        ctx: Agent runtime context with dependencies
        query: Search query text
        match_count: Number of results to return (default: 10)

    Returns:
        List of search results ordered by text relevance

    Raises:
        asyncpg.PostgresError: If PostgreSQL operation fails
    """
    try:
        # Validate query is not empty
        if not query or not query.strip():
            logger.warning("text_search called with empty query, returning empty results")
            return []

        deps = ctx.deps

        # Use default if not specified
        if match_count is None:
            match_count = deps.settings.default_match_count

        # Validate match count
        match_count = min(match_count, deps.settings.max_match_count)

        # Over-fetch for better RRF results (2x requested count)
        fetch_count = match_count * 2

        # PostgreSQL full-text search with French configuration
        # plainto_tsquery automatically handles stemming and stop words
        # Join with documents using file_id (get first part for title/source)
        sql = f"""
            SELECT
                c.id::text AS chunk_id,
                c.file_id::text,
                c.content,
                ts_rank(to_tsvector('french', c.content), plainto_tsquery('french', $1)) AS similarity,
                c.metadata,
                d.title AS document_title,
                d.source AS document_source
            FROM {deps.settings.postgres_table_chunks} c
            JOIN {deps.settings.postgres_table_documents} d ON c.file_id = d.file_id AND d.part_number = 1
            WHERE to_tsvector('french', c.content) @@ plainto_tsquery('french', $1)
            ORDER BY ts_rank(to_tsvector('french', c.content), plainto_tsquery('french', $1)) DESC
            LIMIT $2
        """

        # Execute query
        rows = await deps.execute_query(sql, query, fetch_count, fetch_mode="all")

        # Convert to SearchResult objects
        search_results = [
            SearchResult(
                chunk_id=row['chunk_id'],
                file_id=row['file_id'],
                content=row['content'],
                similarity=float(row['similarity']),
                metadata=json.loads(row['metadata']) if isinstance(row['metadata'], str) else (row['metadata'] or {}),
                document_title=row['document_title'],
                document_source=row['document_source']
            )
            for row in rows
        ]

        logger.info(
            f"text_search_completed: query={query}, results={len(search_results)}, match_count={match_count}"
        )

        return search_results

    except asyncpg.PostgresError as e:
        logger.error(f"text_search_failed: query={query}, error={str(e)}")
        # Return empty list on error (graceful degradation)
        return []
    except Exception as e:
        logger.exception(f"text_search_error: query={query}, error={str(e)}")
        return []


def reciprocal_rank_fusion(
    search_results_list: List[List[SearchResult]],
    k: int = 60
) -> List[SearchResult]:
    """
    Merge multiple ranked lists using Reciprocal Rank Fusion.

    RRF is a simple yet effective algorithm for combining results from different
    search methods. It works by scoring each document based on its rank position
    in each result list.

    Args:
        search_results_list: List of ranked result lists from different searches
        k: RRF constant (default: 60, standard in literature)

    Returns:
        Unified list of results sorted by combined RRF score

    Algorithm:
        For each document d appearing in result lists:
            RRF_score(d) = Σ(1 / (k + rank_i(d)))
        Where rank_i(d) is the position of document d in result list i.

    References:
        - Cormack et al. (2009): "Reciprocal Rank Fusion outperforms the best system"
        - Standard k=60 performs well across various datasets
    """
    # Build score dictionary by chunk_id
    rrf_scores: Dict[str, float] = {}
    chunk_map: Dict[str, SearchResult] = {}

    # Process each search result list
    for results in search_results_list:
        for rank, result in enumerate(results):
            chunk_id = result.chunk_id

            # Calculate RRF contribution: 1 / (k + rank)
            rrf_score = 1.0 / (k + rank)

            # Accumulate score (automatic deduplication)
            if chunk_id in rrf_scores:
                rrf_scores[chunk_id] += rrf_score
            else:
                rrf_scores[chunk_id] = rrf_score
                chunk_map[chunk_id] = result

    # Sort by combined RRF score (descending)
    sorted_chunks = sorted(
        rrf_scores.items(),
        key=lambda x: x[1],
        reverse=True
    )

    # Build final result list with updated similarity scores
    merged_results = []
    for chunk_id, rrf_score in sorted_chunks:
        result = chunk_map[chunk_id]
        # Create new result with updated similarity (RRF score)
        merged_result = SearchResult(
            chunk_id=result.chunk_id,
            file_id=result.file_id,
            content=result.content,
            similarity=rrf_score,  # Combined RRF score
            metadata=result.metadata,
            document_title=result.document_title,
            document_source=result.document_source
        )
        merged_results.append(merged_result)

    logger.info(f"RRF merged {len(search_results_list)} result lists into {len(merged_results)} unique results")

    return merged_results


async def hybrid_search(
    ctx: RunContext[AgentDependencies],
    query: str,
    match_count: Optional[int] = None,
    text_weight: Optional[float] = None
) -> List[SearchResult]:
    """
    Perform hybrid search combining semantic and keyword matching.

    Uses manual Reciprocal Rank Fusion (RRF) to merge vector and text search results.

    Args:
        ctx: Agent runtime context with dependencies
        query: Search query text
        match_count: Number of results to return (default: 10)
        text_weight: Weight for text matching (0-1, not used with RRF)

    Returns:
        List of search results sorted by combined RRF score

    Algorithm:
        1. Run semantic search (pgvector cosine similarity)
        2. Run text search (PostgreSQL full-text search)
        3. Merge results using Reciprocal Rank Fusion
        4. Return top N results by combined score
    """
    try:
        # Validate query is not empty
        if not query or not query.strip():
            logger.warning("hybrid_search called with empty query, returning empty results")
            return []

        deps = ctx.deps

        # Use defaults if not specified
        if match_count is None:
            match_count = deps.settings.default_match_count

        # Validate match count
        match_count = min(match_count, deps.settings.max_match_count)

        # Over-fetch for better RRF results (2x requested count)
        fetch_count = match_count * 2

        logger.info(f"hybrid_search starting: query='{query}', match_count={match_count}")

        # Run both searches concurrently for performance
        semantic_results, text_results = await asyncio.gather(
            semantic_search(ctx, query, fetch_count),
            text_search(ctx, query, fetch_count),
            return_exceptions=True  # Don't fail if one search errors
        )

        # Handle errors gracefully
        if isinstance(semantic_results, Exception):
            logger.warning(f"Semantic search failed: {semantic_results}, using text results only")
            semantic_results = []
        if isinstance(text_results, Exception):
            logger.warning(f"Text search failed: {text_results}, using semantic results only")
            text_results = []

        # If both failed, return empty
        if not semantic_results and not text_results:
            logger.error("Both semantic and text search failed")
            return []

        # Merge results using Reciprocal Rank Fusion
        merged_results = reciprocal_rank_fusion(
            [semantic_results, text_results],
            k=60  # Standard RRF constant
        )

        # Return top N results
        final_results = merged_results[:match_count]

        logger.info(
            f"hybrid_search_completed: query='{query}', "
            f"semantic={len(semantic_results)}, text={len(text_results)}, "
            f"merged={len(merged_results)}, returned={len(final_results)}"
        )

        return final_results

    except Exception as e:
        logger.exception(f"hybrid_search_error: query={query}, error={str(e)}")
        # Graceful degradation: try semantic-only as last resort
        try:
            logger.info("Falling back to semantic search only")
            return await semantic_search(ctx, query, match_count)
        except:
            return []


async def document_search(
    ctx: RunContext[AgentDependencies],
    query: str,
    match_count: Optional[int] = None
) -> List[DocumentSearchResult]:
    """
    Perform full-text search in the documents table content.

    This searches directly in the documents table (not chunks),
    useful for finding information stored in document parts.

    Args:
        ctx: Agent runtime context with dependencies
        query: Search query text
        match_count: Number of results to return (default: 10)

    Returns:
        List of document search results ordered by relevance

    Raises:
        asyncpg.PostgresError: If PostgreSQL operation fails
    """
    try:
        # Validate query is not empty
        if not query or not query.strip():
            logger.warning("document_search called with empty query, returning empty results")
            return []

        deps = ctx.deps

        # Use default if not specified
        if match_count is None:
            match_count = deps.settings.default_match_count

        # Validate match count
        match_count = min(match_count, deps.settings.max_match_count)

        # PostgreSQL full-text search on documents.content with French configuration
        sql = f"""
            SELECT
                d.id::text AS document_id,
                d.file_id::text,
                d.title,
                d.source,
                d.content,
                d.part_number,
                d.total_parts,
                ts_rank(to_tsvector('french', d.content), plainto_tsquery('french', $1)) AS similarity,
                d.metadata
            FROM {deps.settings.postgres_table_documents} d
            WHERE to_tsvector('french', d.content) @@ plainto_tsquery('french', $1)
            ORDER BY ts_rank(to_tsvector('french', d.content), plainto_tsquery('french', $1)) DESC
            LIMIT $2
        """

        # Execute query
        rows = await deps.execute_query(sql, query, match_count, fetch_mode="all")

        # Convert to DocumentSearchResult objects
        search_results = [
            DocumentSearchResult(
                document_id=row['document_id'],
                file_id=row['file_id'],
                title=row['title'],
                source=row['source'],
                content=row['content'],
                part_number=row['part_number'],
                total_parts=row['total_parts'],
                similarity=float(row['similarity']),
                metadata=json.loads(row['metadata']) if isinstance(row['metadata'], str) else (row['metadata'] or {})
            )
            for row in rows
        ]

        logger.info(
            f"document_search_completed: query={query}, results={len(search_results)}"
        )

        return search_results

    except asyncpg.PostgresError as e:
        logger.error(f"document_search_failed: query={query}, error={str(e)}")
        return []
    except Exception as e:
        logger.exception(f"document_search_error: query={query}, error={str(e)}")
        return []


async def get_document_content(
    ctx: RunContext[AgentDependencies],
    file_id: str
) -> List[DocumentSearchResult]:
    """
    Retrieve all parts of a document by its file_id.

    Returns all document parts ordered by part_number,
    allowing reconstruction of the full document content.

    Args:
        ctx: Agent runtime context with dependencies
        file_id: UUID of the file (shared across all parts)

    Returns:
        List of document parts ordered by part_number

    Raises:
        asyncpg.PostgresError: If PostgreSQL operation fails
    """
    try:
        # Validate file_id is not empty
        if not file_id or not file_id.strip():
            logger.warning("get_document_content called with empty file_id")
            return []

        deps = ctx.deps

        # Get all parts of the document ordered by part_number
        sql = f"""
            SELECT
                d.id::text AS document_id,
                d.file_id::text,
                d.title,
                d.source,
                d.content,
                d.part_number,
                d.total_parts,
                1.0 AS similarity,
                d.metadata
            FROM {deps.settings.postgres_table_documents} d
            WHERE d.file_id = $1::uuid
            ORDER BY d.part_number ASC
        """

        # Execute query
        rows = await deps.execute_query(sql, file_id, fetch_mode="all")

        # Convert to DocumentSearchResult objects
        results = [
            DocumentSearchResult(
                document_id=row['document_id'],
                file_id=row['file_id'],
                title=row['title'],
                source=row['source'],
                content=row['content'],
                part_number=row['part_number'],
                total_parts=row['total_parts'],
                similarity=float(row['similarity']),
                metadata=json.loads(row['metadata']) if isinstance(row['metadata'], str) else (row['metadata'] or {})
            )
            for row in rows
        ]

        logger.info(
            f"get_document_content_completed: file_id={file_id}, parts={len(results)}"
        )

        return results

    except asyncpg.PostgresError as e:
        logger.error(f"get_document_content_failed: file_id={file_id}, error={str(e)}")
        return []
    except Exception as e:
        logger.exception(f"get_document_content_error: file_id={file_id}, error={str(e)}")
        return []


async def list_documents(
    ctx: RunContext[AgentDependencies],
    limit: Optional[int] = 50
) -> List[Dict[str, Any]]:
    """
    List all documents in the database (first part of each file only).

    Args:
        ctx: Agent runtime context with dependencies
        limit: Maximum number of documents to return (default: 50)

    Returns:
        List of document summaries with file_id, title, source, total_parts
    """
    try:
        deps = ctx.deps

        # Get first part of each document (contains metadata)
        sql = f"""
            SELECT
                d.file_id::text,
                d.title,
                d.source,
                d.total_parts,
                d.metadata,
                d.created_at
            FROM {deps.settings.postgres_table_documents} d
            WHERE d.part_number = 1
            ORDER BY d.created_at DESC
            LIMIT $1
        """

        rows = await deps.execute_query(sql, limit, fetch_mode="all")

        results = [
            {
                "file_id": row['file_id'],
                "title": row['title'],
                "source": row['source'],
                "total_parts": row['total_parts'],
                "metadata": json.loads(row['metadata']) if isinstance(row['metadata'], str) else (row['metadata'] or {}),
                "created_at": str(row['created_at'])
            }
            for row in rows
        ]

        logger.info(f"list_documents_completed: count={len(results)}")
        return results

    except Exception as e:
        logger.exception(f"list_documents_error: error={str(e)}")
        return []
