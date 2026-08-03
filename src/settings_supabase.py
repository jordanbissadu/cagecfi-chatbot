"""Settings configuration for Supabase RAG Agent."""

from pydantic_settings import BaseSettings
from pydantic import Field, ConfigDict
from dotenv import load_dotenv
from typing import Optional

# Load environment variables from .env file
load_dotenv()


class SupabaseSettings(BaseSettings):
    """Application settings with environment variable support for Supabase."""

    model_config = ConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )

    # Supabase Configuration
    supabase_url: str = Field(..., description="Supabase project URL")

    supabase_anon_key: str = Field(..., description="Supabase anonymous key")

    supabase_service_role_key: str = Field(
        ..., description="Supabase service role key (for admin operations)"
    )

    database_url: str = Field(
        ..., description="PostgreSQL connection string from Supabase"
    )

    # PostgreSQL Tables
    postgres_table_documents: str = Field(
        default="documents", description="Table for source documents"
    )

    postgres_table_chunks: str = Field(
        default="chunks", description="Table for document chunks with embeddings"
    )

    # LLM Configuration (OpenAI-compatible) - GARDE OLLAMA
    llm_provider: str = Field(
        default="ollama",
        description="LLM provider (openai, anthropic, gemini, ollama, etc.)",
    )

    llm_api_key: str = Field(default="ollama", description="API key for the LLM provider")

    llm_model: str = Field(
        default="qwen2.5:7b-instruct-q4_K_M",
        description="Model to use for search and summarization (must support tool calling)",
    )

    llm_base_url: Optional[str] = Field(
        default="http://localhost:11434/v1",
        description="Base URL for the LLM API (for OpenAI-compatible providers)",
    )

    # LLM Generation Parameters (pour réduire les hallucinations)
    llm_temperature: float = Field(
        default=0.1,
        description="Temperature for LLM (0.0-1.0, lower = more deterministic, less hallucinations)",
    )

    llm_top_p: float = Field(
        default=0.9,
        description="Top-p sampling (nucleus sampling)",
    )

    llm_max_tokens: int = Field(
        default=1024,
        description="Maximum tokens in response",
    )

    # Embedding Configuration - GARDE OLLAMA
    embedding_provider: str = Field(default="ollama", description="Embedding provider")

    embedding_api_key: str = Field(default="ollama", description="API key for embedding provider")

    embedding_model: str = Field(
        default="nomic-embed-text:v1.5", description="Embedding model to use"
    )

    embedding_base_url: Optional[str] = Field(
        default="http://localhost:11434/v1", description="Base URL for embedding API"
    )

    embedding_dimension: int = Field(
        default=768,
        description="Embedding vector dimension (768 for nomic-embed-text, 1536 for OpenAI)",
    )

    # Search Configuration
    default_match_count: int = Field(
        default=10, description="Default number of search results to return"
    )

    max_match_count: int = Field(
        default=50, description="Maximum number of search results allowed"
    )

    default_text_weight: float = Field(
        default=0.3, description="Default text weight for hybrid search (0-1)"
    )

    # Mistral OCR (ingestion locale uniquement, jamais appele depuis Vercel)
    mistral_api_key: str = Field(
        default="", description="Cle API Mistral pour l'OCR des plaquettes"
    )

    mistral_ocr_model: str = Field(
        default="mistral-ocr-latest", description="Modele OCR Mistral"
    )


def load_settings() -> SupabaseSettings:
    """Load settings with proper error handling."""
    try:
        return SupabaseSettings()
    except Exception as e:
        error_msg = f"Failed to load settings: {e}"
        if "supabase_url" in str(e).lower():
            error_msg += "\nMake sure to set SUPABASE_URL in your .env file"
        if "database_url" in str(e).lower():
            error_msg += "\nMake sure to set DATABASE_URL in your .env file"
        if "llm_api_key" in str(e).lower():
            error_msg += "\nMake sure to set LLM_API_KEY in your .env file"
        if "embedding_api_key" in str(e).lower():
            error_msg += "\nMake sure to set EMBEDDING_API_KEY in your .env file"
        raise ValueError(error_msg) from e
