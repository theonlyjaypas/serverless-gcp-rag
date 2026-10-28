import hashlib
import io
import json
import logging
import os

import vertexai
from google.cloud import storage
from pypdf import PdfReader
from sqlalchemy import text
from vertexai.language_models import TextEmbeddingModel

from chunking import chunk
from db import get_engine

PROJECT_ID = os.environ["PROJECT_ID"]
REGION = os.environ.get("REGION", "us-central1")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "text-embedding-005")
EMBED_BATCH = 50

log = logging.getLogger("ingest")

vertexai.init(project=PROJECT_ID, location=REGION)
embedder = TextEmbeddingModel.from_pretrained(EMBED_MODEL)
LOCAL_CORPUS_DIR = os.environ.get("LOCAL_CORPUS_DIR")  # local mode: read files from disk, not GCS
gcs = None if LOCAL_CORPUS_DIR else storage.Client()


def extract_text(name: str, data: bytes) -> str:
    if name.lower().endswith(".pdf"):
        reader = PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    return data.decode("utf-8", errors="replace")


def embed(texts: list[str]) -> list[list[float]]:
    vectors = []
    for i in range(0, len(texts), EMBED_BATCH):
        batch = embedder.get_embeddings(texts[i : i + EMBED_BATCH])
        vectors.extend(e.values for e in batch)
    return vectors


def ingest_object(bucket: str, name: str) -> dict:
    if LOCAL_CORPUS_DIR:
        with open(os.path.join(LOCAL_CORPUS_DIR, name), "rb") as f:
            data = f.read()
    else:
        data = gcs.bucket(bucket).blob(name).download_as_bytes()
    doc_hash = hashlib.sha256(data).hexdigest()
    engine = get_engine()

    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM chunks WHERE doc_name = :n AND doc_hash = :h LIMIT 1"),
            {"n": name, "h": doc_hash},
        ).first()

    if exists:
        # Reactivate this version (it may have been marked stale by a later upload)
        # and mark every other version stale.
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE chunks SET is_stale = (doc_hash <> :h) WHERE doc_name = :n"),
                {"n": name, "h": doc_hash},
            )
        return {"doc": name, "status": "unchanged", "chunks": 0}

    body = extract_text(name, data)
    log.info(json.dumps({"event": "extracted", "doc": name, "chars": len(body)}))

    pieces = chunk(body)
    if not pieces:
        raise ValueError(f"no extractable text in {name}")
    vectors = embed(pieces)

    rows = [
        {"n": name, "h": doc_hash, "i": i, "c": content, "e": str(vec)}
        for i, (content, vec) in enumerate(zip(pieces, vectors))
    ]

    # Stale-marking and inserts share one transaction, so a failed run never
    # leaves the document with no active chunks.
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE chunks SET is_stale = TRUE WHERE doc_name = :n AND doc_hash <> :h"),
            {"n": name, "h": doc_hash},
        )
        conn.execute(
            text("""
                INSERT INTO chunks (doc_name, doc_hash, chunk_index, content, embedding)
                VALUES (:n, :h, :i, :c, CAST(:e AS vector))
                ON CONFLICT (doc_name, doc_hash, chunk_index) DO NOTHING
            """),
            rows,
        )

    return {"doc": name, "status": "ingested", "chunks": len(pieces)}
