# Use the pipeline

[README](../README.md) · [How it works](PIPELINE.md) · [Model and research](MODEL-AND-RESEARCH.md)

> Run this project only against systems you own or are explicitly authorized to test.

## Start on Kali Linux

```bash
sudo apt update
sudo apt install -y docker.io docker-compose git
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
newgrp docker

git clone https://github.com/Layansabha/DOM-XSS.git
cd DOM-XSS
cp .env.example .env
```

Start the default ML-only stack:

```bash
docker compose up --build -d --remove-orphans
docker compose ps
curl -fsS http://127.0.0.1:8000/readyz
```

Open `http://127.0.0.1:8000`.

The default stack does not download or run ZAP. For authorized dynamic
verification, generate an API key, set it as `ZAP_API_KEY` in `.env`, and start
the optional override:

```bash
openssl rand -hex 32
docker compose -f compose.yaml -f deploy/compose/zap.yaml up --build -d --remove-orphans
```

Later starts reuse the local images.

### Upgrade an existing checkout

Pull the current code, keep the existing `.env`, and rebuild the application
image:

```bash
git pull --ff-only
docker compose down --remove-orphans
docker compose up --build -d --remove-orphans
curl -fsS http://127.0.0.1:8000/readyz
```

Existing `.env` files that still use
`/app/artifacts/lightgbm_model.txt` and
`/app/artifacts/vocab_top500_filtered.json` are migrated to the grouped
artifact paths by the application. New installations should use the paths in
`.env.example`.

## Scan modes

| Mode | Behaviour |
|---|---|
| `Auto` | Treats a root URL as a bounded same-origin crawl and a URL with a path as one page. |
| `Domain crawl` | Follows safe same-origin links within configured page and depth limits. |
| `Single page` | Analyses only the submitted page. |

The dynamic-verification checkbox is disabled in ML-only mode. It becomes
available when the ZAP override is running. Enable it only for an authorized
target. A model score prioritizes review; it does not prove that a vulnerability
is exploitable or that a page is safe.

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

## Command-line client

The application image installs the `domxss` CLI. Use it from the running API
container:

```bash
docker compose exec -T api domxss health

docker compose exec -T api domxss scan \
  https://example.com/path \
  --scope page
```

The scan command waits by default and prints progress to standard error followed
by a compact result table. Available workflows include:

```bash
# Submit now and inspect the job later.
docker compose exec -T api domxss scan \
  https://example.com/path \
  --scope page \
  --detach

docker compose exec -T api domxss status JOB_ID --wait

# JSON output for jq, CI, or another program.
docker compose exec -T api domxss scan \
  https://example.com/path \
  --scope page \
  --json

# Opt in to exit status 2 when a page is marked high priority.
docker compose exec -T api domxss scan \
  https://example.com/path \
  --scope page \
  --fail-on-high-risk
```

`--verify` requests ZAP analysis and is rejected unless the ZAP override is
running. `--api-url` can target another deployment when the package is installed
on the host. Exit status `1` indicates an operational failure; the default scan
exit status remains `0` even when ML produces a high-risk triage signal.

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

If `/readyz` returns `503`, check the API logs before submitting a scan:

```bash
docker compose logs --no-color --tail=100 api
docker compose exec -T worker python -c \
  'from app.services.ml import get_model_service; model=get_model_service(); print(model.model.num_feature(), len(model.vocabulary))'
```

A valid bundled model prints `500 500`.

## Structured logs

Application logs are written as JSON to stdout. Important fields include:

- `request_id`
- `job_id`
- `stage`
- `status`
- `duration_ms` or `duration_seconds`
- `request_host`
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

Use `make monitor-up-zap` when both monitoring and ZAP are required.

Default endpoints:

- application: `http://127.0.0.1:8000`
- Prometheus: `http://127.0.0.1:9090`
- Grafana: `http://127.0.0.1:3000`

The provisioned **DOM XSS Operations** dashboard focuses on application
behaviour rather than generic container CPU graphs. The monitoring override
does not require a privileged cAdvisor container.

## End-to-end operational test

The repository includes an isolated local target used only for automated tests.
The end-to-end test starts the API, worker, Redis, and the local target, submits
a real asynchronous scan, waits for completion, checks the result, and verifies
the metrics endpoint.

```bash
make e2e
```

The GitHub Actions workflow runs the same type of test after building the
container image. On failure, it prints service status and the relevant Compose
logs before cleanup. The local command also removes its isolated containers and
volumes when it exits.

## Diagnostics

```bash
docker compose ps
docker compose logs --no-color --tail=200 api worker redis
curl -i http://127.0.0.1:8000/healthz
curl -i http://127.0.0.1:8000/readyz
curl -fsS http://127.0.0.1:8000/metrics | head
```

When the ZAP override is running, inspect it with:

```bash
docker compose -f compose.yaml -f deploy/compose/zap.yaml logs --tail=200 zap
```

Stop the application and any optional ZAP or monitoring services:

```bash
make down
```

## CI and image versions

Pull requests run:

1. bundled-model integrity verification, Ruff, mypy, pytest, and pip-audit
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
ENABLE_ZAP=false
```

The deployment script rejects `latest` and the local development image. It
pulls the configured version, starts the base and VPS Compose files, and waits
for `/readyz`. Set `ENABLE_ZAP=true` and configure `ZAP_API_KEY` only when the
VPS should provide dynamic verification.

To roll back, set `APP_IMAGE` to the previous release or commit tag and run the
deployment script again.
