# Requires from week1 setup: var.project_id, var.region, and the
# google_service_account.ingest / google_service_account.query resources.

resource "google_sql_database_instance" "rag" {
  name                = "rag-sql"
  database_version    = "POSTGRES_16"
  region              = var.region
  deletion_protection = false # test project only

  settings {
    tier              = "db-f1-micro"
    edition           = "ENTERPRISE"
    disk_size         = 10
    availability_type = "ZONAL"

    database_flags {
      name  = "cloudsql.iam_authentication"
      value = "on"
    }

    backup_configuration {
      enabled = false # test project; enable for anything real
    }

    ip_configuration {
      ipv4_enabled = true
    }
  }
}

resource "google_sql_database" "rag" {
  name     = "rag"
  instance = google_sql_database_instance.rag.name
}

resource "google_sql_user" "rag_ingest_iam" {
  name     = "rag-ingest@${var.project_id}.iam"
  instance = google_sql_database_instance.rag.name
  type     = "CLOUD_IAM_SERVICE_ACCOUNT"
}

resource "google_sql_user" "rag_query_iam" {
  name     = "rag-query@${var.project_id}.iam"
  instance = google_sql_database_instance.rag.name
  type     = "CLOUD_IAM_SERVICE_ACCOUNT"
}

resource "google_project_iam_member" "ingest_sql" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.ingest.email}"
}

resource "google_project_iam_member" "query_sql" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.query.email}"
}
