-- =========================================
-- Schéma dédié au chatbot support CAGECFI
-- Tables préfixées cagecfi_ pour cohabiter avec les tables existantes du projet.
-- À exécuter dans le SQL Editor de Supabase (ou via apply_supabase_setup.py).
-- =========================================

-- 1. Extension pgvector (idempotent)
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Table des documents (contenu découpé en parties de ~2000 caractères)
CREATE TABLE IF NOT EXISTS cagecfi_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    content TEXT NOT NULL,
    part_number INTEGER NOT NULL DEFAULT 1,
    total_parts INTEGER NOT NULL DEFAULT 1,
    file_id UUID NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cagecfi_documents_file_id ON cagecfi_documents(file_id);
CREATE INDEX IF NOT EXISTS idx_cagecfi_documents_file_id_part ON cagecfi_documents(file_id, part_number);
CREATE INDEX IF NOT EXISTS idx_cagecfi_documents_content_fts ON cagecfi_documents
    USING GIN (to_tsvector('french', content));

-- 3. Table des chunks
--    Dimension de l'embedding = celle du modèle utilisé :
--      - OpenAI text-embedding-3-small  -> vector(1536)   [config cloud / Vercel]
--      - Ollama nomic-embed-text:v1.5   -> vector(768)    [ancienne config locale]
--    ATTENTION : changer de modèle d'embedding rend les anciens vecteurs
--    incompatibles. Si la table existe déjà en 768, exécuter D'ABORD :
--        DROP TABLE IF EXISTS cagecfi_chunks CASCADE;
--    puis relancer ce script et ré-ingérer les documents.
CREATE TABLE IF NOT EXISTS cagecfi_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    file_id UUID NOT NULL,
    content TEXT NOT NULL,
    embedding vector(1536),
    token_count INTEGER NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 4. Index vectoriel HNSW (cosine)
CREATE INDEX IF NOT EXISTS idx_cagecfi_chunks_embedding ON cagecfi_chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- 5. Index full-text français sur les chunks
CREATE INDEX IF NOT EXISTS idx_cagecfi_chunks_content_fts ON cagecfi_chunks
    USING GIN (to_tsvector('french', content));

-- 6. Index de jointure chunks -> documents
CREATE INDEX IF NOT EXISTS idx_cagecfi_chunks_file_id ON cagecfi_chunks(file_id);
