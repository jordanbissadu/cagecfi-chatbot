# Chatbot Support Client CAGECFI

Assistant conversationnel (RAG) pour le support client de **CAGECFI** ([www.cagecfi.com](https://www.cagecfi.com)).
Il répond aux questions des visiteurs sur les services et produits de l'agence (logiciel **Perfect Vision**, solutions de finance digitale, solutions étatiques, formations, etc.) en s'appuyant **uniquement** sur une base de connaissances documentée — pas d'invention.

> Objectif final : embarquer cet agent comme **chatbot sur le site cagecfi.com**.
> Phase actuelle : **POC en local** (interfaces CLI et Web Streamlit). L'API web + widget embarquable est la prochaine étape (voir [Feuille de route](#-feuille-de-route)).

---

## 🧱 Stack technique

| Brique | Technologie |
|---|---|
| **Base vectorielle** | Supabase (PostgreSQL + `pgvector`, index HNSW 768-dim) |
| **LLM** | Ollama **`qwen2.5:7b-instruct-q4_K_M`** (local, OpenAI-compatible, supporte le function calling) |
| **Embeddings** | Ollama **`nomic-embed-text:v1.5`** (768 dimensions) |
| **Recherche** | Hybride — vectorielle + full-text français (fonction SQL `hybrid_search`) |
| **Agent** | Pydantic AI |
| **Ingestion** | Docling (PDF, Word, PowerPoint, Excel, HTML, Markdown, Audio) |
| **Interfaces** | CLI (Rich) + Web (Streamlit) |
| **Gestion de paquets** | UV |

Le code est **agnostique au fournisseur** (endpoint OpenAI-compatible) : un basculement futur vers une API cloud (Claude/OpenAI) ne demande que de changer le `.env`.

---

## 🏗️ Architecture

```
Documents (site cagecfi.com + FAQ rédigée)
        │
        ▼
 Ingestion (Docling + Ollama embeddings)
        │
        ▼
 Supabase (pgvector)  ◀── recherche hybride ──┐
                                              │
Utilisateur ──▶ CLI / Streamlit ──▶ Agent Pydantic AI (qwen2.5:7b-instruct-q4_K_M)
                                              │
                                              └──▶ réponse ancrée sur la base
```

---

## ✅ Prérequis

- **Python 3.10+**
- **UV** (gestionnaire de paquets) — voir étape 1
- **Ollama** installé localement — [ollama.com](https://ollama.com)
- Un compte **Supabase** gratuit — [supabase.com](https://supabase.com)
- ~6 Go de RAM libres pour `qwen2.5:7b-instruct-q4_K_M` (~4,7 Go ; un GPU accélère mais n'est pas obligatoire)

> ⚠️ Le modèle LLM **doit supporter le function calling** (l'agent appelle un outil de recherche). `qwen2.5:7b-instruct-q4_K_M`, `llama3.2:3b`, `llama3.1:8b`, `gemma4:e4b` conviennent — **`gemma3:4b` ne supporte pas les tools**. Sur CPU, privilégiez un modèle léger (`qwen2.5:7b-instruct-q4_K_M` ou `llama3.2:3b`) pour des réponses rapides.

---

## 🚀 Lancement pas-à-pas

### Étape 1 — Installer UV

```powershell
# Windows (PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```
```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Étape 2 — Installer les dépendances du projet

```powershell
uv venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

uv pip install -r requirements_supabase.txt
```

> 🪟 **Windows** : la console (cp1252) ne sait pas afficher les emojis des scripts. Préfixez vos commandes par `$env:PYTHONUTF8='1';` (déjà intégré dans les exemples ci-dessous) pour éviter les `UnicodeEncodeError`.

### Étape 3 — Installer Ollama et télécharger les modèles

1. Installer Ollama depuis [ollama.com](https://ollama.com), puis démarrer le service :
   ```powershell
   ollama serve
   ```
2. Dans un autre terminal, télécharger les modèles (LLM compatible *tools* + embeddings) :
   ```powershell
   ollama pull qwen2.5:7b-instruct-q4_K_M
   ollama pull nomic-embed-text:v1.5
   ```
3. Vérifier qu'ils sont présents :
   ```powershell
   ollama list
   ```

> ⚠️ Ollama doit rester lancé (`ollama serve`) pendant l'ingestion et l'utilisation du chatbot.

### Étape 4 — Créer le projet Supabase et la base

1. Sur [supabase.com](https://supabase.com) : **New project** → noter le **mot de passe** de la base.
2. Créer le schéma dédié CAGECFI (tables `cagecfi_documents` / `cagecfi_chunks`, préfixées pour cohabiter sans risque avec d'éventuelles tables existantes). Deux options :
   - **SQL Editor** → **New query** → coller le contenu de [`supabase_setup_cagecfi.sql`](supabase_setup_cagecfi.sql) → **Run** ; **ou**
   - une fois le `.env` rempli (étape 5), exécuter :
     ```powershell
     $env:PYTHONUTF8='1'; uv run python apply_supabase_setup.py
     ```
   Cela crée l'extension `pgvector`, les deux tables et leurs index (HNSW + full-text français).

### Étape 5 — Configurer le fichier `.env`

```powershell
copy .env.supabase.example .env     # Windows
# cp .env.supabase.example .env     # macOS / Linux
```

Récupérer les valeurs Supabase (**Project Settings → API** et **→ Database → Connection string → URI**, mode *Session pooler*) et remplir dans `.env` :

```bash
SUPABASE_URL=https://xxxxxxxx.supabase.co
SUPABASE_ANON_KEY=eyJhbGc...
SUPABASE_SERVICE_ROLE_KEY=eyJhbGc...
DATABASE_URL=postgresql://postgres.[ref]:VOTRE-MOT-DE-PASSE@aws-0-...pooler.supabase.com:6543/postgres
```

La partie Ollama et les tables dédiées sont déjà configurées (à ne pas changer pour un usage local) :

```bash
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5:7b-instruct-q4_K_M
EMBEDDING_MODEL=nomic-embed-text:v1.5
EMBEDDING_DIMENSION=768
POSTGRES_TABLE_DOCUMENTS=cagecfi_documents
POSTGRES_TABLE_CHUNKS=cagecfi_chunks
```

### Étape 6 — Vérifier la base

```powershell
$env:PYTHONUTF8='1'; uv run python apply_supabase_setup.py
```
Attendu : `cagecfi_documents: cagecfi_documents (lignes=...)` et `cagecfi_chunks: ...`, puis `OK`.

### Étape 7 — Construire la base de connaissances

La base se compose de trois sources, toutes placées dans [`documents/`](documents/) :

1. **Crawl du site cagecfi.com** (automatique) — récupère toutes les pages du site et les exporte en Markdown dans `documents/cagecfi/` :
   ```powershell
   $env:PYTHONUTF8='1'; uv run python -m src.ingestion.crawl_cagecfi
   ```
2. **FAQ rédigée** — [`documents/cagecfi-faq.md`](documents/cagecfi-faq.md) : questions clients fréquentes (contacts, devis, formation, produits). Déjà fournie ; complétez-la librement.
3. **Fiche services** — [`documents/cagecfi-services.md`](documents/cagecfi-services.md) : présentation synthétique des produits. Déjà fournie.

   Vous pouvez aussi déposer vos propres fichiers (PDF, Word, Markdown, HTML…) dans `documents/`.

### Étape 8 — Lancer l'ingestion

```powershell
$env:PYTHONUTF8='1'; uv run python -m src.ingestion.ingest_supabase -d ./documents
```
Cela découpe les documents, génère les embeddings via Ollama et les stocke dans Supabase (tables `cagecfi_*`).
- Pour ajouter sans effacer l'existant : ajouter `--no-clean`.

### Étape 9 — Lancer le chatbot

**Option A — Interface Web (recommandée pour la démo)**
```powershell
$env:PYTHONUTF8='1'; uv run python -m streamlit run src/streamlit_app_supabase.py
```
S'ouvre sur `http://localhost:8501`.

**Option B — Terminal (CLI)**
```powershell
$env:PYTHONUTF8='1'; uv run python -m src.cli_supabase
```

Posez vos questions — l'agent recherche dans la base CAGECFI et répond en français.

### Étape 10 — Tester l'agent

Vérifiez d'abord que la base est bien remplie :
```powershell
$env:PYTHONUTF8='1'; uv run python apply_supabase_setup.py   # cagecfi_chunks (lignes=...) doit être > 0
```

Puis posez quelques questions de référence (CLI ou Web) pour valider les réponses :

| Question | Réponse attendue (issue de la base) |
|---|---|
| « Qu'est-ce que Perfect-Vision ? » | Logiciel de gestion intégré des systèmes financiers décentralisés (SFD). |
| « Comment demander un devis ? » | Via la page « Demander un devis » du site ou par email à cagecfi@cagecfi.com. |
| « Comment contacter CAGECFI ? » | cagecfi@cagecfi.com, +228 22 26 84 61, Lomé (Togo). |
| « Proposez-vous des formations ? » | Oui, via CAGECFI Academy. |
| « Quelle est la capitale de la France ? » | L'agent doit répondre qu'il n'a pas cette information (hors périmètre). |

Bon réflexe : si une réponse est fausse ou « je n'ai pas trouvé » alors que l'info existe, enrichissez la FAQ ([`documents/cagecfi-faq.md`](documents/cagecfi-faq.md)) puis relancez l'ingestion (étape 8).

Un jeu de **30 questions de test** prêt à l'emploi est disponible dans [`tests/cagecfi-test-questions.md`](tests/cagecfi-test-questions.md).

---

## 🌐 Front-end — Landing page + chatbot

Une page vitrine CAGECFI (sombre, animée) avec une **bulle de chat connectée à l'agent** est fournie dans [`frontend/index.html`](frontend/index.html), servie par l'API FastAPI [`src/api.py`](src/api.py).

### Lancer le chatbot complet (page + chat fonctionnel)

Prérequis : Ollama lancé (`ollama serve`), `.env` configuré et ingestion faite (étapes 3–8).

```powershell
$env:PYTHONUTF8='1'; uv run uvicorn src.api:app --port 8000
```
Puis ouvrez **http://localhost:8000**. La page se charge et le **widget de chat dialogue réellement avec l'agent** (recherche dans la base CAGECFI + réponse en français).

- `GET /` → la landing page · `POST /chat` → réponse **en streaming** · `GET /health` → état du service.
- Le chat utilise une **recherche forcée** ([`src/rag_chat.py`](src/rag_chat.py)) : il interroge toujours la base puis rédige en une seule passe LLM, et **diffuse la réponse mot à mot** (ressenti immédiat).
- Les salutations (« Bonjour », « Merci ») répondent instantanément. Pour une vraie question, le 1er mot apparaît après quelques secondes (recherche + modèle sur CPU), puis le texte défile.
- Le widget appelle `/chat` en même origine — aucune configuration CORS nécessaire en local.

> Aperçu visuel **sans** chat : `uv run python -m http.server 8080 --directory frontend` (le chat affichera alors le message de repli, car l'API n'est pas servie sur ce port).

### Embarquer sur cagecfi.com (plus tard)

Pour héberger l'API ailleurs que la page, modifiez la constante `CHAT_API_URL` dans [`frontend/index.html`](frontend/index.html) (repère `// TODO`) pour pointer vers l'URL publique de l'endpoint `/chat`. Le CORS est déjà activé côté API.

---

## 🧰 Commandes utiles

```powershell
# Préfixe Windows recommandé pour éviter les erreurs d'encodage :
$env:PYTHONUTF8='1'

# Créer / vérifier le schéma cagecfi_*
uv run python apply_supabase_setup.py

# Ingérer des documents
uv run python -m src.ingestion.ingest_supabase -d ./documents

# Ingérer sans effacer les données existantes
uv run python -m src.ingestion.ingest_supabase -d ./documents --no-clean

# Lancer l'interface web
uv run python -m streamlit run src/streamlit_app_supabase.py

# Lancer le CLI
uv run python -m src.cli_supabase

# Lancer le chatbot complet (landing + chat connecté à l'agent)
uv run uvicorn src.api:app --port 8000

# Aperçu visuel de la page seule (sans chat)
uv run python -m http.server 8080 --directory frontend
```

---

## 🩺 Dépannage

| Problème | Solution |
|---|---|
| `Ollama connection failed` | Vérifier que `ollama serve` tourne et que `qwen2.5:7b-instruct-q4_K_M` + `nomic-embed-text:v1.5` sont téléchargés (`ollama list`). |
| `Connection refused` (Supabase) | Vérifier `DATABASE_URL` dans `.env` (mot de passe réel, pas `[YOUR-PASSWORD]`) et que le projet Supabase n'est pas en pause. |
| `Extension vector not found` | Exécuter `CREATE EXTENSION IF NOT EXISTS vector;` dans le SQL Editor. |
| `Table does not exist` | Réexécuter `$env:PYTHONUTF8='1'; uv run python apply_supabase_setup.py` (recrée les tables `cagecfi_*`). |
| Le bot répond « je n'ai pas trouvé » | Vérifier que l'ingestion a réussi (`SELECT COUNT(*) FROM cagecfi_chunks;` > 0). |
| `does not support tools` (erreur 400) | Le modèle LLM ne gère pas le function calling. Utiliser `qwen2.5:7b-instruct-q4_K_M`, `llama3.2:3b` ou `llama3.1:8b` (pas `gemma3:4b`). |
| `UnicodeEncodeError` sous Windows | Préfixer la commande par `$env:PYTHONUTF8='1';`. |
| `prepared statement does not exist` / erreur pgbouncer | Déjà géré dans le code (`statement_cache_size=0`). Vérifier que `DATABASE_URL` pointe bien vers le pooler Supabase. |
| Dimensions d'embedding incompatibles | `nomic-embed-text:v1.5` = **768**. Si vous changez de modèle d'embedding, recréez la table `cagecfi_chunks` avec la bonne dimension et réingérez. |
| Le widget de chat répond « pas encore connecté » | Vous avez ouvert la page sans l'API. Lancez `uv run uvicorn src.api:app --port 8000` et ouvrez http://localhost:8000 (pas le port 8080 ni `file://`). |
| Première réponse du chat très lente | Chargement initial du modèle `qwen2.5:7b-instruct-q4_K_M` en mémoire. Normal au démarrage à froid ; les réponses suivantes sont rapides. |

---

## 📁 Structure du projet

```
MongoDB-RAG-Agent/
├── src/
│   ├── settings_supabase.py        # Configuration (Supabase + Ollama)
│   ├── providers_supabase.py       # Fournisseurs LLM / embeddings (Ollama)
│   ├── dependencies_supabase.py    # Connexion PostgreSQL + pgvector
│   ├── tools_supabase.py           # Outils de recherche (semantic, text, hybrid)
│   ├── agent_supabase.py           # Agent Pydantic AI (support CAGECFI)
│   ├── prompts.py                  # Prompts système
│   ├── cli_supabase.py             # Interface terminal
│   ├── streamlit_app_supabase.py   # Interface web (Streamlit)
│   ├── api.py                      # API FastAPI (sert la landing + endpoint /chat en streaming)
│   ├── rag_chat.py                 # Chat RAG : recherche forcée + rédaction streamée
│   └── ingestion/
│       ├── chunker.py              # Découpage Docling HybridChunker
│       ├── crawl_cagecfi.py        # Crawler du site cagecfi.com → Markdown
│       └── ingest_supabase.py      # Pipeline d'ingestion → PostgreSQL
├── documents/                      # Base de connaissances à ingérer
│   ├── cagecfi-faq.md              # FAQ support (contacts, devis, formation…)
│   ├── cagecfi-services.md         # Fiche produits/services
│   └── cagecfi/                    # Pages du site crawlées (Markdown)
├── frontend/
│   └── index.html                  # Landing page CAGECFI + widget de chat
├── tests/
│   └── cagecfi-test-questions.md   # Jeu de 30 questions de test
├── supabase_setup_cagecfi.sql      # Schéma + index des tables cagecfi_*
├── apply_supabase_setup.py         # Crée / vérifie le schéma cagecfi_*
├── .env.supabase.example           # Template de configuration
└── requirements_supabase.txt       # Dépendances Python
```

---

## 🗺️ Feuille de route

- [x] Migration vers Supabase + Ollama (recherche hybride)
- [x] Repositionnement « support client CAGECFI »
- [x] **Base de connaissances** : crawl de cagecfi.com + FAQ rédigée
- [x] **Front-end** : landing page CAGECFI + widget de chat (`frontend/index.html`)
- [x] **API FastAPI** (`/chat`) connectant le widget à l'agent (`src/api.py`)
- [x] **Recherche forcée + streaming** (réponses fiables, affichées mot à mot — `src/rag_chat.py`)
- [ ] Nettoyage du dépôt (canonicalisation des fichiers `*_supabase.py`, retrait du legacy MongoDB)
- [ ] Hébergement de production (serveur/VPS avec Ollama, ou bascule API cloud)

---

## 📚 Ressources

- [Documentation Supabase](https://supabase.com/docs) · [pgvector](https://github.com/pgvector/pgvector)
- [Pydantic AI](https://ai.pydantic.dev) · [Ollama](https://ollama.com) · [Docling](https://github.com/DS4SD/docling)
