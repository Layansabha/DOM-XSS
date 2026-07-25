# Use the pipeline

[README](../README.md) · [How it works](PIPELINE.md) · [Model and research](MODEL-AND-RESEARCH.md)

> Run this project only against systems you own or are explicitly authorized to test.

## Start on Kali Linux

```bash
sudo apt update
sudo apt install -y docker.io docker-compose git openssl
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
newgrp docker

git clone https://github.com/Layansabha/DOM-XSS.git
cd DOM-XSS
cp .env.example .env
openssl rand -hex 32
```

Set the generated value as `ZAP_API_KEY` in `.env`, then start the application:

```bash
docker compose up --build -d
curl -fsS http://127.0.0.1:8000/readyz
```

Open `http://127.0.0.1:8000`.

## Scan modes

- **Auto:** treats a root URL as a bounded same-origin crawl and a URL with a path as one page.
- **Domain crawl:** follows safe same-origin links within configured limits.
- **Single page:** analyzes only the submitted page.

Leave dynamic verification disabled for ML-only triage. Enable it only for an
authorized target. A model score prioritizes review; it does not prove that a
vulnerability is exploitable.

## API

Create a scan with `POST /api/scans`, then poll the returned `status_url` until
the job finishes or fails. Interactive API documentation is available at
`http://127.0.0.1:8000/docs`.

## Diagnostics

```bash
docker compose ps
docker compose logs --no-color --tail=200 api worker redis zap
curl -i http://127.0.0.1:8000/healthz
curl -i http://127.0.0.1:8000/readyz
```

Stop the stack without deleting Redis data:

```bash
docker compose down
```

Remove the stack and its local volumes:

```bash
docker compose down -v
```

## Optional local monitoring

Prometheus, Grafana, and cAdvisor are available through a Docker Compose
override. This provides local container resource monitoring; it is not a full
observability platform.

Set `GRAFANA_ADMIN_PASSWORD` in `.env`, then run:

```bash
docker compose \
  -f compose.yaml \
  -f deploy/compose.observability.yaml \
  up --build -d
```

Default endpoints:

- application: `http://127.0.0.1:8000`
- Prometheus: `http://127.0.0.1:9090`
- Grafana: `http://127.0.0.1:3000`

cAdvisor requires privileged read access to local Docker and host metadata.
Use this override only on a trusted development machine.

## Optional VPS deployment

The VPS override adds Caddy, automatic HTTPS, and HTTP basic authentication for
a single-server deployment. The host can be created with the optional
[Hetzner Terraform reference](../infra/terraform/README.md), or prepared
manually.

Before running `./deploy/deploy.sh`, configure these values in `.env`:

```env
APP_IMAGE=ghcr.io/layansabha/dom-xss:latest
APP_DOMAIN=scan.example.com
APP_BASIC_AUTH_USER=admin
APP_BASIC_AUTH_HASH=replace-with-a-caddy-password-hash
ZAP_API_KEY=replace-with-a-random-value
```

The deployment script pulls the published images, starts the base and VPS
Compose files, and waits for the API readiness check. Applying the Terraform
configuration creates billable Hetzner resources.
