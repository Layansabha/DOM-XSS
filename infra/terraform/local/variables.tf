variable "env_file" {
  description = "Environment file path relative to the repository root."
  type        = string
  default     = ".env"

  validation {
    condition     = !startswith(var.env_file, "/") && !strcontains(var.env_file, "..")
    error_message = "env_file must be a safe path relative to the repository root."
  }
}

variable "enable_observability" {
  description = "Start the local Prometheus, Grafana, and cAdvisor stack."
  type        = bool
  default     = true
}

variable "build_images" {
  description = "Build the application image before starting the local stack."
  type        = bool
  default     = true
}

variable "destroy_volumes" {
  description = "Remove Redis, Prometheus, and Grafana volumes during terraform destroy."
  type        = bool
  default     = false
}

variable "app_port" {
  description = "Loopback port used by the DOM XSS web application."
  type        = number
  default     = 8000

  validation {
    condition     = var.app_port >= 1024 && var.app_port <= 65535
    error_message = "app_port must be between 1024 and 65535."
  }
}

variable "prometheus_port" {
  description = "Loopback port used by Prometheus."
  type        = number
  default     = 9090

  validation {
    condition     = var.prometheus_port >= 1024 && var.prometheus_port <= 65535
    error_message = "prometheus_port must be between 1024 and 65535."
  }
}

variable "grafana_port" {
  description = "Loopback port used by Grafana."
  type        = number
  default     = 3000

  validation {
    condition     = var.grafana_port >= 1024 && var.grafana_port <= 65535
    error_message = "grafana_port must be between 1024 and 65535."
  }
}
