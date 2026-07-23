locals {
  repository_root = abspath("${path.module}/../../..")
  env_file        = abspath("${local.repository_root}/${var.env_file}")

  core_files = [
    "${local.repository_root}/compose.yaml",
    "${local.repository_root}/Dockerfile",
  ]

  observability_files = [
    "${local.repository_root}/deploy/compose.observability.yaml",
    "${local.repository_root}/deploy/monitoring/prometheus.yml",
    "${local.repository_root}/deploy/monitoring/grafana/provisioning/datasources/prometheus.yml",
    "${local.repository_root}/deploy/monitoring/grafana/provisioning/dashboards/default.yml",
    "${local.repository_root}/deploy/monitoring/grafana/dashboards/dom-xss-containers.json",
  ]

  watched_files = concat(
    local.core_files,
    var.enable_observability ? local.observability_files : [],
  )
}

resource "terraform_data" "local_stack" {
  input = {
    repository_root      = local.repository_root
    env_file             = local.env_file
    enable_observability = var.enable_observability
    build_images         = var.build_images
    destroy_volumes      = var.destroy_volumes
    app_port             = var.app_port
    prometheus_port      = var.prometheus_port
    grafana_port         = var.grafana_port
  }

  triggers_replace = [
    for file in local.watched_files : filesha256(file)
  ]

  lifecycle {
    precondition {
      condition     = alltrue([for file in local.watched_files : fileexists(file)])
      error_message = "One or more local deployment files are missing."
    }
  }

  provisioner "local-exec" {
    command = "${path.module}/scripts/apply.sh"

    environment = {
      REPOSITORY_ROOT      = self.input.repository_root
      ENV_FILE             = self.input.env_file
      ENABLE_OBSERVABILITY = tostring(self.input.enable_observability)
      BUILD_IMAGES         = tostring(self.input.build_images)
      APP_PORT             = tostring(self.input.app_port)
      PROMETHEUS_PORT      = tostring(self.input.prometheus_port)
      GRAFANA_PORT         = tostring(self.input.grafana_port)
    }
  }

  provisioner "local-exec" {
    when    = destroy
    command = "${self.input.repository_root}/infra/terraform/local/scripts/destroy.sh"

    environment = {
      REPOSITORY_ROOT      = self.input.repository_root
      ENV_FILE             = self.input.env_file
      ENABLE_OBSERVABILITY = tostring(self.input.enable_observability)
      DESTROY_VOLUMES      = tostring(self.input.destroy_volumes)
      APP_PORT             = tostring(self.input.app_port)
      PROMETHEUS_PORT      = tostring(self.input.prometheus_port)
      GRAFANA_PORT         = tostring(self.input.grafana_port)
    }
  }
}
