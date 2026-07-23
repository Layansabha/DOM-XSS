# Use the pipeline

[README](../README.md) · [How it works](PIPELINE.md) · [Model and research](MODEL-AND-RESEARCH.md)

## 1. Start it on Kali Linux

```bash
sudo apt update
sudo apt install -y docker.io docker-compose git openssl
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
newgrp docker

git clone https://github.com/Layansabha/DOM-XSS.git
cd DOM-XSS
cp .env.example .env
```

Generate a ZAP API key:

```bash
openssl rand -hex 32
```

Open `.env`, set the generated value as `ZAP_API_KEY`, then start the stack:

```bash
docker compose up --build -d
docker compose ps
docker compose logs --tail=100 api worker redis zap
```

Wait until the application is ready:

```bash
curl -fsS http://127.0.0.1:8000/readyz
```

Open `http://127.0.0.1:8000`.

## 2. Choose the target and scope

Enter a complete `http://` or `https://` URL.

| Scope | Behavior |
|---|---|
| `Auto` | A root URL such as `https://example.com/` becomes a domain scan. A URL with a non-root path becomes a single-page scan. |
| `Domain crawl` | Starts at the submitted URL and follows safe, same-origin links up to `MAX_PAGES` and `MAX_CRAWL_DEPTH`. |
| `Single page` | Renders and analyzes only the submitted page. |

Subdomains are different origins. A scan of `https://example.com` does not
automatically include `https://app.example.com`.

## 3. Choose whether to run ZAP

Leave **Run open-source OWASP ZAP dynamic analysis** unchecked for ML-only
triage. This is faster and does not send active test payloads.

Check it only for an authorized target. ZAP runs its Client Spider and
DOM-XSS-focused active rule after the ML stage. Dynamic verification is slower
and may change application state like any active security scanner.

## 4. Start and read the scan

Select **Start analysis**. The job moves through:

1. `queued`
2. page collection
3. ML scoring
4. optional ZAP verification
5. `finished` or `failed`

Each page reports:

| Field | Meaning |
|---|---|
| Collection status | `Complete`, `Partial scan`, or `Collection failed`. |
| ML score | Ranking score of the highest-scoring code unit on the page. It is not exploit probability. |
| High/low priority | Whether the highest score crossed `ML_THRESHOLD`. |
| Feature coverage | Fraction of extracted AST-token occurrences found in the model vocabulary. |
| Scored units | Code units with at least one vocabulary match, out of all extracted units. |
| Top matched features | Vocabulary terms present in the riskiest unit; these are context, not a vulnerability explanation. |
| Client-side detection | ZAP client-side evidence that still needs reproduction. |
| Actively confirmed | ZAP active rule `40026` returned reproducible scanner evidence. |

A low score does not prove that a page is safe. A high score is a triage
candidate until supported by dynamic evidence.

## API usage

Create an ML-only single-page scan:

```bash
response="$(
  curl -fsS -X POST http://127.0.0.1:8000/api/scans \
    -H 'Content-Type: application/json' \
    -d '{
      "target_url": "https://example.com/path",
      "scope_mode": "page",
      "dynamic_verification": false
    }'
)"
printf '%s\n' "$response"
```

The response contains `status_url`. Poll it until `state` becomes `finished`
or `failed`:

```bash
curl -fsS http://127.0.0.1:8000/api/scans/JOB_ID
```

Use `"scope_mode": "domain"` for a domain crawl and set
`"dynamic_verification": true` for authorized ZAP analysis.

## Stop or reset

Stop the containers without deleting Redis data:

```bash
docker compose down
```

Delete the stack and queued/result data:

```bash
docker compose down -v
```

## Fast diagnostics

```bash
docker compose ps
docker compose logs --no-color --tail=200 api
docker compose logs --no-color --tail=200 worker
docker compose logs --no-color --tail=200 redis
docker compose logs --no-color --tail=200 zap
curl -i http://127.0.0.1:8000/healthz
curl -i http://127.0.0.1:8000/readyz
```

The first build is large because it downloads Chromium, OWASP ZAP, Python
dependencies, Redis, and the pinned model artifacts. Later starts reuse the
local images and are much faster.

## VPS deployment

The production override adds Caddy, automatic HTTPS, and HTTP basic
authentication. The host can be created reproducibly with the
[Terraform stack](../infra/terraform/README.md), or prepared manually. Before
deploying:

1. Point the target domain's `A` or `AAAA` record to the VPS.
2. Allow inbound TCP `80/443` and UDP `443`.
3. Copy `.env.example` to `.env`.

Generate the required credentials:

```bash
docker run --rm caddy:2.10-alpine \
  caddy hash-password --plaintext 'choose-a-strong-password'
openssl rand -hex 32
```

Set the resulting values in `.env`:

```env
APP_IMAGE=ghcr.io/layansabha/dom-xss:latest
APP_DOMAIN=scan.example.com
APP_BASIC_AUTH_USER=admin
APP_BASIC_AUTH_HASH='$2a$14$replace_with_the_generated_hash'
ZAP_API_KEY=replace-with-the-generated-random-value
```

Deploy the published image:

```bash
./deploy/deploy.sh
```

The script pulls the images, starts the base and production Compose files, and
waits for the API readiness check. If the GHCR package is not public, first
authenticate Docker with a GitHub token that has `read:packages`.
