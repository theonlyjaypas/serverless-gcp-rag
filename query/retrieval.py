import os

import google.auth
import google.auth.transport.requests
import requests
import vertexai
from sqlalchemy import text
from vertexai.language_models import TextEmbeddingModel

from db import get_engine

PROJECT_ID = os.environ["PROJECT_ID"]
REGION = os.environ.get("REGION", "us-central1")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "text-embedding-005")
# Verify this model name in the Vertex AI console before deploying.
GEN_MODEL = os.environ.get("GEN_MODEL", "gemini-3.6-flash")
# Some Gemini models are served only from the "global" location. The pinned
# Vertex SDK rejects "global", so generation calls the REST endpoint directly.
GEN_LOCATION = os.environ.get("GEN_LOCATION", "global")

vertexai.init(project=PROJECT_ID, location=REGION)
embedder = TextEmbeddingModel.from_pretrained(EMBED_MODEL)

_creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])


def _generate(prompt: str) -> dict:
    if not _creds.valid:
        _creds.refresh(google.auth.transport.requests.Request())
    url = (
        f"https://aiplatform.googleapis.com/v1/projects/{PROJECT_ID}"
        f"/locations/{GEN_LOCATION}/publishers/google/models/{GEN_MODEL}:generateContent"
    )
    resp = requests.post(
        url,
        json={"contents": [{"role": "user", "parts": [{"text": prompt}]}]},
        headers={"Authorization": f"Bearer {_creds.token}"},
        timeout=60,
    )
    resp.raise_for_status()
    body = resp.json()
    parts = body["candidates"][0]["content"]["parts"]
    usage = body["usageMetadata"]
    return {
        "text": "".join(p.get("text", "") for p in parts if not p.get("thought")),
        "input_tokens": usage["promptTokenCount"],
        "output_tokens": usage.get("candidatesTokenCount", 0),
    }


def retrieve(question: str, k: int) -> list[dict]:
    qvec = str(embedder.get_embeddings([question])[0].values)
    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT doc_name, chunk_index, content,
                       1 - (embedding <=> CAST(:q AS vector)) AS score
                FROM chunks
                WHERE is_stale = FALSE
                ORDER BY embedding <=> CAST(:q AS vector)
                LIMIT :k
            """),
            {"q": qvec, "k": k},
        ).mappings().all()
    return [dict(r) for r in rows]


def answer(question: str, chunks: list[dict]) -> dict:
    sources = "\n\n".join(
        f"[{i + 1}] ({c['doc_name']}, chunk {c['chunk_index']})\n{c['content']}"
        for i, c in enumerate(chunks)
    )
    prompt = (
        "Answer the question using only the sources below. "
        "Cite sources by their number in brackets, like [1]. "
        "If the sources do not contain the answer, say so.\n\n"
        f"Sources:\n{sources}\n\nQuestion: {question}\nAnswer:"
    )
    return _generate(prompt)
