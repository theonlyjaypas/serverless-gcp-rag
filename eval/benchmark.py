"""Run the eval set against a deployed rag-query service and write per-question results.

Usage:
    python eval/benchmark.py https://rag-query-xxxx.a.run.app [data/eval.jsonl] [eval/results_gcp.csv]

Requires: pip install requests google-auth
"""

import csv
import json
import statistics
import sys
import time
import os

import requests

URL = sys.argv[1].rstrip("/")
EVAL = sys.argv[2] if len(sys.argv) > 2 else "data/eval.jsonl"
OUT = sys.argv[3] if len(sys.argv) > 3 else "eval/results_gcp.csv"

headers = {}
if URL.startswith("https://"):
    token = os.environ["TOKEN"]
    headers = {"Authorization": f"Bearer {token}"}

with open(EVAL) as f:
    items = [json.loads(line) for line in f if line.strip()]

rows = []
for item in items:
    t0 = time.perf_counter()
    r = requests.post(f"{URL}/ask", json={"question": item["question"]}, headers=headers, timeout=60)
    wall_ms = (time.perf_counter() - t0) * 1000
    body = r.json() if r.ok else {}
    cited_docs = [c["doc"] for c in body.get("citations", [])]
    m = body.get("metrics", {})
    rows.append({
        "question": item["question"],
        "status": r.status_code,
        "wall_ms": round(wall_ms),
        "server_ms": m.get("latency_ms"),
        "input_tokens": m.get("input_tokens"),
        "output_tokens": m.get("output_tokens"),
        "retrieval_hit": item["source"] in cited_docs,
        "answer": body.get("answer", ""),
        "reference": item["answer"],
        "grade": "",  # fill in: correct / partial / wrong
    })

with open(OUT, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)

ok = [r for r in rows if r["status"] == 200]
print(f"requests: {len(rows)}  ok: {len(ok)}")
if ok:
    lat = sorted(r["wall_ms"] for r in ok)
    p50 = statistics.median(lat)
    p95 = lat[int(0.95 * (len(lat) - 1))]
    hit_rate = sum(r["retrieval_hit"] for r in ok) / len(ok)
    in_tok = statistics.mean(r["input_tokens"] for r in ok)
    out_tok = statistics.mean(r["output_tokens"] for r in ok)
    print(f"p50 wall latency: {p50:.0f} ms")
    print(f"p95 wall latency: {p95:.0f} ms")
    print(f"retrieval hit rate: {hit_rate:.1%}")
    print(f"avg input tokens: {in_tok:.0f}  avg output tokens: {out_tok:.0f}")
print(f"wrote {OUT}")
