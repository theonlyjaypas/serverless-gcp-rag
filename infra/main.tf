data "google_project" "this" {}

locals {
  pubsub_sa = "service-${data.google_project.this.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
  gcs_sa    = "service-${data.google_project.this.number}@gs-project-accounts.iam.gserviceaccount.com"
}

# ---------- Service accounts ----------

resource "google_service_account" "ingest" {
  account_id   = "rag-ingest"
  display_name = "RAG ingest worker"
}

resource "google_service_account" "query" {
  account_id   = "rag-query"
  display_name = "RAG query API"
}

# ---------- Storage ----------

resource "google_storage_bucket" "docs" {
  name                        = "${var.project_id}-docs"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = true # test project only
  public_access_prevention    = "enforced"
}

resource "google_storage_bucket_iam_member" "ingest_read_docs" {
  bucket = google_storage_bucket.docs.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.ingest.email}"
}

# ---------- Pub/Sub ----------

resource "google_pubsub_topic" "ingest_jobs" {
  name = "ingest-jobs"
}

resource "google_pubsub_topic" "ingest_dlq" {
  name = "ingest-jobs-dlq"
}

resource "google_pubsub_subscription" "ingest_dlq_sub" {
  name                 = "ingest-jobs-dlq-sub"
  topic                = google_pubsub_topic.ingest_dlq.name
  ack_deadline_seconds = 60
}

resource "google_pubsub_subscription" "ingest_jobs_sub" {
  name                 = "ingest-jobs-sub"
  topic                = google_pubsub_topic.ingest_jobs.name
  ack_deadline_seconds = 300 # ingest can take a while on large PDFs

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.ingest_dlq.id
    max_delivery_attempts = 5
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "300s"
  }

  # The push endpoint is set with gcloud after rag-ingest is deployed (plan 2.8).
  lifecycle {
    ignore_changes = [push_config]
  }
}

# Pub/Sub must be able to forward failed messages to the DLQ and ack from the source.
resource "google_pubsub_topic_iam_member" "dlq_publisher" {
  topic  = google_pubsub_topic.ingest_dlq.name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${local.pubsub_sa}"
}

resource "google_pubsub_subscription_iam_member" "jobs_sub_subscriber" {
  subscription = google_pubsub_subscription.ingest_jobs_sub.name
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:${local.pubsub_sa}"
}

# GCS must be able to publish OBJECT_FINALIZE events to the ingest topic (plan 2.1).
resource "google_pubsub_topic_iam_member" "gcs_publisher" {
  topic  = google_pubsub_topic.ingest_jobs.name
  role   = "roles/pubsub.publisher"
  member = "serviceAccount:${local.gcs_sa}"
}

# The GCS notification itself is created with gcloud (plan 2.1), so it is not
# managed here; the bucket is still managed by Terraform above.
