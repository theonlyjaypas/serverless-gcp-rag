"""Retrieval-only check against the local database: does the source doc appear in top-k?

Usage: DATABASE_URL=... PROJECT_ID=... python scripts/retrieval_check.py [k]
"""
import json
import os
import sys

import vertexai
from sqlalchemy import create_engine, text
from vertexai.language_models import TextEmbeddingModel

K = int(sys.argv[1]) if len(sys.argv) > 1 else 5
vertexai.init(project=os.environ["PROJECT_ID"], location="us-central1")
embedder = TextEmbeddingModel.from_pretrained("text-embedding-005")
engine = create_engine(os.environ["DATABASE_URL"])

items = [json.loads(line) for line in open("data/eval.jsonl")]
hits, rr_sum = 0, 0.0
for item in items:
    qvec = str(embedder.get_embeddings([item["question"]])[0].values)
    with engine.connect() as conn:
        rows = conn.execute(
            text("""SELECT doc_name FROM chunks WHERE is_stale = FALSE
                    ORDER BY embedding <=> CAST(:q AS vector) LIMIT :k"""),
            {"q": qvec, "k": K},
        ).all()
    docs = [r[0] for r in rows]
    if item["source"] in docs:
        hits += 1
        rr_sum += 1 / (docs.index(item["source"]) + 1)
    print(item["id"], "HIT " if item["source"] in docs else "MISS", item["source"])

n = len(items)
print(f"\nhit@{K}: {hits}/{n} = {hits / n:.1%}   MRR@{K}: {rr_sum / n:.3f}")
