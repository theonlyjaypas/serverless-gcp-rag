# GCP Serverless RAG: Document Q&A with Citations

A retrieval-augmented generation (RAG) system on Google Cloud. Upload documents to a Cloud Storage bucket. They are extracted, chunked, embedded with Vertex AI, and stored in Postgres with pgvector. A query endpoint embeds the question, retrieves the most relevant chunks, and asks Gemini for an answer that cites its sources.

The project was built as a measured, end-to-end system: a 50-question eval set, a retrieval benchmark, a tested failure path, and Terraform for the infrastructure.

## Contents

- [Architecture](#architecture)
- [Status](#status)
- [How it works](#how-it-works)
- [Repository layout](#repository-layout)
- [API](#api)
- [Run it locally](#run-it-locally)
- [Deploy to Google Cloud](#deploy-to-google-cloud)
- [Evaluation](#evaluation)
- [Design decisions](#design-decisions)
- [Known limitations](#known-limitations)
- [Troubleshooting](#troubleshooting)

## Architecture

```
                 OBJECT_FINALIZE
 upload -------> GCS bucket -------------> Pub/Sub topic (ingest-jobs)
 (documents)                                     |
                                                 | push subscription (ingest-jobs-sub)
                                                 | dead-letter after 5 attempts --> ingest-jobs-dlq
                                                 v
                                   Cloud Run: rag-ingest
                                   read object -> extract text -> chunk
                                   -> Vertex AI embeddings -> write
                                                 |
                                                 v
                                   Cloud SQL (Postgres 16 + pgvector)
                                                 ^
                                                 | top-k vector search
                                                 |
 question --> Cloud Run: rag-query --------------+
              embed question -> retrieve chunks -> Gemini on Vertex AI
              -> answer with [n] citations
```

Both Cloud Run services require IAM authentication. Neither is publicly reachable.

## Status

| Part | State |
|---|---|
| Ingest service (chunking, embedding, idempotent writes, stale-version handling) | Built and run locally against 45 documents |
| Query service (`/ask` with citations and metrics) | Built and run locally, answers verified |
| Retrieval evaluation (50 questions) | Run locally: hit rate 100%, MRR 1.0 |
| End-to-end benchmark (50 questions through `/ask`) | Run locally: all requests succeed, latency and token numbers below |
| Answer accuracy | Graded locally: 49 correct, 1 wrong |
| Terraform (service accounts, bucket, Pub/Sub, Cloud SQL, IAM) | Cloud SQL instance and IAM users created; final Pub/Sub bindings in progress |
| Cloud Run deployment, Pub/Sub push wiring | Not yet done |
| Dashboard, alert policies, failure test matrix | Not yet done |

See `nextsteps.md` for the remaining steps.

## How it works

### Ingest

1. A file lands in the docs bucket. GCS publishes an `OBJECT_FINALIZE` event to the `ingest-jobs` topic.
2. Pub/Sub pushes the event to `rag-ingest`. A 2xx response acknowledges the message. Any other response causes a retry.
3. The service downloads the object and computes its SHA-256 hash.
   - If that hash is already stored for this document, the file is unchanged. The service reactivates that version and marks any other versions stale. No embedding calls are made.
   - Otherwise the text is extracted (`pypdf` for PDFs, UTF-8 decoding for everything else).
4. The text is split into 1,200-character windows with 200 characters of overlap. Whitespace-only pieces are dropped.
5. Each chunk is embedded with `text-embedding-005` (768 dimensions), in batches of 50.
6. Old versions are marked stale, and the new chunks are inserted, in one transaction. A failed run never leaves a document with no active chunks.
7. After five failed deliveries, Pub/Sub moves the message to `ingest-jobs-dlq`.

### Query

1. `POST /ask` validates the question (3 to 1,000 characters) and `k` (1 to 10, default 5).
2. The question is embedded, and the nearest non-stale chunks are retrieved by cosine distance (pgvector `<=>`).
3. The chunks are placed in a prompt that asks Gemini to answer only from the numbered sources and to cite them as `[n]`.
4. The response contains the answer, the citations, and latency and token metrics. Raw chunk text is not returned.

## Repository layout

```
.
├── README.md
├── nextsteps.md              # Remaining steps and deployment runbook
├── plan.md                   # Original six-week build plan
├── docker-compose.yml        # Local Postgres 16 with pgvector (port 5433)
├── data/
│   ├── corpus/               # 45 Kubernetes concept docs (public, Markdown)
│   └── eval.jsonl            # 50 questions with reference answers and source docs
├── db/
│   └── schema.sql            # chunks table, HNSW index, grants
├── ingest/                   # Pub/Sub push service
│   ├── main.py               # HTTP handler, event validation, retry signalling
│   ├── pipeline.py           # download, hash, extract, embed, write
│   ├── chunking.py           # pure text chunker (no GCP imports)
│   ├── db.py                 # Cloud SQL connector or DATABASE_URL
│   ├── test_chunking.py      # unit tests for the chunker
│   ├── requirements.txt      # pinned versions
│   └── Dockerfile
├── query/                    # Question-answering API
│   ├── main.py               # FastAPI app: /ask and /healthz
│   ├── retrieval.py          # embed, retrieve, generate
│   ├── db.py                 # same connection logic as ingest
│   ├── requirements.txt
│   └── Dockerfile
├── eval/
│   ├── benchmark.py          # runs the eval set against a service
│   ├── results_local.csv     # per-question results, local run (graded)
│   ├── results_gcp.csv       # per-question results, second run (not yet graded)
│   └── summary_local.md      # benchmark summary
├── scripts/
│   ├── send_ingest_event.py  # sends a Pub/Sub-style event to a running ingest service
│   └── retrieval_check.py    # retrieval-only hit rate and MRR, no generation calls
├── docs/
│   └── chunking-analysis.json  # rag-architect chunking comparison on the corpus
└── infra/                    # Terraform (GCS backend)
    ├── versions.tf
    ├── variables.tf
    ├── main.tf               # service accounts, bucket, Pub/Sub, IAM
    ├── cloudsql.tf           # Cloud SQL instance, database, users, IAM
    └── outputs.tf
```

## API

### `POST /ask`

Request:

```json
{ "question": "Are Kubernetes Secrets encrypted in the API server data store by default?", "k": 5 }
```

Response (shortened):

```json
{
  "answer": "No. By default, Kubernetes Secrets are stored unencrypted in the API server's underlying data store (etcd) [1].",
  "citations": [
    { "doc": "secret.md", "chunk": 1, "score": 0.7747 },
    { "doc": "secret.md", "chunk": 0, "score": 0.7343 }
  ],
  "metrics": {
    "latency_ms": 2790,
    "retrieval_ms": 509,
    "input_tokens": 1495,
    "output_tokens": 27
  }
}
```

Errors:

| Status | Meaning |
|---|---|
| 422 | Validation failed (for example, a question shorter than 3 characters) |
| 500 | The query failed. The full traceback is logged; the client sees `{"detail": "query failed"}` |
| 403 | Missing or invalid identity token (Cloud Run only) |

### `GET /healthz`

Returns `{"ok": true}`.

## Run it locally

Requirements: Python 3.13 (3.12 also works), Docker, and Google Cloud application-default credentials with access to Vertex AI in your project.

```bash
# 1. Start Postgres with pgvector on port 5433
docker compose up -d db

# 2. Create the virtualenv and install pinned dependencies
python3 -m venv .venv
.venv/bin/pip install -r ingest/requirements.txt -r query/requirements.txt

# 3. Apply the schema (the GRANT lines are for Cloud SQL; skip them locally)
grep -v GRANT db/schema.sql | docker compose exec -T db psql -U rag -d rag -v ON_ERROR_STOP=1

# 4. Start the ingest service
cd ingest
PROJECT_ID=jaypas-001 \
DATABASE_URL=postgresql+pg8000://rag:rag@127.0.0.1:5433/rag \
LOCAL_CORPUS_DIR=$PWD/../data/corpus \
../.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8090 &
cd ..

# 5. Ingest the corpus (sends one Pub/Sub-style event per file)
for f in data/corpus/*.md; do .venv/bin/python scripts/send_ingest_event.py http://127.0.0.1:8090 "$(basename "$f")"; done

# 6. Start the query service
cd query
PROJECT_ID=jaypas-001 \
DATABASE_URL=postgresql+pg8000://rag:rag@127.0.0.1:5433/rag \
GEN_MODEL=gemini-3.6-flash GEN_LOCATION=global \
../.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8091 &
cd ..

# 7. Ask a question
curl -s -X POST http://127.0.0.1:8091/ask -H 'Content-Type: application/json' \
  -d '{"question":"Are Kubernetes Secrets encrypted in the API server data store by default?"}' | python3 -m json.tool
```

Run the tests for the chunker (no services or credentials needed):

```bash
cd ingest && python3 -m unittest test_chunking -v
```

Run the retrieval check and the benchmark:

```bash
PROJECT_ID=jaypas-001 DATABASE_URL=postgresql+pg8000://rag:rag@127.0.0.1:5433/rag \
  .venv/bin/python scripts/retrieval_check.py 5

.venv/bin/python eval/benchmark.py http://127.0.0.1:8091 data/eval.jsonl eval/results_local.csv
```

The benchmark calls Gemini once per question, so it has a small cost in your project.

## Deploy to Google Cloud

The full runbook, with exact commands, is in `nextsteps.md` (sections 1 to 4 and "What to do next (part 2)"). In short:

1. **Infrastructure.** From `infra/`, run `terraform plan`, then `terraform apply`. This creates the service accounts, the docs bucket, the Pub/Sub topics and subscriptions with a dead-letter path, the Cloud SQL instance (`db-f1-micro`, Postgres 16), and the IAM bindings. Terraform state is stored in `gs://jaypas-001-tfstate`.
2. **Database.** Set a password for the `postgres` user, then load `db/schema.sql` with `gcloud sql connect`.
3. **Services.** Deploy `ingest/` as `rag-ingest` and `query/` as `rag-query` with `gcloud run deploy --source`. Both use `--no-allow-unauthenticated`. Set `PROJECT_ID`, `INSTANCE_CONNECTION_NAME`, `DB_USER`, and, for the query service, `GEN_MODEL` and `GEN_LOCATION`.
4. **Wiring.** Create the GCS notification to `ingest-jobs`, grant the Pub/Sub service account token-creator rights, and set the push endpoint of `ingest-jobs-sub` to the ingest service URL.
5. **Verify.** Upload the corpus, confirm the chunk counts, re-upload one file to confirm the unchanged path, and call `/ask` with an identity token.

Cloud SQL bills while it runs. Stop it between sessions:

```bash
gcloud sql instances patch rag-sql --activation-policy=NEVER    # stop
gcloud sql instances patch rag-sql --activation-policy=ALWAYS   # start
```

## Evaluation

### Data

- **Corpus:** 45 public Kubernetes concept documents (about 620 KB), split into 639 chunks.
- **Eval set:** 50 questions in `data/eval.jsonl`. Each has a reference answer, a source document, and an `evidence` phrase. A script confirmed that every evidence phrase appears in its source document.

The questions were written from the corpus text, so these scores are likely optimistic. Treat them as a regression baseline, not as a measure of general quality.

### Metrics

- **Retrieval hit rate:** whether the source document appears in the citations.
- **Retrieval MRR:** mean reciprocal rank of the source document (retrieval-only check).
- **Latency:** wall-clock time per request, including network time.
- **Tokens:** prompt and output token counts reported by Gemini.
- **Accuracy:** each answer graded as correct, partial, or wrong against the reference answer.

### Results (local run)

Stack: local query service, local Postgres 16 with pgvector, `text-embedding-005` for embeddings, `gemini-3.6-flash` (global location) for answers, top-k 5.

| Metric | Result |
|---|---|
| Requests succeeded | 50 / 50 |
| p50 wall latency | 3,113 ms |
| p95 wall latency | 4,701 ms |
| Retrieval hit rate (`hit@5`) | 100% (50 / 50) |
| Retrieval MRR (`@5`) | 1.000 |
| Average input tokens | 1,557 |
| Average output tokens | 66 |
| Answer accuracy | 49 correct, 1 wrong |

The one wrong answer (question 16, the default `preemptionPolicy` of a PriorityClass) is an abstention. The model said the sources didn't contain the answer, although the retrieved document states it. Hit rate checks the document, not the chunk, so a correct document can still miss the chunk with the answer.

Grades were assigned by hand by the author of this project. Spot-check them before relying on the accuracy figure.

### Cloud run

`eval/results_gcp.csv` holds a second 50-question run: all 50 requests returned 200, p50 was 2,662 ms, p95 was 4,403 ms, and retrieval hit rate was 100%. These answers have not yet been graded, and the run is not summarized in `eval/summary_local.md`. Confirm the target URL before using these numbers for comparisons.

## Design decisions

- **pgvector on Cloud SQL, not Vertex AI Vector Search.** At this corpus size, a small Postgres instance is cheap and simple to operate, and the same SQL runs locally. Vector Search suits larger, managed-scale workloads.
- **GCS notification to Pub/Sub, not Eventarc.** The Pub/Sub subscription has a native dead-letter topic and delivery-attempt counting. Eventarc can be added later.
- **Content hashes for idempotency.** Re-uploading an unchanged file costs no embedding calls. Edited files are re-embedded, and the previous version is kept but marked stale, so behavior can be shown and compared.
- **Stale marking and inserts in one transaction.** A failed run cannot leave a document with no active chunks.
- **Parameterized SQL only.** Retrieval passes the query vector as a bound parameter (`CAST(:q AS vector)`). The query path has no string-built SQL.
- **Bounded retrieval.** `k` is validated between 1 and 10, and the question length is capped at 1,000 characters.
- **Errors are logged, not returned.** A failing query returns `500 query failed`. The traceback goes to Cloud Logging only.
- **Generation through the REST endpoint.** `gemini-3.6-flash` is served only from the `global` location. The pinned Vertex SDK rejects `global`, so the query service calls the REST endpoint directly with the same credentials. Embeddings still use the SDK in `us-central1`.
- **Chunking chosen from data.** A chunking comparison on this corpus (`docs/chunking-analysis.json`) scored sentence-based chunking at 0.68 against 0.50 for fixed-size chunks. The current build uses fixed-size chunks as the baseline, and the sentence-based variant is the next experiment.

## Known limitations

- **Scale.** `db-f1-micro` with a single zonal instance, no backups, and `deletion_protection = false`. Suitable for a test project, not for production.
- **Single-chunk retrieval.** Retrieval is pure vector similarity. There is no reranker, no keyword (hybrid) search, and no query rewriting.
- **Small, self-written eval set.** Fifty questions written from the same text the system indexes. Scores are optimistic. A held-out set written by someone else would be a stronger test.
- **Manual grading.** Accuracy was graded by hand, by the author, for one run.
- **PDF extraction.** `pypdf` extracts text but does not handle scanned PDFs (no OCR). Tables and multi-column layouts may come out garbled. Empty extraction is treated as a failure.
- **Auth.** Access is controlled by IAM only. There is no per-user authorization or rate limiting.
- **Pinned SDK.** The Vertex SDK version is pinned in `requirements.txt` and cannot address the `global` location. Generation uses a direct REST call as a workaround.
- **Push configuration not in Terraform.** The Pub/Sub push endpoint is set with `gcloud`, because the ingest service URL is only known after deployment.
- **Model names change.** `text-embedding-005` and `gemini-3.6-flash` were current when this was built. Check them in the Vertex AI console before deploying.
- **Cost.** This README does not quote prices. Compute cost per 1,000 queries from your own billing data.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `terraform` reports "No configuration files" | You ran it from the repository root. Run it from `infra/`. |
| `terraform apply tfplan` cannot find `tfplan` | Same cause. Run from `infra/`, or pass the full path. |
| Terraform reports 403 on the state bucket | Terraform is using the wrong credentials. Run `gcloud auth application-default login` with the account that owns `jaypas-001`, or set `GOOGLE_OAUTH_ACCESS_TOKEN=$(gcloud auth print-access-token)`. |
| Local Postgres: `role "rag" does not exist` | Port 5432 is taken by another Postgres (Homebrew, for example). This project uses 5433. Check the `DATABASE_URL` port. |
| Embedding call returns 403 `aiplatform.endpoints.predict` | Application-default credentials belong to an account without Vertex AI access on the project. Re-run `gcloud auth application-default login`. |
| Gemini call returns 404 "Publisher model ... not found" | The model is not available in that location for your project. `gemini-3.6-flash` needs `GEN_LOCATION=global`. |
| Ingest returns 500 with `NOT_FOUND` or a Cloud SQL error | Check the database URL (local) or `INSTANCE_CONNECTION_NAME` and `DB_USER` (cloud). |
| Pub/Sub message ends up in `ingest-jobs-dlq` | Five deliveries failed. Read the ingest logs for the traceback, fix the cause, then re-upload the file. |
