"""Chat RAG en mode « recherche forcée ».

Au lieu de laisser le LLM décider d'appeler un outil (peu fiable et lent car
2 passes), on recherche SYSTÉMATIQUEMENT dans la base, on injecte le contexte,
puis on fait UNE seule passe LLM pour rédiger. Plus fiable et plus rapide.
"""

import re

from pydantic_ai import Agent

from src.dependencies_supabase import AgentDependencies
from src.prompts import RAG_ANSWER_PROMPT
from src.providers_supabase import get_llm_model
from src.settings_supabase import load_settings
from src.tools_supabase import hybrid_search

# Agent construit paresseusement (au 1er appel) et non à l'import : ainsi
# importer ce module n'a aucun effet de bord et ne requiert pas les variables
# d'environnement (essentiel pour le build serverless Vercel).
_answer_agent: Agent | None = None


def _get_agent() -> Agent:
    """Construit (une seule fois) puis renvoie l'agent de rédaction."""
    global _answer_agent
    if _answer_agent is None:
        settings = load_settings()
        _answer_agent = Agent(
            get_llm_model(),
            system_prompt=RAG_ANSWER_PROMPT,
            model_settings={
                "temperature": settings.llm_temperature,
                "top_p": settings.llm_top_p,
                "max_tokens": settings.llm_max_tokens,
            },
        )
    return _answer_agent

_GREETING = re.compile(r"^\s*(bonjour|bonsoir|salut|hello|hi|coucou|hey)\b", re.IGNORECASE)
_THANKS = re.compile(r"^\s*(merci|thanks|thank you|d'accord|parfait|super)\b", re.IGNORECASE)
_BYE = re.compile(r"^\s*(au revoir|bye|à bientôt|a bientot|adieu|bonne journée)\b", re.IGNORECASE)

_NO_INFO = (
    "Je n'ai pas cette information. Vous pouvez contacter CAGECFI à "
    "cagecfi@cagecfi.com ou au +228 22 26 84 61."
)


class _Ctx:
    """Petit wrapper pour fournir `.deps` aux outils de recherche."""

    def __init__(self, deps: AgentDependencies) -> None:
        self.deps = deps


async def warmup() -> None:
    """Précharge le modèle LLM (appelé au démarrage de l'API)."""
    await _get_agent().run("Bonjour")


def _social_reply(msg: str) -> str | None:
    """Réponse sociale instantanée (salutation/merci/au revoir), sinon None."""
    if len(msg) >= 30:
        return None
    if _GREETING.match(msg):
        return "Bonjour 👋 Je suis le chatbot de CAGECFI. Comment puis-je vous aider ?"
    if _THANKS.match(msg):
        return "Avec plaisir ! Puis-je vous aider sur autre chose ?"
    if _BYE.match(msg):
        return "Au revoir et à bientôt ! Pour toute question : cagecfi@cagecfi.com."
    return None


async def _build_prompt(msg: str) -> str | None:
    """Recherche dans la base et construit le prompt avec contexte (None si rien)."""
    deps = AgentDependencies()
    await deps.initialize()
    try:
        results = await hybrid_search(_Ctx(deps), msg, match_count=6)
    finally:
        await deps.cleanup()
    if not results:
        return None
    context = "\n\n".join(f"[{r.document_title}]\n{r.content}" for r in results)
    return f"CONTEXTE:\n{context}\n\nQUESTION: {msg}"


async def answer(message: str) -> str:
    """Répond à un message (non-streaming) : salutation, sinon recherche forcée + rédaction."""
    msg = (message or "").strip()
    if not msg:
        return "Posez-moi une question sur les services de CAGECFI."
    social = _social_reply(msg)
    if social:
        return social
    prompt = await _build_prompt(msg)
    if prompt is None:
        return _NO_INFO
    result = await _get_agent().run(prompt)
    return str(result.output)


async def answer_stream(message: str):
    """Génère la réponse en flux (tokens au fil de l'eau) pour un ressenti immédiat."""
    msg = (message or "").strip()
    if not msg:
        yield "Posez-moi une question sur les services de CAGECFI."
        return
    social = _social_reply(msg)
    if social:
        yield social
        return
    prompt = await _build_prompt(msg)
    if prompt is None:
        yield _NO_INFO
        return
    async with _get_agent().run_stream(prompt) as result:
        async for delta in result.stream_text(delta=True):
            yield delta
