# =============================================================
# PLanalyst — Terraform: Provision PostgreSQL with pgvector
# =============================================================
# Uses the kreuzwerker/docker provider to run a local
# pgvector-enabled Postgres container.
# =============================================================

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    docker = {
      source  = "kreuzwerker/docker"
      version = "~> 3.0"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.0"
    }
  }
}

provider "docker" {}

# --- Pull the pgvector image (Postgres 17 + vector extension) ---
resource "docker_image" "pgvector" {
  name         = "pgvector/pgvector:pg17"
  keep_locally = true
}

# --- Create a persistent volume for Postgres data ---
resource "docker_volume" "pgdata" {
  name = "planalyst_pgdata"
}

# --- Run the Postgres container ---
resource "docker_container" "postgres" {
  name  = var.container_name
  image = docker_image.pgvector.image_id

  ports {
    internal = 5432
    external = var.postgres_port
  }

  env = [
    "POSTGRES_USER=${var.postgres_user}",
    "POSTGRES_PASSWORD=${var.postgres_password}",
    "POSTGRES_DB=${var.postgres_db}",
  ]

  volumes {
    volume_name    = docker_volume.pgdata.name
    container_path = "/var/lib/postgresql/data"
  }

  restart = "unless-stopped"

  # Health check to wait for Postgres to be ready
  healthcheck {
    test         = ["CMD-SHELL", "pg_isready -U ${var.postgres_user} -d ${var.postgres_db}"]
    interval     = "5s"
    timeout      = "5s"
    retries      = 10
    start_period = "10s"
  }
}

# --- Enable pgvector and create schemas after container is ready ---
resource "null_resource" "setup_extensions" {
  depends_on = [docker_container.postgres]

  provisioner "local-exec" {
    command = <<-EOT
      echo "Waiting for Postgres to be ready..."
      timeout 30 bash -c 'until docker exec ${var.container_name} pg_isready -U ${var.postgres_user} -d ${var.postgres_db}; do sleep 2; done' 2>/dev/null || powershell -Command "Start-Sleep -Seconds 15"
      
      echo "Enabling pgvector extension..."
      docker exec ${var.container_name} psql -U ${var.postgres_user} -d ${var.postgres_db} -c "CREATE EXTENSION IF NOT EXISTS vector;"
      
      echo "Creating schemas..."
      docker exec ${var.container_name} psql -U ${var.postgres_user} -d ${var.postgres_db} -c "CREATE SCHEMA IF NOT EXISTS bronze;"
      docker exec ${var.container_name} psql -U ${var.postgres_user} -d ${var.postgres_db} -c "CREATE SCHEMA IF NOT EXISTS silver;"
      docker exec ${var.container_name} psql -U ${var.postgres_user} -d ${var.postgres_db} -c "CREATE SCHEMA IF NOT EXISTS gold;"
      docker exec ${var.container_name} psql -U ${var.postgres_user} -d ${var.postgres_db} -c "CREATE SCHEMA IF NOT EXISTS training;"
      
      echo "Postgres setup complete!"
    EOT
  }
}
