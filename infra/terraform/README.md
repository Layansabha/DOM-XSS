# Hetzner VPS Terraform reference

This directory contains an optional Terraform configuration for one Hetzner
Cloud VPS. `terraform plan` is free, while `terraform apply` creates billable
cloud resources.

The configuration demonstrates infrastructure provisioning for a small
single-server deployment. It is not a highly available or autoscaling platform.

## What it creates

- one Ubuntu 24.04 VPS
- a managed SSH public key
- a firewall that allows:
  - SSH only from the configured administration CIDRs
  - public TCP 80 and 443
  - ICMP for diagnostics and IPv6 operation
- optional paid server backups
- deletion and rebuild protection
- cloud-init configuration that:
  - creates a non-root `deploy` user
  - disables SSH password authentication and root login
  - installs Docker Engine and Docker Compose
  - enables unattended operating-system updates
  - configures bounded Docker log rotation
  - checks out an explicit release tag or commit
  - installs a systemd service for restart-on-boot behaviour

Terraform does not place application secrets in state. Runtime values such as
`ZAP_API_KEY` and the Caddy password hash remain in `.env`, which is copied to
the server over SSH.

## Requirements

- Terraform 1.14 or newer
- a Hetzner Cloud project and API token
- an SSH key pair
- a domain whose DNS records you can update

The default `cpx31` server provides 8 GB RAM and supports running Chromium and
OWASP ZAP together. ML-only deployments do not start ZAP. Review current Hetzner
pricing before applying.

## Configure

Generate a dedicated SSH key:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/domxss_hetzner
```

Create the local variable file:

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
```

Set the following values:

- `ssh_public_key`: contents of `~/.ssh/domxss_hetzner.pub`
- `admin_cidrs`: the administration IP followed by `/32` for IPv4 or `/128` for IPv6
- `repository_ref`: a release tag such as `v1.0.0` or a full commit SHA
- location, server size, IPv6, backup, and deletion-protection settings

Mutable `main` and `master` refs are rejected. This prevents a later deployment
from silently checking out different application code.

Expose the Hetzner token only through the environment:

```bash
export HCLOUD_TOKEN='replace-with-the-project-token'
```

Do not put the token in `.tf` or `.tfvars` files.

## Validate and provision

```bash
terraform init
terraform fmt -check
terraform validate
terraform test
terraform plan -out=tfplan
terraform apply tfplan
```

Review the plan before approving it. Applying the plan creates billable
resources.

Read the connection details:

```bash
terraform output
terraform output -raw ssh_command
terraform output -raw bootstrap_status_command
```

Wait for cloud-init:

```bash
ssh deploy@"$(terraform output -raw server_ipv4)" \
  'sudo cloud-init status --wait && docker compose version'
```

## Deploy a versioned image

Prepare `.env` from the repository root:

```bash
cp .env.example .env
docker run --rm caddy:2.10-alpine \
  caddy hash-password --plaintext 'choose-a-strong-password'
openssl rand -hex 32
```

Set at least:

```env
APP_IMAGE=ghcr.io/layansabha/dom-xss:v1.0.0
APP_DOMAIN=scan.example.com
APP_BASIC_AUTH_USER=admin
APP_BASIC_AUTH_HASH=replace-with-the-generated-caddy-hash
ENABLE_ZAP=false
```

The deployment script rejects `latest` and the local development image. Use a
version tag, commit tag, or digest so that deployment and rollback are
predictable.

To enable dynamic verification on the VPS, set:

```env
ENABLE_ZAP=true
ZAP_API_KEY=replace-with-the-generated-random-value
```

Copy the runtime file and deploy:

```bash
SERVER_IP="$(terraform -chdir=infra/terraform output -raw server_ipv4)"
scp .env "deploy@$SERVER_IP:/opt/dom-xss/.env"
ssh "deploy@$SERVER_IP" \
  'cd /opt/dom-xss && ./deploy/deploy.sh'
```

Point the domain's `A` record to `server_ipv4` and, when enabled, its `AAAA`
record to `server_ipv6`. Caddy obtains the TLS certificate after DNS resolves.

## Rollback

Set `APP_IMAGE` to the previous version or commit tag and run:

```bash
./deploy/deploy.sh
```

The script pulls that exact image and waits for `/readyz` before reporting a
successful deployment.

## State and teardown

Terraform state can contain infrastructure identifiers and must not be
committed. For team use, configure an encrypted remote backend with state
locking before the first apply.

Deletion protection intentionally blocks accidental teardown. To destroy the
environment:

1. set `enable_delete_protection = false`
2. run `terraform apply`
3. run `terraform destroy`
