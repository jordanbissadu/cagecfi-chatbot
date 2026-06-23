"""Dependencies for Supabase RAG Agent."""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any
import logging
import asyncpg
import openai
from src.settings_supabase import load_settings

logger = logging.getLogger(__name__)


@dataclass
class AgentDependencies:
    """Dependencies injected into the agent context for Supabase."""

    # Core dependencies
    pg_pool: Optional[asyncpg.Pool] = None
    openai_client: Optional[openai.AsyncOpenAI] = None
    settings: Optional[Any] = None

    # Session context
    session_id: Optional[str] = None
    user_preferences: Dict[str, Any] = field(default_factory=dict)
    query_history: list = field(default_factory=list)

    async def initialize(self) -> None:
        """
        Initialize external connections.

        Raises:
            asyncpg.PostgresError: If PostgreSQL connection fails
            ValueError: If settings cannot be loaded
        """
        if not self.settings:
            self.settings = load_settings()
            logger.info(
                f"settings_loaded: database_url={self.settings.database_url[:30]}..., "
                f"documents={self.settings.postgres_table_documents}, "
                f"chunks={self.settings.postgres_table_chunks}"
            )

        # Initialize PostgreSQL connection pool
        if not self.pg_pool:
            try:
                # statement_cache_size=0 is required for the Supabase pooler
                # (pgbouncer) which does not support prepared statements.
                self.pg_pool = await asyncpg.create_pool(
                    self.settings.database_url,
                    min_size=1,
                    max_size=10,
                    command_timeout=60,
                    statement_cache_size=0,
                )

                # Verify connection with a simple query
                async with self.pg_pool.acquire() as conn:
                    await conn.fetchval("SELECT 1")

                logger.info(
                    f"postgresql_connected: tables="
                    f"{self.settings.postgres_table_documents}/"
                    f"{self.settings.postgres_table_chunks}"
                )
            except asyncpg.PostgresError as e:
                logger.exception(f"postgresql_connection_failed: {e}")
                raise

        # Initialize OpenAI client for embeddings (using Ollama)
        if not self.openai_client:
            self.openai_client = openai.AsyncOpenAI(
                api_key=self.settings.embedding_api_key,
                base_url=self.settings.embedding_base_url,
            )
            logger.info(
                f"openai_client_initialized: model={self.settings.embedding_model}, "
                f"dimension={self.settings.embedding_dimension}, "
                f"provider={self.settings.embedding_provider}"
            )

    async def cleanup(self) -> None:
        """Clean up external connections."""
        if self.pg_pool:
            await self.pg_pool.close()
            self.pg_pool = None
            logger.info("postgresql_connection_closed")

    async def get_embedding(self, text: str) -> list[float]:
        """
        Generate embedding for text using OpenAI-compatible API (Ollama).

        Args:
            text: Text to embed

        Returns:
            Embedding vector as list of floats

        Raises:
            Exception: If embedding generation fails
        """
        if not self.openai_client:
            await self.initialize()

        response = await self.openai_client.embeddings.create(
            model=self.settings.embedding_model, input=text
        )
        # Return as list of floats - PostgreSQL pgvector uses this format
        return response.data[0].embedding

    async def execute_query(
        self, query: str, *args, fetch_mode: str = "all"
    ) -> Any:
        """
        Execute a SQL query with the connection pool.

        Args:
            query: SQL query string
            *args: Query parameters
            fetch_mode: "all", "one", "val", or "execute"

        Returns:
            Query results based on fetch_mode

        Raises:
            asyncpg.PostgresError: If query execution fails
        """
        if not self.pg_pool:
            await self.initialize()

        async with self.pg_pool.acquire() as conn:
            if fetch_mode == "all":
                return await conn.fetch(query, *args)
            elif fetch_mode == "one":
                return await conn.fetchrow(query, *args)
            elif fetch_mode == "val":
                return await conn.fetchval(query, *args)
            elif fetch_mode == "execute":
                return await conn.execute(query, *args)
            else:
                raise ValueError(f"Invalid fetch_mode: {fetch_mode}")

    def set_user_preference(self, key: str, value: Any) -> None:
        """
        Set a user preference for the session.

        Args:
            key: Preference key
            value: Preference value
        """
        self.user_preferences[key] = value

    def add_to_history(self, query: str) -> None:
        """
        Add a query to the search history.

        Args:
            query: Search query to add to history
        """
        self.query_history.append(query)
        # Keep only last 10 queries
        if len(self.query_history) > 10:
            self.query_history.pop(0)
