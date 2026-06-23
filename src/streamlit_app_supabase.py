#!/usr/bin/env python3
"""Streamlit web interface for Supabase Agent Service Clientèle with real-time streaming."""

import asyncio
import streamlit as st
from typing import List

from pydantic_ai import Agent
from pydantic_ai.messages import PartDeltaEvent, PartStartEvent, TextPartDelta
from pydantic_ai.ag_ui import StateDeps
from dotenv import load_dotenv

# Import our Supabase agent and dependencies
from src.agent_supabase import rag_agent, RAGState
from src.settings_supabase import load_settings

# Load environment variables
load_dotenv(override=True)

# Page configuration
st.set_page_config(
    page_title="Agent Service Clientèle (Supabase)",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better chat UX
st.markdown("""
<style>
    .stChatMessage {
        padding: 1rem;
        border-radius: 0.5rem;
    }
    .stChatInputContainer {
        padding: 1rem 0;
    }
</style>
""", unsafe_allow_html=True)


def clean_response_text(text: str) -> str:
    """
    Clean response text by removing technical prefixes and artifacts.

    Args:
        text: Raw response text from the LLM

    Returns:
        Cleaned response text without technical prefixes
    """
    import re

    cleaned = text.strip()

    # Remove model artifacts and special tokens
    artifacts_to_remove = [
        "-prepend_search-",
        "-prepend-search-",
        "prepend_search:",
        "[prepend_search]",
        "<|im_start|>",
        "<|im_end|>",
        "<tool_response>",
        "</tool_response>",
        "<|im_start|>user",
        "<|im_start|>assistant",
    ]

    for artifact in artifacts_to_remove:
        cleaned = cleaned.replace(artifact, "")

    # Remove leading Cyrillic or other non-Latin garbage before actual content
    cleaned = re.sub(r'^[^\w\sÀ-ÿ]+', '', cleaned, flags=re.UNICODE)

    # Remove "Found X relevant documents:" if it appears at the start
    cleaned = re.sub(r'^Found \d+ relevant documents?:?\s*', '', cleaned, flags=re.IGNORECASE)

    # Remove document markers like "--- Document X: ..."
    cleaned = re.sub(r'---\s*Document\s+\d+:.*?---', '', cleaned, flags=re.DOTALL)

    # Remove tool call artifacts (JSON/dict representations of function calls)
    # Pattern 1: Complete JSON - { "name": "search_knowledge_base", "parameters": {...} }
    cleaned = re.sub(r'\{\s*[\'"]name[\'"]\s*:\s*[\'"]search_knowledge_base[\'"]\s*,\s*[\'"]parameters[\'"]\s*:\s*\{[^}]+\}\s*\}["\']?', '', cleaned, flags=re.IGNORECASE)

    # Pattern 2: Partial JSON (missing opening brace) - name": "search_knowledge_base", "parameters": {...}}
    cleaned = re.sub(r'[\'"]?name[\'"]?\s*:\s*[\'"]search_knowledge_base[\'"]\s*,\s*[\'"]?parameters[\'"]?\s*:\s*\{[^}]+\}\s*\}+["\']?', '', cleaned, flags=re.IGNORECASE)

    # Pattern 3: Generic partial tool call patterns with any function name
    cleaned = re.sub(r'[\'"]?name[\'"]?\s*:\s*[\'"][^\'\"]+[\'"]\s*,\s*[\'"]?parameters[\'"]?\s*:\s*\{[^}]+\}\s*\}+', '', cleaned, flags=re.IGNORECASE)

    # Remove standalone function call patterns like "search_knowledge_base(...)"
    cleaned = re.sub(r'search_knowledge_base\s*\([^)]*\)', '', cleaned, flags=re.IGNORECASE)

    # Remove JSON-like tool call patterns more broadly
    cleaned = re.sub(r'\{\s*[\'"]?name[\'"]?\s*:\s*[\'"][^\'\"]+[\'"],\s*[\'"]?parameters[\'"]?\s*:\s*\{[^}]*\}\s*\}', '', cleaned)

    # Clean up excessive whitespace
    cleaned = re.sub(r'\n\s*\n\s*\n+', '\n\n', cleaned)
    cleaned = cleaned.strip()

    return cleaned


def initialize_session_state() -> None:
    """
    Initialize all session state variables.

    Session state persists across Streamlit reruns, maintaining conversation
    history and agent state.
    """
    if "messages" not in st.session_state:
        st.session_state.messages = []

    if "message_history" not in st.session_state:
        st.session_state.message_history = []

    if "state" not in st.session_state:
        st.session_state.state = RAGState()

    if "deps" not in st.session_state:
        st.session_state.deps = StateDeps[RAGState](
            state=st.session_state.state
        )

    if "tool_calls" not in st.session_state:
        st.session_state.tool_calls = []

    if "total_searches" not in st.session_state:
        st.session_state.total_searches = 0


def render_sidebar() -> None:
    """Render sidebar with configuration and statistics."""
    with st.sidebar:
        st.title("🔍 Agent Service Clientèle")
        st.caption("Powered by Supabase + pgvector")
        st.divider()

        # System Configuration
        st.subheader("⚙️ Configuration")
        settings = load_settings()

        # LLM info with local indicator
        llm_label = "🟢 Ollama (Local)" if settings.llm_provider.lower() == "ollama" else settings.llm_provider
        st.text(f"LLM: {llm_label}")
        st.caption(settings.llm_model)

        # Embedding info
        embed_label = "🟢 Ollama (Local)" if settings.embedding_provider.lower() == "ollama" else settings.embedding_provider
        st.text(f"Embeddings: {embed_label}")
        st.caption(f"{settings.embedding_model} ({settings.embedding_dimension}D)")

        # Database info
        st.text("Database: Supabase (PostgreSQL)")
        st.caption(f"Tables: {settings.postgres_table_documents}, {settings.postgres_table_chunks}")

        st.divider()

        # Session Statistics
        st.subheader("📊 Statistiques")
        st.metric("Messages", len(st.session_state.messages))
        st.metric("Recherches", st.session_state.total_searches)

        st.divider()

        # Recent Tool Calls
        if st.session_state.tool_calls:
            st.subheader("🔧 Recherches Récentes")
            for tool_call in st.session_state.tool_calls[-3:]:  # Last 3
                with st.expander(f"{tool_call['search_type']}"):
                    st.text(f"Query: {tool_call['query']}")
                    if 'match_count' in tool_call:
                        st.text(f"Résultats: {tool_call['match_count']}")

        # Clear chat button
        if st.button("🗑️ Nouvelle Discussion", use_container_width=True):
            st.session_state.messages = []
            st.session_state.message_history = []
            st.session_state.tool_calls = []
            st.session_state.total_searches = 0
            st.rerun()


async def stream_agent_response(user_input: str) -> str:
    """
    Stream agent response with real-time tool call detection.

    This function handles the complete agent interaction lifecycle:
    1. Streams response text character-by-character
    2. Detects and displays tool calls inline
    3. Updates session state with tool call history
    4. Maintains Pydantic AI message history for context

    Adapted from src/cli.py:_stream_agent() for Streamlit.
    Key differences:
    - console.print() → placeholder.markdown()
    - Separate tool indicator with st.empty()
    - Returns complete text for history

    Args:
        user_input: User's message text to send to agent

    Returns:
        Complete assistant response text after streaming

    Raises:
        Exception: If agent execution fails (displayed to user)
    """
    response_text = ""
    response_placeholder = st.empty()
    tool_indicator = st.empty()

    try:
        async with rag_agent.iter(
            user_input,
            deps=st.session_state.deps,
            message_history=st.session_state.message_history
        ) as run:

            async for node in run:

                # Handle tool calls
                if Agent.is_call_tools_node(node):
                    async with node.stream(run.ctx) as tool_stream:
                        async for event in tool_stream:
                            event_type = type(event).__name__

                            if event_type == "FunctionToolCallEvent":
                                tool_name = "Unknown"
                                args = {}

                                if hasattr(event, 'part'):
                                    part = event.part
                                    if hasattr(part, 'tool_name'):
                                        tool_name = part.tool_name
                                    if hasattr(part, 'args'):
                                        args = part.args

                                # Ensure args is a dict (handle cases where it might be a string)
                                if not isinstance(args, dict):
                                    args = {}

                                if tool_name == "search_knowledge_base":
                                    search_type = args.get('search_type', 'hybrid')
                                    query = args.get('query', '')

                                    # Display search indicator
                                    tool_indicator.info(
                                        f"🔍 Recherche en cours ({search_type})...\\n\\n"
                                        f"**Query:** {query}"
                                    )

                                    # Save to history
                                    st.session_state.tool_calls.append({
                                        "tool": tool_name,
                                        "query": query,
                                        "search_type": search_type,
                                        "match_count": args.get('match_count', 5)
                                    })
                                    st.session_state.total_searches += 1

                            elif event_type == "FunctionToolResultEvent":
                                tool_indicator.success("✅ Recherche terminée")

                # Handle text streaming
                elif Agent.is_model_request_node(node):
                    # Clear tool indicator once response starts
                    tool_indicator.empty()

                    async with node.stream(run.ctx) as request_stream:
                        async for event in request_stream:
                            # Initial text
                            if isinstance(event, PartStartEvent) and event.part.part_kind == 'text':
                                initial_text = event.part.content
                                if initial_text:
                                    response_text += initial_text
                                    response_placeholder.markdown(response_text + "▌")

                            # Text deltas (character-by-character streaming)
                            elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
                                delta_text = event.delta.content_delta
                                if delta_text:
                                    response_text += delta_text
                                    response_placeholder.markdown(response_text + "▌")

            # Get new messages for history
            new_messages = run.result.new_messages()
            st.session_state.message_history.extend(new_messages)

        # Clear cursor, clean and show final text
        cleaned_text = clean_response_text(response_text)
        response_placeholder.markdown(cleaned_text)
        return cleaned_text

    except Exception as e:
        st.error(
            f"❌ Erreur de l'agent:\\n\\n"
            f"**Erreur:** {str(e)}\\n\\n"
            f"**Vérifiez:**\\n"
            f"- Ollama est en cours d'exécution (lancez `ollama serve`)\\n"
            f"- Le modèle est téléchargé (`ollama pull llama3.2:3b`)\\n"
            f"- Supabase est accessible\\n"
            f"- DATABASE_URL est correct dans .env"
        )
        return "Une erreur s'est produite. Consultez le message ci-dessus."


def main() -> None:
    """Main Streamlit application."""

    # Initialize session state
    initialize_session_state()

    # Render sidebar
    render_sidebar()

    # Main title
    st.title("🔍 Agent Service Clientèle")
    st.caption("Recherche intelligente dans votre base de connaissances (Supabase + pgvector)")

    # Display chat history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Chat input
    if prompt := st.chat_input("Posez votre question..."):
        # Add user message
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Get assistant response
        with st.chat_message("assistant"):
            # asyncio.run() because Streamlit is synchronous
            response = asyncio.run(stream_agent_response(prompt))

        # Add to display history
        st.session_state.messages.append({
            "role": "assistant",
            "content": response
        })


if __name__ == "__main__":
    main()
