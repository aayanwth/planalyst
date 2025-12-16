# =============================================================
# PLanalyst — Terraform Outputs
# =============================================================

output "postgres_connection_string" {
  description = "PostgreSQL connection string for the PLanalyst database"
  value       = "postgresql://${var.postgres_user}:${var.postgres_password}@localhost:${var.postgres_port}/${var.postgres_db}"
  sensitive   = true
}

output "container_name" {
  description = "Name of the running Postgres container"
  value       = docker_container.postgres.name
}

output "postgres_port" {
  description = "External port Postgres is listening on"
  value       = var.postgres_port
}

output "schemas_created" {
  description = "Database schemas created for the medallion architecture"
  value       = ["bronze", "silver", "gold", "training"]
}
