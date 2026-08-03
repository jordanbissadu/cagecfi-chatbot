# Déploiement sur Vercel — Assistant CAGECFI

Ce guide déploie **tout sur Vercel** : la landing page + l'API `/chat`, avec les
modèles **dans le cloud** (plus rien ne tourne sur ta machine en production).

## Pourquoi cette config (rappel du blocage)

Ton agent utilisait Ollama sur `http://localhost:11434` pour le **LLM** *et* les
**embeddings**. Une fonction Vercel s'exécute dans le cloud : elle ne peut pas
joindre ton `localhost`, et Vercel ne peut pas héberger Ollama (pas de GPU,
fonctions limitées). On remplace donc :

| Rôle        | Avant (local)              | Après (cloud)                          |
|-------------|----------------------------|----------------------------------------|
| LLM         | Ollama `qwen2.5:7b`        | OpenAI `gpt-4o-mini`                    |
| Embeddings  | Ollama `nomic` (768 dim)   | OpenAI `text-embedding-3-small` (1536) |
| Base vect.  | Supabase pgvector          | Supabase pgvector (inchangé)           |
| Frontend+API| FastAPI local              | Fonction serverless Vercel             |

> ✅ **Une seule clé OpenAI** suffit pour le LLM ET les embeddings.
> Le changement d'embedding fait passer l'index de **768 → 1536 dimensions**,
> donc une **ré-ingestion** est nécessaire (une fois, en local).

---

## Étape 1 — Obtenir les clés API

1. **OpenAI** (LLM + embeddings) : https://platform.openai.com/api-keys → `sk-...`
2. **Supabase** : `DATABASE_URL` en **Transaction pooler (port 6543)**
   (Dashboard → Project Settings → Database → Connection string → *Transaction pooler*).

## Étape 2 — Migrer le schéma Supabase en 1536 dim

Dans le **SQL Editor** de Supabase :

```sql
DROP TABLE IF EXISTS cagecfi_chunks CASCADE;
```

Puis coller et exécuter le contenu mis à jour de `supabase_setup_cagecfi.sql`
(la table `cagecfi_chunks` est désormais en `vector(1536)`).

## Étape 3 — Ré-ingérer les documents (en local, en mode cloud)

L'ingestion reste locale (elle a besoin de Docling), mais doit produire des
embeddings **OpenAI** pour matcher la production :

```bash
cp .env.production.example .env        # puis remplir les vraies valeurs
uv pip install -e ".[ingestion]"      # Docling + deps d'ingestion (local uniquement)
uv run python -m src.ingestion.ingest_supabase -d documents/plaquettes_md
```

> L'ingestion cible toujours `documents/plaquettes_md/` (le markdown déjà
> extrait et validé), **jamais** les PDF bruts de `documents/plaquettes/` :
> une partie de ces PDF n'a aucune couche texte exploitable, et le pipeline
> produirait des chunks illisibles sans qu'aucune erreur ne le signale.

> Les dépendances lourdes (Docling, Whisper, Streamlit) sont en **extras**
> (`[ingestion]`, `[ui]`) pour que le build Vercel reste léger : Vercel installe
> uniquement les dépendances runtime listées dans `[project.dependencies]`.

Vérifier dans Supabase que `cagecfi_chunks` est repeuplée.

## Étape 4 — Déployer sur Vercel

```bash
npm i -g vercel        # si besoin
vercel login
vercel                 # déploiement preview
vercel --prod          # déploiement production
```

Fichiers déjà prêts dans le repo :
- `api/index.py` — expose l'app FastAPI (`src/api.py`). Vercel détecte la variable `app`.
- `vercel.json` — route tout le trafic vers la fonction ; `maxDuration: 60`.
- `pyproject.toml` — Vercel (uv) installe **uniquement** `[project.dependencies]`
  (runtime léger) ; Docling/Whisper/Streamlit sont en extras et restent en local.

## Étape 5 — Variables d'environnement Vercel

Project Settings → **Environment Variables** : recopier **toutes** les clés de
`.env.production.example` (Supabase, `DATABASE_URL` pooler 6543, `LLM_*`,
`EMBEDDING_*`, `ENABLE_WARMUP=0`). Puis **redéployer** (`vercel --prod`).

## Étape 6 — Vérifier

- `https://<ton-projet>.vercel.app/health` → `{"status":"ok"}`
- `https://<ton-projet>.vercel.app/` → la landing page
- Ouvrir le chat, poser « Qu'est-ce que CAGECFI ? » → réponse depuis la base.

---

## Points d'attention / limites

- **Timeout** : `maxDuration` = 60 s (plan Hobby : jusqu'à 60 s). Avec un modèle
  rapide la réponse arrive en quelques secondes. Garder `LLM_MAX_TOKENS` modéré.
- **Pas de streaming** : `/chat` renvoie la réponse complète en un bloc
  (`PlainTextResponse`), mode robuste sur Vercel. Le widget l'affiche d'un coup.
- **Cold start** : 1ʳᵉ requête après inactivité un peu plus lente (init du pool
  asyncpg). Normal en serverless.
- **Coût** : OpenRouter + OpenAI sont facturés à l'usage (quelques centimes pour
  un petit volume). Surveiller les quotas.
- **CORS** : actuellement ouvert (`*`) dans `src/api.py`. Pour intégrer le widget
  sur `cagecfi.com`, restreindre `allow_origins` aux domaines autorisés.
