-- ============================================================
-- Apolo AI — Schema Supabase
-- Execute no SQL Editor do painel Supabase
-- ============================================================

-- Extensões necessárias
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ------------------------------------------------------------
-- Tabela: knowledge
-- Armazena conhecimento persistente encontrado na web
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS knowledge (
    id         uuid        PRIMARY KEY DEFAULT uuid_generate_v4(),
    title      text        NOT NULL,
    url        text        UNIQUE,
    content    text        NOT NULL,
    category   text        NOT NULL DEFAULT 'web',
    tags       text[]      DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- Coluna de busca full-text gerada automaticamente (português)
ALTER TABLE knowledge
    ADD COLUMN IF NOT EXISTS fts tsvector
        GENERATED ALWAYS AS (
            to_tsvector(
                'portuguese',
                coalesce(title, '') || ' ' || coalesce(content, '')
            )
        ) STORED;

-- Índice GIN para busca full-text eficiente
CREATE INDEX IF NOT EXISTS knowledge_fts_idx
    ON knowledge USING GIN(fts);

CREATE INDEX IF NOT EXISTS knowledge_category_idx
    ON knowledge(category);

CREATE INDEX IF NOT EXISTS knowledge_updated_idx
    ON knowledge(updated_at DESC);

-- ------------------------------------------------------------
-- Row Level Security (opcional — descomente para produção)
-- ------------------------------------------------------------
-- ALTER TABLE knowledge ENABLE ROW LEVEL SECURITY;
-- CREATE POLICY "anon_read" ON knowledge FOR SELECT USING (true);
-- CREATE POLICY "anon_insert" ON knowledge FOR INSERT WITH CHECK (true);
-- CREATE POLICY "anon_update" ON knowledge FOR UPDATE USING (true);

-- ------------------------------------------------------------
-- Verificação: deve retornar as colunas criadas
-- ------------------------------------------------------------
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'knowledge'
ORDER BY ordinal_position;
