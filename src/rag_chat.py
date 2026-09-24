"""Chat RAG en mode « recherche forcée ».

Au lieu de laisser le LLM décider d'appeler un outil (peu fiable et lent car
2 passes), on recherche SYSTÉMATIQUEMENT dans la base, on injecte le contexte,
puis on fait UNE seule passe LLM pour rédiger. Plus fiable et plus rapide.
"""

import re
from typing import Optional

from pydantic_ai import Agent

from src.dependencies_supabase import AgentDependencies
from src.prompts import CONDENSE_PROMPT, GENERAL_ANSWER_PROMPT, RAG_ANSWER_PROMPT
from src.providers_supabase import get_llm_model
from src.settings_supabase import load_settings
from src.tools_supabase import hybrid_search

# Nombre de derniers tours de conversation conservés (coût/latence maîtrisés).
_MAX_HISTORY_TURNS = 6

# Agents construits paresseusement (au 1er appel) et non à l'import : ainsi
# importer ce module n'a aucun effet de bord et ne requiert pas les variables
# d'environnement (essentiel pour le build serverless Vercel).
#   - _answer_agent  : rédige à partir du CONTEXTE trouvé en base (ancré, anti-hallucination)
#   - _general_agent : répond aux questions hors périmètre CAGECFI (connaissances générales)
_answer_agent: Optional[Agent] = None
_general_agent: Optional[Agent] = None
_condense_agent: Optional[Agent] = None


def _make_agent(system_prompt: str) -> Agent:
    """Fabrique un agent de rédaction avec le prompt système donné."""
    settings = load_settings()
    return Agent(
        get_llm_model(),
        system_prompt=system_prompt,
        model_settings={
            "temperature": settings.llm_temperature,
            "top_p": settings.llm_top_p,
            "max_tokens": settings.llm_max_tokens,
        },
    )


def _get_agent() -> Agent:
    """Agent ancré sur le CONTEXTE (questions CAGECFI)."""
    global _answer_agent
    if _answer_agent is None:
        _answer_agent = _make_agent(RAG_ANSWER_PROMPT)
    return _answer_agent


def _get_general_agent() -> Agent:
    """Agent « connaissances générales » (questions hors périmètre CAGECFI)."""
    global _general_agent
    if _general_agent is None:
        _general_agent = _make_agent(GENERAL_ANSWER_PROMPT)
    return _general_agent


def _get_condense_agent() -> Agent:
    """Agent RAPIDE (gpt-4o-mini) qui reformule une relance en requête autonome."""
    global _condense_agent
    if _condense_agent is None:
        settings = load_settings()
        _condense_agent = Agent(
            get_llm_model(settings.condense_model),
            system_prompt=CONDENSE_PROMPT,
            model_settings={"temperature": 0.0, "max_tokens": 200},
        )
    return _condense_agent

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


def _social_reply(msg: str) -> Optional[str]:
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


def _format_history(history: Optional[list]) -> str:
    """Formate les derniers tours en texte 'Utilisateur:/Assistant:' (vide si aucun)."""
    if not history:
        return ""
    lines = []
    for m in history[-_MAX_HISTORY_TURNS:]:
        if isinstance(m, dict):
            role, content = m.get("role", ""), m.get("content", "")
        else:
            role, content = getattr(m, "role", ""), getattr(m, "content", "")
        content = (content or "").strip()
        if not content:
            continue
        who = "Utilisateur" if role == "user" else "Assistant"
        lines.append(f"{who}: {content}")
    return "\n".join(lines)


async def _condense_query(msg: str, hist_txt: str) -> str:
    """Reformule (historique + message) en requête de recherche autonome."""
    if not hist_txt:
        return msg
    prompt = f"HISTORIQUE :\n{hist_txt}\n\nMESSAGE À REFORMULER: {msg}"
    try:
        result = await _get_condense_agent().run(prompt)
        lines = str(result.output).strip().strip('"').splitlines()
        return (lines[0].strip() if lines else "") or msg
    except Exception:
        # Dégradation gracieuse : on cherche avec le message brut.
        return msg


async def _build_prompt(msg: str, hist_txt: str) -> Optional[str]:
    """Reformule la requête, recherche, et construit le prompt (historique + contexte)."""
    search_query = await _condense_query(msg, hist_txt)
    deps = AgentDependencies()
    await deps.initialize()
    try:
        results = await hybrid_search(_Ctx(deps), search_query, match_count=6)
    finally:
        await deps.cleanup()
    if not results:
        return None
    context = "\n\n".join(f"[{r.document_title}]\n{r.content}" for r in results)
    hist_block = f"HISTORIQUE :\n{hist_txt}\n\n" if hist_txt else ""
    return f"{hist_block}CONTEXTE:\n{context}\n\nMESSAGE ACTUEL: {msg}"


def _general_input(msg: str, hist_txt: str) -> str:
    """Entrée pour l'agent général : le message, précédé de l'historique s'il existe."""
    return f"HISTORIQUE :\n{hist_txt}\n\nMESSAGE ACTUEL: {msg}" if hist_txt else msg


async def answer(message: str, history: Optional[list] = None) -> str:
    """Répond à un message en tenant compte de l'historique de la conversation."""
    msg = (message or "").strip()
    if not msg:
        return "Posez-moi une question sur les services de CAGECFI."
    social = _social_reply(msg)
    if social:
        return social
    hist_txt = _format_history(history)
    prompt = await _build_prompt(msg, hist_txt)
    if prompt is None:
        # Hors périmètre CAGECFI : connaissances générales, avec l'historique pour le fil.
        result = await _get_general_agent().run(_general_input(msg, hist_txt))
        return str(result.output)
    result = await _get_agent().run(prompt)
    return str(result.output)


async def answer_stream(message: str, history: Optional[list] = None):
    """Version streaming de answer() (mémoire conversationnelle incluse)."""
    msg = (message or "").strip()
    if not msg:
        yield "Posez-moi une question sur les services de CAGECFI."
        return
    social = _social_reply(msg)
    if social:
        yield social
        return
    hist_txt = _format_history(history)
    prompt = await _build_prompt(msg, hist_txt)
    if prompt is None:
        async with _get_general_agent().run_stream(_general_input(msg, hist_txt)) as result:
            async for delta in result.stream_text(delta=True):
                yield delta
        return
    async with _get_agent().run_stream(prompt) as result:
        async for delta in result.stream_text(delta=True):
            yield delta
