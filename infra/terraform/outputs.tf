output "server_id" {
  description = "Hetzner Cloud server ID."
  value       = hcloud_server.app.id
}

output "server_ipv4" {
  description = "Public IPv4 address to use for the domain A record."
  value       = hcloud_server.app.ipv4_address
}

output "server_ipv6" {
  description = "Public IPv6 address to use for the domain AAAA record, when enabled."
  value       = var.enable_ipv6 ? hcloud_server.app.ipv6_address : null
}

output "ssh_command" {
  description = "Command used to connect as the non-root deployment user."
  value       = "ssh deploy@${hcloud_server.app.ipv4_address}"
}

output "bootstrap_status_command" {
  description = "Command that waits until cloud-init has completed."
  value       = "ssh deploy@${hcloud_server.app.ipv4_address} 'sudo cloud-init status --wait'"
}

output "application_directory" {
  description = "Directory containing the checked-out application on the server."
  value       = "/opt/dom-xss"
}
