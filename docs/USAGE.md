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
docker compose ps
curl -fsS http://127.0.0.1:8000/readyz
```

Open `http://127.0.0.1:8000`.

The first startup downloads the application dependencies, Chromium, Redis,
OWASP ZAP 2.17.0, and the pinned model artifacts. Later starts reuse the local
images.

## Scan modes

| Mode | Behaviour |
|---|---|
| `Auto` | Treats a root URL as a bounded same-origin crawl and a URL with a path as one page. |
| `Domain crawl` | Follows safe same-origin links within configured page and depth limits. |
| `Single page` | Analyses only the submitted page. |

Leave dynamic verification disabled for ML-only triage. Enable it only for an
authorized target. A model score prioritizes review; it does not prove that a
vulnerability is exploitable or that a page is safe.

## API

Create a single-page ML-only scan:

```bash
curl -fsS -X POST http://127.0.0.1:8000/api/scans \
  -H 'Content-Type: application/json' \
  -d '{
    "target_url": "https://example.com/path",
    "scope_mode": "page",
    "dynamic_verification": false
  }'
```

The API returns `202 Accepted`, a job ID, and a `status_url`. Poll that URL until
the state becomes `finished` or `failed`. Interactive API documentation is
available at `http://127.0.0.1:8000/docs`.

The API process does not perform the scan directly. It validates the request,
places a job in Redis, and returns immediately. The RQ worker performs browser
collection, ML inference, and optional ZAP verification.

## Health and readiness

```bash
curl -i http://127.0.0.1:8000/healthz
curl -i http://127.0.0.1:8000/readyz
```

- `/healthz` confirms that the API process responds.
- `/readyz` also checks Redis and the ML model.
- the worker container has its own health check that verifies Redis access and
  confirms that the RQ process is running.

A healthy API does not by itself prove that scans are being processed. Check the
worker health and queue depth when troubleshooting delayed jobs.

## Structured logs

Application logs are written as JSON to stdout. Important fields include:

- `request_id`
- `job_id`
- `stage`
- `status`
- `duration_ms` or `duration_seconds`
- `target_host`
- `error_type`

Use Docker Compose to inspect them:

```bash
docker compose logs --no-color --tail=200 api
docker compose logs --no-color --tail=200 worker
```

The API also returns an `X-Request-ID` response header. A supplied
`X-Request-ID` is preserved, which allows a request to be correlated with API
logs.

## Operational metrics

The application exposes Prometheus metrics at:

```text
http://127.0.0.1:8000/metrics
```

Key metrics include:

- HTTP request rate and latency
- Redis metrics availability
- queue depth
- registered RQ workers
- scans queued, completed, and failed
- pages collected
- failed ZAP runs
- total and average scan duration

Start Prometheus and Grafana:

```bash
make monitor-up
```

Default endpoints:

- application: `http://127.0.0.1:8000`
- Prometheus: `http://127.0.0.1:9090`
- Grafana: `http://127.0.0.1:3000`

The provisioned **DOM XSS Operations** dashboard focuses on application
behaviour rather than generic container CPU graphs. The monitoring override
does not require a privileged cAdvisor container.

Stop monitoring without deleting its stored history:

```bash
make monitor-down
```

## End-to-end operational test

The repository includes an isolated local target used only for automated tests.
The end-to-end test starts the API, worker, Redis, and the local target, submits
a real asynchronous scan, waits for completion, checks the result, and verifies
the metrics endpoint.

```bash
make e2e
make e2e-down
```

The GitHub Actions workflow runs the same type of test after building the
container image. On failure, it prints service status and the relevant Compose
logs before cleanup.

## Diagnostics

```bash
docker compose ps
docker compose logs --no-color --tail=200 api worker redis zap
curl -i http://127.0.0.1:8000/healthz
curl -i http://127.0.0.1:8000/readyz
curl -fsS http://127.0.0.1:8000/metrics | head
```

Stop the stack without deleting Redis data:

```bash
docker compose down
```

Remove the stack and local volumes:

```bash
docker compose down -v
```

## CI and image versions

Pull requests run:

1. Ruff, mypy, pytest, and pip-audit
2. Terraform format, validation, and tests
3. Compose configuration validation
4. application image build
5. model and RQ smoke tests
6. the end-to-end asynchronous scan
7. Trivy image scanning

Merges to `main` publish `latest` and a commit-based `sha-*` image tag. Git tags
matching `v*` also publish semantic-version tags such as `v1.0.0` and `1.0`.
Deployments should use a version or commit tag, not `latest`.

## Optional VPS deployment

The VPS override adds Caddy, automatic HTTPS, and HTTP basic authentication for
a single-server deployment. The host can be created with the optional
[Hetzner Terraform reference](../infra/terraform/README.md), or prepared
manually.

Before running `./deploy/deploy.sh`, configure at least:

```env
APP_IMAGE=ghcr.io/layansabha/dom-xss:v1.0.0
APP_DOMAIN=scan.example.com
APP_BASIC_AUTH_USER=admin
APP_BASIC_AUTH_HASH=replace-with-a-caddy-password-hash
ZAP_API_KEY=replace-with-a-random-value
```

The deployment script rejects `latest` and the local development image. It
pulls the configured version, starts the base and VPS Compose files, and waits
for `/readyz`.

To roll back, set `APP_IMAGE` to the previous release or commit tag and run the
deployment script again.
