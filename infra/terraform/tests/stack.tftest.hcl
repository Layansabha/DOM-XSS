mock_provider "hcloud" {}

run "production_stack" {
  command = plan

  variables {
    ssh_public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBXiDBuwYCWjPsmyiMtCL0zMRppyj4cW/25jr9Hosqom dom-xss-terraform-test"
    admin_cidrs    = ["198.51.100.42/32"]
  }

  assert {
    condition     = hcloud_server.app.name == "dom-xss-production"
    error_message = "The default resource name must identify the application and environment."
  }

  assert {
    condition     = hcloud_server.app.server_type == "cpx31"
    error_message = "The default server must provide enough memory for Chromium and ZAP."
  }

  assert {
    condition     = length(hcloud_server.app.firewall_ids) == 1
    error_message = "The application server must have the managed firewall attached."
  }

  assert {
    condition     = strcontains(hcloud_server.app.user_data, "PasswordAuthentication no")
    error_message = "The rendered cloud-init configuration must disable SSH passwords."
  }

  assert {
    condition     = strcontains(hcloud_server.app.user_data, "/opt/dom-xss")
    error_message = "The rendered cloud-init configuration must prepare the application directory."
  }
}

run "invalid_admin_network_is_rejected" {
  command = plan

  variables {
    ssh_public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBXiDBuwYCWjPsmyiMtCL0zMRppyj4cW/25jr9Hosqom dom-xss-terraform-test"
    admin_cidrs    = ["0.0.0.0/33"]
  }

  expect_failures = [var.admin_cidrs]
}

run "world_open_ssh_is_rejected" {
  command = plan

  variables {
    ssh_public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBXiDBuwYCWjPsmyiMtCL0zMRppyj4cW/25jr9Hosqom dom-xss-terraform-test"
    admin_cidrs    = ["0.0.0.0/0"]
  }

  expect_failures = [var.admin_cidrs]
}
