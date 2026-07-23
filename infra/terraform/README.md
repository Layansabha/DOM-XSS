# Hetzner Cloud Terraform deployment

This stack provisions the production host used by the DOM XSS pipeline. It
creates a Hetzner Cloud server, restricted network firewall, managed SSH key,
and cloud-init bootstrap for Docker Engine and Docker Compose.

Terraform does **not** deploy application secrets. Values such as
`ZAP_API_KEY` and the Caddy password hash stay outside Terraform state and are
copied to the server only after provisioning.

## Provisioned resources

- Ubuntu 24.04 VPS with configurable location and server type
- IPv4 and optional IPv6
- Hetzner Cloud firewall:
  - SSH only from `admin_cidrs`
  - public HTTP, HTTPS, and HTTP/3
  - ICMP for diagnostics and required IPv6 behavior
- Hetzner-managed SSH public key
- optional paid server backups
- server deletion and rebuild protection
- cloud-init bootstrap that:
  - creates a non-root `deploy` user
  - disables SSH passwords and root login
  - installs Docker from Docker's official Ubuntu repository
  - enables unattended operating-system upgrades
  - configures bounded Docker log rotation
  - checks out the requested repository revision in `/opt/dom-xss`
  - installs a systemd unit for restart-on-boot behavior

The default `cpx31` size provides 8 GB RAM, which is the practical minimum for
running Chromium and OWASP ZAP together. Choose a smaller server only when ZAP
verification is disabled.

## Requirements

- Terraform 1.14 or newer
- a Hetzner Cloud project and read/write API token
- an SSH key pair
- a domain whose DNS records you can update

Create a dedicated SSH key:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/domxss_hetzner
```

## Configure

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
```

Edit `terraform.tfvars`:

- replace `ssh_public_key` with the contents of
  `~/.ssh/domxss_hetzner.pub`
- replace `admin_cidrs` with your public administration IP followed by `/32`
- review the selected location, server size, backup setting, and repository ref

Expose the Hetzner token as an environment variable. Do not write it in a
`.tf` or `.tfvars` file:

```bash
export HCLOUD_TOKEN='replace-with-the-project-token'
```

## Validate and provision

```bash
terraform init
terraform fmt -check
terraform validate
terraform test
terraform plan -out=tfplan
terraform apply tfplan
```

`terraform apply` creates billable Hetzner resources. Review the plan before
approving it.

Read the connection details:

```bash
terraform output
terraform output -raw ssh_command
terraform output -raw bootstrap_status_command
```

Wait for the bootstrap to finish:

```bash
ssh deploy@"$(terraform output -raw server_ipv4)" \
  'sudo cloud-init status --wait && docker compose version'
```

## Configure and start the application

From the repository root, prepare the runtime file locally:

```bash
cp .env.example .env
docker run --rm caddy:2.10-alpine \
  caddy hash-password --plaintext 'choose-a-strong-password'
openssl rand -hex 32
```

Set at least `APP_DOMAIN`, `APP_BASIC_AUTH_USER`,
`APP_BASIC_AUTH_HASH`, and `ZAP_API_KEY` in `.env`. Then copy the file over the
encrypted SSH connection and deploy. The deployment script restricts the
runtime file to its owner before starting the stack:

```bash
SERVER_IP="$(terraform -chdir=infra/terraform output -raw server_ipv4)"
scp .env "deploy@$SERVER_IP:/opt/dom-xss/.env"
ssh "deploy@$SERVER_IP" \
  'cd /opt/dom-xss && ./deploy/deploy.sh'
```

Point the domain's `A` record to `server_ipv4` and, when enabled, its `AAAA`
record to `server_ipv6`. Caddy obtains the TLS certificate after DNS resolves.

The enabled `dom-xss.service` starts the Compose stack automatically on later
server boots once `/opt/dom-xss/.env` exists.

## State and teardown

Terraform state can contain infrastructure identifiers and must not be
committed. This repository ignores local state and variable files. For a team
deployment, configure an encrypted remote backend with locking before the
first apply.

Deletion protection intentionally blocks accidental teardown. To destroy the
environment:

1. set `enable_delete_protection = false`
2. run `terraform apply`
3. run `terraform destroy`
