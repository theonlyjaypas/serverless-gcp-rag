import json
import logging
import time

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from retrieval import answer, retrieve

app = FastAPI()
log = logging.getLogger("query")
logging.basicConfig(level=logging.INFO)


class Ask(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    k: int = Field(default=5, ge=1, le=10)


@app.get("/healthz")
def health():
    return {"ok": True}


@app.post("/ask")
def ask(req: Ask):
    t0 = time.perf_counter()
    try:
        chunks = retrieve(req.question, req.k)
        t_retrieve = time.perf_counter() - t0
        result = answer(req.question, chunks)
    except Exception as e:
        # Full traceback goes to the logs; the client gets a generic message.
        log.exception("query failed")
        raise HTTPException(status_code=500, detail="query failed") from e

    metrics = {
        "latency_ms": round((time.perf_counter() - t0) * 1000),
        "retrieval_ms": round(t_retrieve * 1000),
        "input_tokens": result["input_tokens"],
        "output_tokens": result["output_tokens"],
    }
    log.info(json.dumps({"event": "ask", **metrics}))

    return {
        "answer": result["text"],
        "citations": [
            {"doc": c["doc_name"], "chunk": c["chunk_index"], "score": round(c["score"], 4)}
            for c in chunks
        ],
        "metrics": metrics,
    }
