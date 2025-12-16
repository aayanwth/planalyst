# =============================================================
# PLanalyst — Terraform Variables
# =============================================================

variable "postgres_user" {
  description = "PostgreSQL superuser name"
  type        = string
  default     = "planalyst"
}

variable "postgres_password" {
  description = "PostgreSQL superuser password"
  type        = string
  default     = "planalyst_dev"
  sensitive   = true
}

variable "postgres_db" {
  description = "PostgreSQL database name"
  type        = string
  default     = "planalyst"
}

variable "postgres_port" {
  description = "External port to expose PostgreSQL on"
  type        = number
  default     = 5432
}

variable "container_name" {
  description = "Name of the Docker container"
  type        = string
  default     = "planalyst-postgres"
}
