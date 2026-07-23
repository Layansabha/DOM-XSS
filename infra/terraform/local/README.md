# Free local Terraform deployment

This stack provides a fully local, zero-cloud-cost deployment for the DOM XSS
pipeline. Terraform controls the lifecycle, Docker Compose remains the
application runtime definition, and the optional observability layer adds
Prometheus, Grafana, and cAdvisor.

No cloud account, domain, payment card, or remote Terraform service is required.

## What Terraform manages

- repeatable `apply` and `destroy` lifecycle around the Compose application
- configuration-change detection through file hashes
- local application image builds
- Redis persistence
- OWASP ZAP and Chromium worker services
- loopback-only Prometheus and Grafana endpoints
- a provisioned Grafana datasource and container-resource dashboard
- generated local ZAP and Grafana secrets kept in `.env`, outside Terraform state

The local stack intentionally uses the built-in `terraform_data` resource
instead of duplicating the Compose services in a second container definition.

## Requirements

- Terraform 1.14 or newer
- Docker Engine
- Docker Compose v2
- OpenSSL
- at least 6 GB of available RAM when ZAP is enabled
- Linux for the cAdvisor host mounts; Kali Linux is supported

## Deploy

From the repository root:

```bash
cp infra/terraform/local/terraform.tfvars.example \
  infra/terraform/local/terraform.tfvars

terraform -chdir=infra/terraform/local init
terraform -chdir=infra/terraform/local fmt -check
terraform -chdir=infra/terraform/local validate
terraform -chdir=infra/terraform/local test
terraform -chdir=infra/terraform/local plan
terraform -chdir=infra/terraform/local apply
```

The first apply creates `.env` from `.env.example` when needed and replaces the
placeholder ZAP and Grafana passwords with random local values. The secrets are
not stored in Terraform state.

Default endpoints:

| Service | URL |
|---|---|
| DOM XSS application | `http://127.0.0.1:8000` |
| Prometheus | `http://127.0.0.1:9090` |
| Grafana | `http://127.0.0.1:3000` |

The Grafana username and generated password are in `.env`.

## Makefile shortcuts

```bash
make tf-local-plan
make tf-local-apply
make tf-local-output
make tf-local-destroy
```

## Configuration

Edit `infra/terraform/local/terraform.tfvars` to change ports, disable
observability, skip image builds, or choose whether `terraform destroy` also
deletes persistent volumes.

```hcl
enable_observability = true
build_images         = true
destroy_volumes      = false

app_port        = 8000
prometheus_port = 9090
grafana_port    = 3000
```

`destroy_volumes = false` is the safer default because Redis scan results and
monitoring history survive a normal teardown.

## Destroy

```bash
terraform -chdir=infra/terraform/local destroy
```

To remove persistent Docker volumes as well:

```hcl
destroy_volumes = true
```

Apply that configuration once, then run `terraform destroy`.

## Security scope

All web ports bind to `127.0.0.1`. Redis, ZAP, and cAdvisor are not published to
the host. cAdvisor requires privileged read access to Linux host and Docker
metadata, so this observability override is intended for a trusted local
development machine only, not a shared or internet-facing server.

The paid Hetzner reference architecture remains available one directory above
for demonstrating a cloud deployment design without running it.
