run "default_free_local_stack" {
  command = plan

  assert {
    condition     = terraform_data.local_stack.input.enable_observability
    error_message = "Observability must be enabled by default for the local DevOps stack."
  }

  assert {
    condition     = terraform_data.local_stack.input.build_images
    error_message = "The local stack must build the application image by default."
  }

  assert {
    condition     = output.application_url == "http://127.0.0.1:8000"
    error_message = "The default application URL must stay loopback-only."
  }

  assert {
    condition     = output.grafana_url == "http://127.0.0.1:3000"
    error_message = "The default Grafana URL must stay loopback-only."
  }
}

run "observability_can_be_disabled" {
  command = plan

  variables {
    enable_observability = false
  }

  assert {
    condition     = output.prometheus_url == null && output.grafana_url == null
    error_message = "Monitoring URLs must be null when observability is disabled."
  }
}

run "privileged_port_is_rejected" {
  command = plan

  variables {
    app_port = 80
  }

  expect_failures = [var.app_port]
}
