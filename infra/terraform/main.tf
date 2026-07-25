locals {
  resource_name = "${var.project_name}-${var.environment}"
  common_labels = {
    application = var.project_name
    environment = var.environment
    managed_by  = "terraform"
  }
}

resource "hcloud_ssh_key" "admin" {
  name       = "${local.resource_name}-admin"
  public_key = trimspace(var.ssh_public_key)
  labels     = local.common_labels
}

resource "hcloud_firewall" "app" {
  name   = "${local.resource_name}-firewall"
  labels = local.common_labels

  dynamic "rule" {
    for_each = toset(var.admin_cidrs)

    content {
      direction   = "in"
      protocol    = "tcp"
      port        = "22"
      source_ips  = [rule.value]
      description = "Restricted SSH administration"
    }
  }

  rule {
    direction   = "in"
    protocol    = "tcp"
    port        = "80"
    source_ips  = ["0.0.0.0/0", "::/0"]
    description = "HTTP for Caddy certificate issuance and redirect"
  }

  rule {
    direction   = "in"
    protocol    = "tcp"
    port        = "443"
    source_ips  = ["0.0.0.0/0", "::/0"]
    description = "HTTPS application traffic"
  }

  rule {
    direction   = "in"
    protocol    = "icmp"
    source_ips  = ["0.0.0.0/0", "::/0"]
    description = "Network diagnostics and IPv6 neighbor discovery"
  }
}

resource "hcloud_server" "app" {
  name        = local.resource_name
  server_type = var.server_type
  image       = var.server_image
  location    = var.location

  ssh_keys     = [hcloud_ssh_key.admin.id]
  firewall_ids = [hcloud_firewall.app.id]
  backups      = var.enable_backups

  delete_protection  = var.enable_delete_protection
  rebuild_protection = var.enable_delete_protection

  public_net {
    ipv4_enabled = true
    ipv6_enabled = var.enable_ipv6
  }

  user_data = templatefile("${path.module}/cloud-init.yaml.tftpl", {
    repository_url_b64 = base64encode(var.repository_url)
    repository_ref_b64 = base64encode(var.repository_ref)
    ssh_public_key     = jsonencode(trimspace(var.ssh_public_key))
  })

  labels = local.common_labels
}
