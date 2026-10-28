# Local benchmark summary

Date: 2026-10-28. Stack: local query service (FastAPI), local Postgres 16 + pgvector, Vertex AI `text-embedding-005` for embeddings, Gemini `gemini-3.6-flash` (global location) for answers. Chunking: fixed 1200 chars with 200 overlap. Top-k: 5.

Corpus: 45 Kubernetes concept docs (about 620 KB), 639 chunks. Eval: 50 questions in `data/eval.jsonl`, each with a reference answer and a source document.

| Metric | Result |
|---|---|
| Requests succeeded | 50 / 50 |
| p50 wall latency | 3113 ms |
| p95 wall latency | 4701 ms |
| Retrieval hit rate (source doc in citations) | 100.0% |
| Average input tokens | 1557 |
| Average output tokens | 66 |
| Answer accuracy | 49 correct, 1 wrong (manual grading) |

Caveats:
- Graded by hand against the reference answers, by the author. Spot-check before relying on it.
- Questions were written from the corpus text, so hit rate and accuracy are likely optimistic.
- Retrieval hit checks the source document, not the chunk. Q16 was a miss at answer level even though its document was retrieved.
- Latency is from a local run, not Cloud Run. Warm and cold GCP numbers are still needed.
- Latencies come from a single pass over 50 questions. No repeat runs yet.
- Cost per 1,000 queries is not computed. It needs billing data from a deployed run.
