"""Model providers for Supabase RAG Agent."""

from typing import Optional
from pydantic_ai.providers.openai import OpenAIProvider

# pydantic-ai >= 1.x a renommé `OpenAIModel` en `OpenAIChatModel`. On supporte
# les deux pour être robuste à la version installée (local vs build Vercel).
try:
    from pydantic_ai.models.openai import OpenAIModel
except ImportError:  # pragma: no cover
    from pydantic_ai.models.openai import OpenAIChatModel as OpenAIModel

from src.settings_supabase import load_settings


def get_llm_model(model_choice: Optional[str] = None) -> OpenAIModel:
    """
    Get LLM model configuration based on environment variables.
    Supports any OpenAI-compatible API provider (Ollama, OpenRouter, etc.).

    Args:
        model_choice: Optional override for model choice

    Returns:
        Configured OpenAI-compatible model
    """
    settings = load_settings()

    llm_choice = model_choice or settings.llm_model
    base_url = settings.llm_base_url
    api_key = settings.llm_api_key

    # Create provider based on configuration
    provider = OpenAIProvider(base_url=base_url, api_key=api_key)

    return OpenAIModel(llm_choice, provider=provider)


def get_embedding_model() -> OpenAIModel:
    """
    Get embedding model configuration.
    Uses OpenAI embeddings API (or compatible provider like Ollama).

    Returns:
        Configured embedding model
    """
    settings = load_settings()

    # For embeddings, use the same provider configuration
    provider = OpenAIProvider(
        base_url=settings.llm_base_url, api_key=settings.llm_api_key
    )

    return OpenAIModel(settings.embedding_model, provider=provider)


def get_model_info() -> dict:
    """
    Get information about current model configuration.

    Returns:
        Dictionary with model configuration info
    """
    settings = load_settings()

    return {
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
        "llm_base_url": settings.llm_base_url,
        "embedding_model": settings.embedding_model,
    }


def validate_llm_configuration() -> bool:
    """
    Validate that LLM configuration is properly set.

    Returns:
        True if configuration is valid
    """
    try:
        # Check if we can create a model instance
        get_llm_model()
        return True
    except Exception as e:
        print(f"LLM configuration validation failed: {e}")
        return False
