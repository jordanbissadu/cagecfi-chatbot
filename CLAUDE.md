# CAGECFI Chatbot — Development Instructions

## Project Overview

Chatbot RAG de support client pour **CAGECFI** (ingénierie informatique, Lomé — produit
phare *Perfect-Vision*). Il répond aux visiteurs **uniquement** à partir d'une base
documentaire maison : plaquettes commerciales, pages du site, FAQ. Jamais d'invention.

Stack : **Supabase (PostgreSQL + pgvector)** pour le stockage et la recherche,
**Pydantic AI** pour l'agent, **Docling** pour l'ingestion multi-format,
**FastAPI** pour l'API, déployé en **serverless sur Vercel**. Géré avec **UV**.

> ⚠️ Le dépôt s'appelle `MongoDB-RAG-Agent` pour des raisons historiques.
> **Il n'y a plus aucune trace de MongoDB** : le legacy (`examples/`, `test_scripts/`)
> a été supprimé. La recherche hybride est faite par un RRF codé en Python,
> pas par `$rankFusion`.

## Core Principles

1. **TYPE SAFETY IS NON-NEGOTIABLE**
   - All functions, methods, and variables MUST have type annotations
   - Use Pydantic models for all data structures (documents, chunks, search results)
   - No `Any` types without explicit justification

2. **KISS** (Keep It Simple, Stupid)
   - Prefer simple, readable solutions over clever abstractions
   - Don't build fallback mechanisms unless absolutely necessary

3. **YAGNI** (You Aren't Gonna Need It)
   - Don't build features until they're actually needed
   - MVP first, enhancements later

4. **ASYNC ALL THE WAY**
   - All I/O operations MUST be async (PostgreSQL, embeddings, LLM calls)
   - Use `asyncio.gather` for concurrent operations (ex. semantic + text search)
   - Proper cleanup with `try/finally` or context managers

5. **ANTI-HALLUCINATION SUR LES FAITS CAGECFI**
   - Toute réponse **portant sur CAGECFI** (produits, tarifs, coordonnées, chiffres…)
     doit être ancrée sur un passage réellement retrouvé en base (`RAG_ANSWER_PROMPT`)
   - Zéro résultat (question **hors périmètre CAGECFI**) → le bot répond avec les
     connaissances générales du modèle via `GENERAL_ANSWER_PROMPT`, qui **interdit
     formellement d'inventer un fait spécifique à CAGECFI** (garde-fou conservé)
   - Ne jamais relâcher les garde-fous de `src/prompts.py` sans raison explicite

**Architecture:**

```
src/
├── settings_supabase.py       # Pydantic Settings (variables .env)
├── providers_supabase.py      # Fabrique le modèle LLM (API compatible OpenAI)
├── dependencies_supabase.py   # Pool asyncpg + client embeddings
├── prompts.py                 # System prompts (règles métier, en français)
├── tools_supabase.py          # Recherches semantic / text / hybrid + RRF
├── agent_supabase.py          # Agent Pydantic AI et ses outils (CLI, Streamlit)
├── rag_chat.py                # Mode « recherche forcée » (utilisé par l'API)
├── api.py                     # FastAPI : /, /chat, /health
├── cli_supabase.py            # Interface terminal (Rich)
├── streamlit_app_supabase.py  # Interface web locale
└── ingestion/
    ├── drive_source.py        # Téléchargement des plaquettes (Google Drive)
    ├── pdf_audit.py           # Classification TEXTE / MIXTE / IMAGE, dédoublonnage
    ├── mistral_ocr.py         # OCR des documents sans couche texte
    ├── extract_plaquettes.py  # Extraction routée → Markdown versionnable
    ├── product_sheet.py       # Fiches produit structurées (LLM)
    ├── chunker.py             # Wrapper Docling HybridChunker
    ├── ingest_supabase.py     # Pipeline d'ingestion → PostgreSQL
    ├── verify_ingestion.py    # Recette post-ingestion bloquante
    └── crawl_cagecfi.py       # Crawler du site cagecfi.com

api/index.py                   # Point d'entrée serverless Vercel (expose `app`)
frontend/index.html            # Landing page de démo + widget de chat
```

Pour la vue d'ensemble détaillée : `docs/comprendre-le-projet.md`.

---

## Documentation Style

**Use Google-style docstrings** for all functions, classes, and modules:

```python
async def semantic_search(
    ctx: RunContext[AgentDependencies],
    query: str,
    match_count: Optional[int] = None
) -> list[SearchResult]:
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
        ValueError: If match_count exceeds maximum allowed
    """
```

Les modules d'ingestion documentent **la mesure qui a dicté la conception**, pas
seulement le comportement (cf. l'en-tête de `pdf_audit.py` ou `mistral_ocr.py`).
Garder cette habitude : c'est ce qui rend les choix de routage défendables.

---

## Development Workflow

**Setup environment:**
```bash
uv venv
.venv\Scripts\activate     # Windows
# source .venv/bin/activate  # Unix

uv pip install -e .                    # runtime API seul
uv pip install -e ".[ingestion,ui]"    # + ingestion locale et interfaces
```

Les extras comptent : Docling / Whisper / Streamlit ne doivent **jamais** entrer
dans `[project].dependencies`, sinon le build serverless Vercel dépasse la limite
de taille.

**Créer / vérifier le schéma :**
```bash
uv run python apply_supabase_setup.py    # applique supabase_setup_cagecfi.sql
```

**Run ingestion:**
```bash
uv run python -m src.ingestion.ingest_supabase -d ./documents
uv run python -m src.ingestion.verify_ingestion    # recette bloquante
```

**Run interfaces:**
```bash
uv run python -m src.cli_supabase                       # CLI
uv run streamlit run src/streamlit_app_supabase.py      # Streamlit
uv run uvicorn src.api:app --reload --port 8000         # API + landing page
```

> 🪟 Windows : préfixer par `$env:PYTHONUTF8='1';` pour éviter les
> `UnicodeEncodeError` (la console cp1252 ne sait pas afficher les emojis).

---

## Configuration Management

### Environment Variables

**ALL configuration in .env file** (jamais commité ; en production, ce sont les
variables d'environnement du dashboard Vercel) :

```bash
# Supabase / PostgreSQL
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_ANON_KEY=...
SUPABASE_SERVICE_ROLE_KEY=...
DATABASE_URL=postgresql://...
POSTGRES_TABLE_DOCUMENTS=cagecfi_documents
POSTGRES_TABLE_CHUNKS=cagecfi_chunks

# LLM Provider (API compatible OpenAI)
LLM_PROVIDER=openai
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini
LLM_BASE_URL=https://api.openai.com/v1
LLM_TEMPERATURE=0.1          # bas = déterministe = moins d'hallucinations

# Embedding Provider
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSION=1536     # DOIT correspondre à vector(N) en base

# OCR (ingestion locale uniquement, jamais appelé depuis Vercel)
MISTRAL_API_KEY=...
```

Le code est **agnostique au fournisseur** : tout passe par une API compatible
OpenAI. Basculer vers Ollama, OpenRouter ou Anthropic ne demande que de changer
le `.env` — à condition de ré-ingérer si la dimension des embeddings change.

### Pydantic Settings

**Use Pydantic Settings for type-safe configuration** (`src/settings_supabase.py`) :

```python
class SupabaseSettings(BaseSettings):
    """Application settings with environment variable support for Supabase."""

    model_config = ConfigDict(
        env_file=".env", env_file_encoding="utf-8",
        case_sensitive=False, extra="ignore"
    )

    database_url: str = Field(..., description="PostgreSQL connection string")
    llm_model: str = Field(default="gpt-4o-mini")
    embedding_dimension: int = Field(default=1536)
```

Une clé obligatoire manquante fait échouer le démarrage avec un message explicite
(`load_settings()`), plutôt qu'un plantage obscur plus tard.

---

## Database Schema

Deux tables, définies dans `supabase_setup_cagecfi.sql` :

| Table | Rôle |
|---|---|
| `cagecfi_documents` | texte intégral découpé en **parties** de ~2000 caractères, reliées par `file_id` |
| `cagecfi_chunks` | morceaux vectorisés (`embedding vector(1536)`), reliés au fichier par `file_id` |

Index : **HNSW** (`vector_cosine_ops`) pour le vectoriel, **GIN** sur
`to_tsvector('french', content)` pour le plein texte.

La jointure de recherche se fait sur `file_id` **avec `d.part_number = 1`** pour ne
récupérer qu'une seule ligne de titre/source par fichier.

---

## Error Handling

### General Pattern

```python
try:
    result = await operation()
except SpecificError as e:
    logger.exception(f"operation_failed: context=value, error={e}")
    raise
```

### PostgreSQL Operations

```python
import asyncpg

try:
    rows = await deps.execute_query(sql, *args, fetch_mode="all")
except asyncpg.PostgresError as e:
    logger.error(f"search_failed: query={query}, error={e}")
    return []   # dégradation gracieuse : la recherche ne doit jamais crasher le chat
```

Les outils de recherche renvoient une **liste vide** en cas d'échec plutôt que de
propager : `hybrid_search` continue avec la moitié des résultats si l'une des deux
recherches échoue, et `rag_chat.answer` répond la phrase de repli si tout échoue.

En revanche, l'**ingestion** doit échouer bruyamment : `verify_ingestion.py` est
bloquant par conception — une base qui paraît remplie mais qui est vide est le
mode de défaillance que tout le pipeline vise à empêcher.

### API Calls (Embeddings, LLM)

```python
from openai import APIError, RateLimitError

try:
    result = await client.embeddings.create(model=model, input=texts)
except RateLimitError as e:
    logger.warning(f"api_rate_limited: retry_after={e.retry_after}")
    await asyncio.sleep(e.retry_after or 5)
except APIError as e:
    logger.exception(f"api_error: status_code={e.status_code}")
    raise
```

### Document Processing

```python
try:
    result = converter.convert(file_path)
except Exception as e:
    logger.exception(f"document_conversion_failed: file={file_path}")
    # Continue processing other documents, don't crash pipeline
    return None
```

---

## Testing

**Tests mirror the src directory structure:**

```
src/ingestion/pdf_audit.py    →  tests/ingestion/test_pdf_audit.py
src/ingestion/product_sheet.py →  tests/ingestion/test_product_sheet.py
src/settings_supabase.py       →  tests/test_settings_mistral.py
```

### Unit Tests

```python
import pytest
from src.ingestion.pdf_audit import classify

@pytest.mark.unit
def test_classify_routes_low_text_to_image():
    """Un PDF sous le seuil MIXTE est classé IMAGE."""
    assert classify(chars_per_page=10) == "IMAGE"
    assert classify(chars_per_page=100) == "MIXTE"
    assert classify(chars_per_page=800) == "TEXTE"
```

### Integration Tests

```python
@pytest.mark.integration
async def test_pgvector_semantic_search(pg_pool):
    """Test vector search against live Supabase."""
    results = await semantic_search(ctx=test_context, query="test", match_count=5)
    assert len(results) > 0
```

**Run tests:**
```bash
uv run pytest tests/ -v
uv run pytest tests/ -m unit          # sans I/O réseau
uv run pytest tests/ -m integration   # avec service externe
```

`docs/tests-chatbot-cagecfi.md` complète les tests automatisés par une **recette
manuelle** : des questions ancrées sur des faits réellement présents en base
(année de création, capital social, certifications). Une réponse qui s'en écarte
signale une extraction fautive, un problème de recherche, ou une hallucination.

---

## Common Pitfalls

### 1. Embedding Format for pgvector
```python
# ❌ WRONG - asyncpg ne convertit pas automatiquement une liste en type vector
await conn.fetch(sql, embedding_list)

# ✅ CORRECT - sérialiser en littéral pgvector, et caster en SQL
embedding_str = '[' + ','.join(str(x) for x in embedding) + ']'
# ... ORDER BY c.embedding <=> $1::vector
```

### 2. Async/Await Mistakes
```python
# ❌ WRONG - Forgot await
result = deps.execute_query(sql)

# ✅ CORRECT
result = await deps.execute_query(sql)
```

### 3. Missing DoclingDocument for HybridChunker
```python
# ❌ WRONG - Passing raw text to HybridChunker
chunks = chunker.chunk(dl_doc=markdown_text)

# ✅ CORRECT - Pass DoclingDocument from converter
result = converter.convert(file_path)
chunks = chunker.chunk(dl_doc=result.document)
```

### 4. Changer de modèle d'embedding sans migrer la base
La colonne est déclarée `vector(1536)`. Passer à un modèle de dimension
différente (ex. `nomic-embed-text` en 768) rend **tous les vecteurs existants
inutilisables**. Il faut `DROP TABLE cagecfi_chunks CASCADE`, réappliquer le SQL,
puis ré-ingérer entièrement.

### 5. Supabase pooler et prepared statements
```python
# ❌ WRONG - le pooler (pgbouncer) de Supabase ne supporte pas les prepared statements
pool = await asyncpg.create_pool(database_url)

# ✅ CORRECT
pool = await asyncpg.create_pool(database_url, statement_cache_size=0)
```

### 6. Effets de bord à l'import (casse le build Vercel)
```python
# ❌ WRONG - exige les variables d'environnement dès l'import du module
agent = Agent(get_llm_model(), system_prompt=PROMPT)

# ✅ CORRECT - construction paresseuse au premier appel (cf. src/rag_chat.py)
def _get_agent() -> Agent:
    global _answer_agent
    if _answer_agent is None:
        _answer_agent = Agent(get_llm_model(), system_prompt=PROMPT)
    return _answer_agent
```

### 7. Dépendances lourdes dans `[project].dependencies`
Docling, Whisper et Streamlit doivent rester dans les extras `[ingestion]` /
`[ui]`. Vercel installe depuis `pyproject.toml` : une dépendance de trop et le
build dépasse la limite de 250 Mo.

---

## Quick Reference

**PostgreSQL / pgvector:**
```python
# Recherche vectorielle (distance cosinus → similarité 0-1)
sql = """
    SELECT c.id::text, c.content,
           1 - (c.embedding <=> $1::vector) / 2 AS similarity
    FROM cagecfi_chunks c
    JOIN cagecfi_documents d ON c.file_id = d.file_id AND d.part_number = 1
    ORDER BY c.embedding <=> $1::vector
    LIMIT $2
"""

# Recherche plein texte française (racinisation + mots vides gérés)
sql = """
    SELECT ts_rank(to_tsvector('french', c.content),
                   plainto_tsquery('french', $1)) AS similarity
    FROM cagecfi_chunks c
    WHERE to_tsvector('french', c.content) @@ plainto_tsquery('french', $1)
"""
```

**Recherche hybride (RRF):**
```python
# Les deux recherches en parallèle, puis fusion par rang
semantic, text = await asyncio.gather(
    semantic_search(ctx, query, fetch_count),
    text_search(ctx, query, fetch_count),
    return_exceptions=True,
)
merged = reciprocal_rank_fusion([semantic, text], k=60)
```
Le RRF n'utilise que le **rang**, jamais le score brut — c'est ce qui permet de
combiner une similarité cosinus (0-1) et un `ts_rank` (échelle sans rapport).

**Embedding Generation:**
```python
# Batch (ALWAYS prefer batching — l'ingestion traite par lots de 100)
response = await client.embeddings.create(model=model, input=texts)
```

**Docling Conversion:**
```python
result = converter.convert(file_path)
markdown = result.document.export_to_markdown()
chunks = list(chunker.chunk(dl_doc=result.document))
```

**Pydantic AI Agent:**
```python
agent = Agent(model, deps_type=StateDeps[State], system_prompt=prompt)

@agent.tool
async def tool_func(ctx: RunContext[StateDeps[State]], arg: str) -> str:
    """Tool description — le LLM la lit pour décider d'appeler l'outil."""

async with agent.iter(input, deps=deps, message_history=history) as run:
    async for node in run:
        ...
```

---

## Implementation-Specific References

- **Vue d'ensemble** : `docs/comprendre-le-projet.md` — architecture de A à Z,
  concepts expliqués (RAG, embeddings, RRF, serverless)
- **Docling ingestion** : `.claude/reference/docling-ingestion.md` — conversion
  multi-format, HybridChunker, transcription audio Whisper
- **Agent & tools** : `.claude/reference/agent-tools.md` — patterns Pydantic AI,
  définition d'outils, streaming
- **Déploiement** : `DEPLOY_VERCEL.md`
- **Recette fonctionnelle** : `docs/tests-chatbot-cagecfi.md`
