"""Main Supabase RAG agent implementation with shared state."""

from pydantic_ai import Agent, RunContext
from pydantic import BaseModel
from typing import Optional

from pydantic_ai.ag_ui import StateDeps

from src.providers_supabase import get_llm_model
from src.dependencies_supabase import AgentDependencies
from src.prompts import MAIN_SYSTEM_PROMPT
from src.settings_supabase import load_settings
from src.tools_supabase import (
    semantic_search,
    hybrid_search,
    text_search,
    document_search,
    get_document_content,
    list_documents
)


class RAGState(BaseModel):
    """Minimal shared state for the RAG agent."""
    pass


# Load settings for model parameters
_settings = load_settings()

# Create the RAG agent with AGUI support
# model_settings passed to reduce hallucinations (temperature, top_p)
rag_agent = Agent(
    get_llm_model(),
    deps_type=StateDeps[RAGState],
    system_prompt=MAIN_SYSTEM_PROMPT,
    model_settings={
        "temperature": _settings.llm_temperature,  # 0.1 = très déterministe
        "top_p": _settings.llm_top_p,
        "max_tokens": _settings.llm_max_tokens,
    }
)


@rag_agent.tool
async def search_knowledge_base(
    ctx: RunContext[StateDeps[RAGState]],
    query: str,
    match_count: Optional[int] = 8,
    search_type: Optional[str] = "hybrid"
) -> str:
    """
    Rechercher dans la base de connaissances de CAGECFI (services, produits, contacts, FAQ).

    ⚠️ NE JAMAIS UTILISER CET OUTIL POUR:
    - "Bonjour", "Bonsoir", "Salut", "Hello" (salutations)
    - "Merci", "D'accord", "OK" (remerciements)
    - "Au revoir", "Bye", "À bientôt" (au revoir)
    → Pour ces messages, répondre DIRECTEMENT sans appeler cet outil.

    ✅ UTILISER CET OUTIL POUR toute question sur CAGECFI:
    - L'entreprise (présentation, mission, pays, certification)
    - Les produits (Perfect-Vision, finance digitale, solutions étatiques, SYCEBNL-ERP)
    - Contact, devis, démonstration, formation, recrutement, support

    Args:
        ctx: Contexte d'exécution de l'agent avec dépendances d'état
        query: La question COMPLÈTE de l'utilisateur, telle quelle (ne pas réduire à des mots-clés).
        match_count: Nombre de résultats à retourner (défaut: 8, max: 50)
        search_type: Type de recherche - "hybrid" (défaut), "semantic", ou "text"

    Returns:
        Information pertinente extraite de la base de connaissances CAGECFI
    """
    try:
        # Validate query is not empty
        if not query or not query.strip():
            return "Error: Search query cannot be empty. Please provide a search query."

        # Initialize database connection
        agent_deps = AgentDependencies()
        await agent_deps.initialize()

        # Create a context wrapper for the search tools
        class DepsWrapper:
            def __init__(self, deps):
                self.deps = deps

        deps_ctx = DepsWrapper(agent_deps)

        # Perform the search based on type
        if search_type == "hybrid":
            results = await hybrid_search(
                ctx=deps_ctx,
                query=query,
                match_count=match_count
            )
        elif search_type == "semantic":
            results = await semantic_search(
                ctx=deps_ctx,
                query=query,
                match_count=match_count
            )
        else:
            results = await text_search(
                ctx=deps_ctx,
                query=query,
                match_count=match_count
            )

        # Clean up
        await agent_deps.cleanup()

        # Log pour debug
        print(f"[DEBUG] Recherche: '{query}' | Type: {search_type} | Résultats: {len(results)}")

        # Format results as a simple string
        if not results:
            print(f"[DEBUG] Aucun résultat trouvé pour: '{query}'")
            return """⚠️ AUCUNE INFORMATION TROUVÉE.

INSTRUCTION: Tu DOIS répondre: "Je n'ai pas trouvé cette information dans la documentation Perfect-Vision."
NE PAS inventer de réponse."""

        # Build a formatted response with anti-hallucination instructions
        response_parts = [
            f"📚 {len(results)} résultat(s) trouvé(s).",
            "",
            "INSTRUCTION: Utilise UNIQUEMENT les informations ci-dessous. NE PAS inventer.",
            ""
        ]

        for i, result in enumerate(results, 1):
            response_parts.append(f"--- Source {i}: {result.document_title} ---")
            response_parts.append(result.content)
            response_parts.append("")

        response_parts.append("FIN DES RÉSULTATS. Réponds UNIQUEMENT avec ces informations.")

        return "\n".join(response_parts)

    except Exception as e:
        return f"Error searching knowledge base: {str(e)}"


@rag_agent.tool
async def search_documents(
    ctx: RunContext[StateDeps[RAGState]],
    query: str,
    match_count: Optional[int] = 5
) -> str:
    """
    Rechercher directement dans la table documents (contenu original du fichier).

    Utilisez cet outil quand vous avez besoin de trouver des informations
    dans le contenu original des documents (non découpé en chunks).

    Args:
        ctx: Contexte d'exécution de l'agent
        query: Texte de recherche
        match_count: Nombre de résultats (défaut: 5)

    Returns:
        Parties de documents correspondantes à la recherche
    """
    try:
        if not query or not query.strip():
            return "Erreur: La requête de recherche ne peut pas être vide."

        agent_deps = AgentDependencies()
        await agent_deps.initialize()

        class DepsWrapper:
            def __init__(self, deps):
                self.deps = deps

        deps_ctx = DepsWrapper(agent_deps)

        results = await document_search(
            ctx=deps_ctx,
            query=query,
            match_count=match_count
        )

        await agent_deps.cleanup()

        if not results:
            return "Aucune information trouvée dans les documents."

        response_parts = [f"Trouvé {len(results)} parties de documents:\n"]

        for i, result in enumerate(results, 1):
            response_parts.append(
                f"\n--- {result.title} (partie {result.part_number}/{result.total_parts}, "
                f"pertinence: {result.similarity:.2f}) ---"
            )
            response_parts.append(result.content)

        return "\n".join(response_parts)

    except Exception as e:
        return f"Erreur lors de la recherche dans les documents: {str(e)}"


@rag_agent.tool
async def get_full_document(
    ctx: RunContext[StateDeps[RAGState]],
    file_id: str
) -> str:
    """
    Récupérer le contenu complet d'un document par son file_id.

    Utilisez cet outil quand vous avez trouvé un document intéressant
    et que vous voulez voir son contenu complet (toutes les parties).

    Args:
        ctx: Contexte d'exécution de l'agent
        file_id: UUID du fichier (obtenu via search_knowledge_base ou search_documents)

    Returns:
        Contenu complet du document (toutes les parties concaténées)
    """
    try:
        if not file_id or not file_id.strip():
            return "Erreur: file_id ne peut pas être vide."

        agent_deps = AgentDependencies()
        await agent_deps.initialize()

        class DepsWrapper:
            def __init__(self, deps):
                self.deps = deps

        deps_ctx = DepsWrapper(agent_deps)

        results = await get_document_content(
            ctx=deps_ctx,
            file_id=file_id
        )

        await agent_deps.cleanup()

        if not results:
            return f"Aucun document trouvé avec le file_id: {file_id}"

        # Reconstruct full document content
        title = results[0].title
        source = results[0].source
        total_parts = results[0].total_parts

        response_parts = [
            f"Document: {title}",
            f"Source: {source}",
            f"Parties: {total_parts}",
            "\n--- Contenu complet ---\n"
        ]

        for part in results:
            response_parts.append(part.content)

        return "\n".join(response_parts)

    except Exception as e:
        return f"Erreur lors de la récupération du document: {str(e)}"


@rag_agent.tool
async def list_all_documents(
    ctx: RunContext[StateDeps[RAGState]],
    limit: Optional[int] = 20
) -> str:
    """
    Lister tous les documents disponibles dans la base de connaissances.

    Utilisez cet outil pour voir la liste des documents disponibles,
    leurs titres et le nombre de parties.

    Args:
        ctx: Contexte d'exécution de l'agent
        limit: Nombre maximum de documents à lister (défaut: 20)

    Returns:
        Liste des documents avec leur file_id, titre et nombre de parties
    """
    try:
        agent_deps = AgentDependencies()
        await agent_deps.initialize()

        class DepsWrapper:
            def __init__(self, deps):
                self.deps = deps

        deps_ctx = DepsWrapper(agent_deps)

        results = await list_documents(
            ctx=deps_ctx,
            limit=limit
        )

        await agent_deps.cleanup()

        if not results:
            return "Aucun document trouvé dans la base de connaissances."

        response_parts = [f"Documents disponibles ({len(results)}):\n"]

        for doc in results:
            response_parts.append(
                f"- {doc['title']}\n"
                f"  file_id: {doc['file_id']}\n"
                f"  source: {doc['source']}\n"
                f"  parties: {doc['total_parts']}"
            )

        return "\n".join(response_parts)

    except Exception as e:
        return f"Erreur lors de la liste des documents: {str(e)}"
