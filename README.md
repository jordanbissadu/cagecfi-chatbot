# Chatbot Support Client CAGECFI

Assistant conversationnel (RAG) pour le support client de **CAGECFI** ([www.cagecfi.com](https://www.cagecfi.com)).
Sur toute question **concernant CAGECFI** (produits, services, tarifs, coordonnées…), il répond **uniquement** à partir d'une base de connaissances documentée — jamais d'invention. Pour une question **hors périmètre CAGECFI** (culture générale, définitions…), il répond intelligemment avec les connaissances du modèle, sans jamais inventer un fait spécifique à CAGECFI.

> **Statut : déployé en production sur Vercel** (serverless), avec un widget de chat sur la landing page.
> Le développement en local reste possible (CLI, Streamlit, API) — voir [Lancement pas-à-pas](#-lancement-pas-à-pas).

---

## 🧱 Stack technique

| Brique | Technologie |
|---|---|
| **Base vectorielle** | Supabase (PostgreSQL + `pgvector`, index HNSW **1536-dim**) |
| **LLM** | **RodiumAI** `openai/gpt-4o-mini` (gateway compatible OpenAI) |
| **Embeddings** | **RodiumAI** `openai/text-embedding-3-small` (**1536 dimensions**) |
| **Recherche** | Hybride — vectorielle + full-text français (RRF en Python) |
| **Agent** | Pydantic AI |
| **Ingestion** | Docling (PDF, Word, PowerPoint, Excel, HTML, Markdown, Audio) |
| **Interfaces** | Widget web (landing) + CLI (Rich) + Streamlit |
| **Déploiement** | **Vercel** (serverless Python, `api/index.py`) |
| **Gestion de paquets** | UV |

Le code est **agnostique au fournisseur** : tout passe par une API compatible OpenAI
(`LLM_BASE_URL` / `EMBEDDING_BASE_URL`). Basculer vers **OpenAI, RodiumAI, Ollama
(local), OpenRouter…** ne demande que de changer le `.env` — à condition de ré-ingérer
si la **dimension des embeddings** change (voir [Dépannage](#-dépannage)).

---

## 🏗️ Architecture

```
Documents (site cagecfi.com + FAQ + plaquettes)
        │
        ▼
 Ingestion (Docling + embeddings text-embedding-3-small, 1536)
        │
        ▼
 Supabase (pgvector)  ◀── recherche hybride (RRF) ──┐
                                                    │
Visiteur ──▶ Widget web / CLI / Streamlit ──▶ rag_chat + Pydantic AI
   (Vercel serverless FastAPI)                 (RodiumAI · gpt-4o-mini)
                                                    │
       ┌────────────────────────────────────────────┘
       ├─▶ question CAGECFI  → réponse ANCRÉE sur la base
       └─▶ question générale → connaissances du modèle (sans inventer de fait CAGECFI)
```

---

## ✅ Prérequis

- **Python 3.10+**
- **UV** (gestionnaire de paquets) — voir étape 1
- Un compte **Supabase** gratuit — [supabase.com](https://supabase.com)
- Un fournisseur LLM/embeddings compatible OpenAI — **RodiumAI** ([rodiumai.io](https://www.rodiumai.io)) par défaut
- *(Optionnel)* **Ollama** — [ollama.com](https://ollama.com) — uniquement pour la voie 100 % locale/gratuite

> ℹ️ L'API `/chat` (widget web) utilise une **recherche forcée** (`src/rag_chat.py`) :
> elle interroge toujours la base puis rédige en une seule passe — **aucun function
> calling requis**, donc n'importe quel modèle convient. Les interfaces CLI/Streamlit,
> elles, passent par l'agent à outils (`src/agent_supabase.py`) et requièrent un
> modèle qui supporte les *tools* (ex. `gpt-4o-mini`, `qwen2.5:7b` ; pas `gemma3:4b`).

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

# Runtime seul (API /chat) :
uv pip install -e .

# Avec l'ingestion locale (Docling, OCR) et les interfaces CLI / Streamlit :
uv pip install -e ".[ingestion,ui]"
```

> Les dépendances sont déclarées dans `pyproject.toml`. Les briques lourdes
> (Docling, Whisper, Streamlit) sont des **extras optionnels** : elles ne servent
> qu'en local et alourdiraient le build serverless.

> 🪟 **Windows** : la console (cp1252) ne sait pas afficher les emojis des scripts. Préfixez vos commandes par `$env:PYTHONUTF8='1';` (déjà intégré dans les exemples ci-dessous) pour éviter les `UnicodeEncodeError`.

### Étape 3 — (Optionnel, voie locale) Installer Ollama

> À faire **uniquement** si tu choisis la voie 100 % locale au lieu de RodiumAI
> (étape 5). Avec RodiumAI (config par défaut), **saute cette étape**.

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

Configurer le fournisseur LLM/embeddings. **Config actuelle (prod) : RodiumAI**, un
gateway compatible OpenAI. Crée une clé sur [rodiumai.io/dashboard/api-keys](https://www.rodiumai.io/dashboard/api-keys)
(et autorise le modèle d'embedding `openai/text-embedding-3-small`) :

```bash
LLM_PROVIDER=openai
LLM_API_KEY=rd_sk_...            # ta clé RodiumAI
LLM_MODEL=openai/gpt-4o-mini
LLM_BASE_URL=https://api.rodiumai.io/v1

EMBEDDING_PROVIDER=openai
EMBEDDING_API_KEY=rd_sk_...      # même clé
EMBEDDING_MODEL=openai/text-embedding-3-small
EMBEDDING_BASE_URL=https://api.rodiumai.io/v1
EMBEDDING_DIMENSION=1536         # DOIT correspondre à vector(N) en base

POSTGRES_TABLE_DOCUMENTS=cagecfi_documents
POSTGRES_TABLE_CHUNKS=cagecfi_chunks
```

> 💡 **Alternative 100 % locale et gratuite : Ollama.** Mets plutôt
> `LLM_BASE_URL=http://localhost:11434/v1`, `LLM_MODEL=qwen2.5:7b-instruct-q4_K_M`,
> `EMBEDDING_MODEL=nomic-embed-text:v1.5`, `EMBEDDING_DIMENSION=768` (⚠️ 768 ≠ 1536 :
> recrée la table `cagecfi_chunks` en `vector(768)` puis ré-ingère). Voir l'étape 3.

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
4. **Plaquettes commerciales** — pipeline dédié (`drive_source.py` → `pdf_audit.py` → `extract_plaquettes.py` → `product_sheet.py`) qui audite, extrait et résume chaque plaquette PDF. Le markdown déjà extrait et validé vit dans `documents/plaquettes_md/`.

   Vous pouvez aussi déposer vos propres fichiers (PDF, Word, Markdown, HTML…) dans `documents/`, **sauf dans `documents/plaquettes/`** : ce dossier contient les PDF bruts des plaquettes, dont certains n'ont aucune couche texte exploitable — ne les passez jamais directement à l'ingestion (voir Étape 8).

### Étape 8 — Lancer l'ingestion

```powershell
$env:PYTHONUTF8='1'; uv run python -m src.ingestion.ingest_supabase -d documents/plaquettes_md
```
Cela découpe les documents, génère les embeddings via Ollama et les stocke dans Supabase (tables `cagecfi_*`).
- Pour ajouter sans effacer l'existant : ajouter `--no-clean`.
- L'ingestion cible toujours le markdown déjà extrait (`documents/plaquettes_md/`), **jamais** les PDF bruts de `documents/plaquettes/` : une partie de ces PDF n'a aucune couche texte exploitable et produirait des chunks illisibles sans qu'aucune erreur ne le signale. Pour les autres sources (crawl, FAQ, fiche services), ciblez leur propre dossier ou fichier avec `--no-clean` plutôt qu'un `-d ./documents` global.

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
| « Quelle est la capitale de la France ? » | **« Paris. »** — question hors périmètre : réponse via les connaissances générales du modèle. |
| « Quel est le chiffre d'affaires exact de CAGECFI ? » | Décline sans inventer → renvoie au contact (garde-fou anti-hallucination). |

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

---

## ☁️ Déploiement sur Vercel

Le projet est déployé en **serverless Python** sur Vercel : `api/index.py` expose
l'app FastAPI, `vercel.json` route tout vers elle et sert la landing page.

### Contrainte critique : taille du bundle < 500 Mo
Vercel installe les dépendances au build. Les briques lourdes (Docling, Whisper,
transformers, torch, Streamlit) **feraient exploser la limite de 500 Mo**. Deux
fichiers garantissent un build slim :
- [`requirements.txt`](requirements.txt) — **uniquement** les deps runtime de l'API
  (miroir de `[project].dependencies`). Ne jamais y ajouter les extras.
- [`.vercelignore`](.vercelignore) — exclut `uv.lock` (qui embarque les extras),
  `documents/`, `tests/`, `.venv`… pour forcer une install minimale.

### Variables d'environnement (dashboard Vercel → Settings → Environment Variables)
Reprendre **toutes** les clés du `.env` (elles ne sont jamais commitées) :
`SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `DATABASE_URL`,
`POSTGRES_TABLE_*`, et le bloc **RodiumAI** (`LLM_*`, `EMBEDDING_*`).

### Déployer
- **Via Git** : connecter le dépôt à **un seul** projet Vercel dont la *Production
  Branch* est `feat/ingestion-plaquettes-cagecfi` → chaque push redéploie.
- **Via CLI** (déploiement manuel de l'état local) :
  ```powershell
  npx vercel link          # lier au bon projet
  npx vercel deploy --prod # build + mise en production
  ```

> ⚠️ Attention aux **projets Vercel multiples** : ne garder qu'un projet relié au
> dépôt pour éviter que l'URL de prod pointe vers un projet non synchronisé.

### Embarquer le widget sur un autre domaine (cagecfi.com)
Si la page est hébergée ailleurs que l'API, modifier `CHAT_API_URL` dans
[`frontend/index.html`](frontend/index.html) (repère `// TODO`) vers l'URL publique
de `/chat`. Le CORS est déjà activé côté API.

---

## 🧰 Commandes utiles

```powershell
# Préfixe Windows recommandé pour éviter les erreurs d'encodage :
$env:PYTHONUTF8='1'

# Créer / vérifier le schéma cagecfi_*
uv run python apply_supabase_setup.py

# Ingérer les plaquettes (markdown déjà extrait, jamais les PDF bruts de documents/plaquettes/)
uv run python -m src.ingestion.ingest_supabase -d documents/plaquettes_md

# Ingérer sans effacer les données existantes
uv run python -m src.ingestion.ingest_supabase -d documents/plaquettes_md --no-clean

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
| Dimensions d'embedding incompatibles | La table est en `vector(1536)` (= `text-embedding-3-small`). Changer de modèle d'embedding de dimension différente impose `DROP TABLE cagecfi_chunks CASCADE`, recréer le schéma, puis **ré-ingérer**. |
| `model_not_allowed` (403 RodiumAI) | La clé n'est pas autorisée pour ce modèle. Dans le dashboard RodiumAI, autoriser `openai/gpt-4o-mini` **et** `openai/text-embedding-3-small` pour la clé. |
| `billing_not_active` / `account is not active` (429) | Le compte du fournisseur (OpenAI/RodiumAI) n'a pas de facturation active ou de crédits. Recharger le wallet / activer la facturation. |
| La prod ne reflète pas mes changements | Vérifier que le déploiement vise **le bon projet Vercel** (plusieurs projets peuvent coexister) et que le build a réussi (bundle < 500 Mo). |
| `bundle size exceeds 500 MB` (build Vercel) | Une dep lourde a fui dans le runtime. Vérifier que `requirements.txt` reste slim et que `.vercelignore` exclut bien `uv.lock`. |
| Le widget de chat répond « pas encore connecté » | Vous avez ouvert la page sans l'API. Lancez `uv run uvicorn src.api:app --port 8000` et ouvrez http://localhost:8000 (pas le port 8080 ni `file://`). |

---

## 📁 Structure du projet

```
MongoDB-RAG-Agent/
├── src/
│   ├── settings_supabase.py        # Configuration (Supabase + LLM/embeddings via .env)
│   ├── providers_supabase.py       # Fabrique le modèle LLM (API compatible OpenAI)
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
│       ├── drive_source.py         # Téléchargement des plaquettes (Google Drive)
│       ├── pdf_audit.py            # Audit d'extractibilité (TEXTE / MIXTE / IMAGE)
│       ├── mistral_ocr.py          # OCR des plaquettes sans couche texte
│       ├── extract_plaquettes.py   # Extraction routée → Markdown relisible
│       ├── product_sheet.py        # Fiches produit structurées (LLM)
│       ├── verify_ingestion.py     # Recette post-ingestion bloquante
│       └── ingest_supabase.py      # Pipeline d'ingestion → PostgreSQL
├── api/
│   └── index.py                    # Point d'entrée serverless Vercel
├── documents/                      # Base de connaissances à ingérer
│   ├── cagecfi/                    # Pages du site crawlées + FAQ (Markdown)
│   ├── plaquettes/                 # PDF sources téléchargés (hors git)
│   ├── plaquettes_md/              # Markdown extraits + fiches produit
│   └── plaquettes_audit.json       # Rapport d'audit du corpus
├── frontend/
│   └── index.html                  # Landing page CAGECFI + widget de chat
├── docs/
│   ├── comprendre-le-projet.md     # Guide d'architecture de A à Z
│   └── tests-chatbot-cagecfi.md    # Recette manuelle ancrée sur la base
├── tests/                          # Tests pytest (chaîne d'ingestion)
├── supabase_setup_cagecfi.sql      # Schéma + index des tables cagecfi_*
├── apply_supabase_setup.py         # Crée / vérifie le schéma cagecfi_*
├── .env.supabase.example           # Template de configuration (.env)
├── vercel.json                     # Routage serverless Vercel
├── requirements.txt                # Deps RUNTIME slim pour le build Vercel (< 500 Mo)
├── .vercelignore                   # Exclut uv.lock + dossiers lourds du déploiement
└── pyproject.toml                  # Dépendances (runtime + extras) et packaging
```

---

## 🗺️ Feuille de route

- [x] Migration vers Supabase + Ollama (recherche hybride)
- [x] Repositionnement « support client CAGECFI »
- [x] **Base de connaissances** : crawl de cagecfi.com + FAQ rédigée
- [x] **Front-end** : landing page CAGECFI + widget de chat (`frontend/index.html`)
- [x] **API FastAPI** (`/chat`) connectant le widget à l'agent (`src/api.py`)
- [x] **Recherche forcée + streaming** (réponses fiables, affichées mot à mot — `src/rag_chat.py`)
- [x] **Retrait du legacy MongoDB** (`examples/`, `test_scripts/`, doublons de dépendances)
- [x] **Bascule fournisseur cloud** : RodiumAI (`openai/gpt-4o-mini` + `openai/text-embedding-3-small`, 1536)
- [x] **Déploiement production sur Vercel** (serverless, bundle slim)
- [x] **Réponses générales** hors périmètre CAGECFI (garde-fou anti-hallucination conservé)
- [ ] Canonicalisation des noms de fichiers `*_supabase.py` → `*.py`
- [ ] Consolidation des projets Vercel + auto-déploiement Git

---

## 📚 Ressources

- [Documentation Supabase](https://supabase.com/docs) · [pgvector](https://github.com/pgvector/pgvector)
- [Pydantic AI](https://ai.pydantic.dev) · [Ollama](https://ollama.com) · [Docling](https://github.com/DS4SD/docling)
