output "application_url" {
  description = "Local DOM XSS application URL."
  value       = "http://127.0.0.1:${var.app_port}"
}

output "prometheus_url" {
  description = "Local Prometheus URL when observability is enabled."
  value       = var.enable_observability ? "http://127.0.0.1:${var.prometheus_port}" : null
}

output "grafana_url" {
  description = "Local Grafana URL when observability is enabled."
  value       = var.enable_observability ? "http://127.0.0.1:${var.grafana_port}" : null
}

output "environment_file" {
  description = "Runtime environment file used outside Terraform state."
  value       = local.env_file
}
