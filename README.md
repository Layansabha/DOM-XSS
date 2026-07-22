# DOM XSS Pipeline

A deployable DOM-based XSS analysis pipeline that combines:

- same-origin crawling for domain-level targets
- browser-rendered DOM and JavaScript collection with Playwright
- Random Forest inference using the trained artifacts from `Layansabha/Dom-xss-ML`
- optional authorized dynamic verification with the OWASP ZAP DOM XSS active scan rule
- Redis/RQ background jobs
- Docker Compose deployment
- CI, linting, tests, container scanning, and dependency updates

> This project is intended only for systems you own or are explicitly authorized to test.

## How it works

1. The user submits a URL.
2. `auto` mode treats a root URL as a domain scan and a non-root URL as a single-page scan.
3. Playwright renders each in-scope page.
4. The pipeline collects the rendered DOM, inline JavaScript, and same-origin external JavaScript.
5. Tokens are counted and mapped to the original 500-token vocabulary.
6. The Random Forest model returns a probability-based ML risk signal.
7. When authorized dynamic verification is enabled, ZAP runs the DOM XSS active rule (`40026`) against the same target scope.
8. The UI displays per-page ML findings and any ZAP evidence.

The ML result is a prioritization signal, not proof of exploitability. ZAP findings are reported separately.

## Kali Linux quick start

Requirements:

- Kali Linux with Docker Engine and Docker Compose v2
- at least 6 GB free RAM recommended for the API, worker, Chromium, Redis, and ZAP
- internet access during the first image build so model artifacts and container images can be pulled

```bash
git clone https://github.com/Layansabha/DOM-XSS.git
cd DOM-XSS
cp .env.example .env
openssl rand -hex 32
```

Put the generated value in `.env` as `ZAP_API_KEY`, then run:

```bash
docker compose up --build
```

Open:

```text
http://127.0.0.1:8000
```

Stop the stack:

```bash
docker compose down
```

Remove Redis data as well:

```bash
docker compose down -v
```

## CLI smoke checks

```bash
curl -fsS http://127.0.0.1:8000/healthz
curl -fsS http://127.0.0.1:8000/readyz
```

Create an ML-only scan:

```bash
curl -sS -X POST http://127.0.0.1:8000/api/scans \
  -H 'Content-Type: application/json' \
  -d '{
    "target_url": "https://example.com/",
    "scope_mode": "auto",
    "dynamic_verification": false,
    "authorized": false
  }'
```

Dynamic verification requires both `dynamic_verification=true` and `authorized=true`.

## Configuration

Copy `.env.example` to `.env`. Important controls:

- `ALLOW_PRIVATE_TARGETS=false` blocks loopback, RFC1918, link-local, reserved, and metadata-style destinations.
- `MAX_PAGES=30` limits domain crawls.
- `MAX_CRAWL_DEPTH=2` limits crawl depth.
- `CRAWL_DELAY_MS=150` adds a small delay between same-origin page navigations.
- `REQUEST_TIMEOUT_SECONDS=20` limits page and HTTP operations.
- `MAX_PAGE_BYTES=5000000` caps collected content per page.
- `INCLUDE_THIRD_PARTY_SCRIPTS=false` excludes third-party JavaScript from ML analysis by default.
- `ML_THRESHOLD=0.50` controls the vulnerable-risk classification threshold.
- `ZAP_MAX_MINUTES=10` limits dynamic verification.
- `ZAP_ATTACK_STRENGTH=LOW` limits payload volume.
- `ZAP_ALERT_THRESHOLD=MEDIUM` reduces noisy alerts.

For an authorized local lab, explicitly set:

```env
ALLOW_PRIVATE_TARGETS=true
```

Do not enable this on an internet-facing deployment.

## Artifact provenance

The image build downloads immutable model artifacts from commit:

```text
a14721a928d492055d02dbb5416318d3de8062b4
```

Files:

- `models/random_forest_best_model_final.pkl`
- `preprocessing/vocab_top500_filtered.pkl`

The download script verifies each file using its Git blob SHA before installation.

Reported model metrics from the source repository:

| Metric | Value |
|---|---:|
| Accuracy | 0.9619 |
| Precision | 0.9987 |
| Recall | 0.9160 |
| Approximate F1 | 0.9556 |
| False positives | 5 |

## Development

Create a local virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
playwright install chromium
pytest
ruff check .
mypy app
```

Run the API and worker locally:

```bash
redis-server
uvicorn app.main:app --reload
rq worker domxss --url redis://127.0.0.1:6379/0
```

The model files must exist under `artifacts/`. Download and verify them with:

```bash
python scripts/fetch_artifacts.py
```

## API

- `POST /api/scans` creates a background scan.
- `GET /api/scans/{job_id}` returns queued/running/finished/failed state.
- `GET /healthz` confirms the API process is alive.
- `GET /readyz` confirms Redis and model artifacts are available.

OpenAPI documentation is available at `/docs`.

## Security design

- URL normalization and DNS resolution before requests
- private/reserved IP rejection by default
- redirect and browser-request checks with DNS re-resolution on every request
- same-origin crawl boundary and conservative skip rules for logout/delete/download links
- strict page, depth, byte, and time limits
- no public ZAP port
- ZAP API key
- DOM-XSS-only active scan policy
- explicit authorization gate
- non-root application user
- Redis not published to the host
- security headers and API request-size limits
- CI lint, unit tests, dependency audit, and Trivy image scan

## Known limitations

- The source ML repository contains vocabulary creation and vectorization, but not the exact original raw-page-to-feature extraction implementation. This project uses a deterministic JavaScript/DOM tokenizer aligned with the published vocabulary. The model therefore must be treated as a triage signal until it is revalidated on an external labeled dataset generated by this exact runtime extractor.
- Automated scanners can miss interaction-dependent or authentication-dependent DOM XSS.
- Authenticated crawling is not implemented yet.
- DNS re-resolution narrows but cannot completely eliminate DNS-rebinding time-of-check/time-of-use risk. Production deployments should also enforce outbound network policy and metadata-service blocking.
- The included Compose exposure is localhost-only. Add authentication, rate limiting, TLS, and an egress allowlist before exposing the service to untrusted users.
- Some applications intentionally block headless browsers.

## License

MIT. Model artifacts remain attributable to their source repository and are downloaded during the image build rather than copied into this repository.
