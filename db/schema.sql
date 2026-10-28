-- Run as the postgres admin user against database "rag".
-- Replace jaypas-001 in the GRANT lines with your project ID.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS chunks (
  id           BIGSERIAL PRIMARY KEY,
  doc_name     TEXT NOT NULL,
  doc_hash     TEXT NOT NULL,
  chunk_index  INT NOT NULL,
  content      TEXT NOT NULL,
  embedding    vector(768) NOT NULL,   -- matches text-embedding-005
  is_stale     BOOLEAN NOT NULL DEFAULT FALSE,
  ingested_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (doc_name, doc_hash, chunk_index)
);

CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops);

GRANT ALL ON chunks TO "rag-ingest@jaypas-001.iam";
GRANT ALL ON SEQUENCE chunks_id_seq TO "rag-ingest@jaypas-001.iam";
GRANT SELECT ON chunks TO "rag-query@jaypas-001.iam";
