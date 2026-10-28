output "docs_bucket" {
  value = google_storage_bucket.docs.name
}

output "sql_connection_name" {
  value = google_sql_database_instance.rag.connection_name
}

output "ingest_service_account" {
  value = google_service_account.ingest.email
}

output "query_service_account" {
  value = google_service_account.query.email
}
