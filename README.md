# DOM XSS Pipeline

A deployable DOM-based XSS analysis pipeline that combines:

- same-origin crawling for domain-level targets
- browser-rendered DOM and JavaScript collection with Playwright
- function-level AST inference with the LightGBM model from `Layansabha/Dom-xss-ML`
- optional dynamic analysis with OWASP ZAP Client Spider, client-side rules, and active rule 40026
- Redis/RQ background jobs
- Docker Compose deployment
- CI, linting, tests, container scanning, and dependency updates

> This project is intended only for systems you own or are explicitly authorized to test.

## How it works

1. The user submits a URL.
2. `auto` mode treats a root URL as a domain scan and a non-root URL as a single-page scan.
3. Playwright renders each in-scope page.
4. The pipeline collects JavaScript from both the original HTML response and the rendered DOM, plus same-origin external scripts and DOM event handlers. Reading the original response preserves scripts removed by `document.write()` or other runtime DOM mutations.
5. JavaScript is split into function-sized units and converted into AST token-frequency vectors using the original 500-token vocabulary.
6. LightGBM scores only units with at least one vocabulary match. Zero-feature units are reported as insufficient coverage instead of receiving the model's intercept score.
7. The highest scored function is reported for its page, together with feature coverage and scored-unit counts.
8. When dynamic analysis is enabled, ZAP Client Spider exercises client-side flows and the browser-based active rule (`40026`) runs once for each collected in-scope page, bounded by `MAX_PAGES`.
9. The UI separates client-side detections from actively confirmed findings.

The ML score is a ranking signal, not a calibrated probability that a page is exploitable. ZAP client-side detections still require review; only active rule `40026` findings are labeled actively confirmed.

## Kali Linux quick start

Requirements:

- Kali Linux with Docker Engine and Docker Compose v2
- at least 6 GB free RAM recommended for the API, worker, Chromium, Redis, and ZAP
- internet access during the first image build so model artifacts and container images can be pulled

Install Docker on Kali if needed:

```bash
sudo apt update
sudo apt install -y docker.io docker-compose
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
newgrp docker
docker compose version
```

Kali packages Compose v2 as `docker-compose`; `docker-compose-plugin` is not available on every Kali mirror. The installed command is still `docker compose`.

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

## VPS deployment

The production override adds Caddy, automatic HTTPS, and HTTP basic authentication. Point an `A`/`AAAA` record at the VPS first, then prepare `.env`:

```bash
cp .env.example .env
docker run --rm caddy:2.10-alpine caddy hash-password --plaintext 'choose-a-strong-password'
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

Allow inbound TCP `80/443` and UDP `443`, then deploy:

```bash
./scripts/deploy.sh
```

The script pulls the published image, recreates the stack, and waits for `/readyz`. If the GHCR package is not public, authenticate the VPS with a GitHub token that has `read:packages` before running it.

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
    "dynamic_verification": false
  }'
```

Set `dynamic_verification=true` to run OWASP ZAP after ML analysis.

### Reading the result

- **ML score** ranks code using the original LightGBM model; it is not a confidence percentage or proof of a vulnerability.
- **Feature coverage** is the share of extracted AST tokens represented in the model's 500-token vocabulary.
- **Insufficient coverage** means no collected code unit matched that vocabulary, so the page is intentionally not scored.
- **Client-side detection** is evidence from a ZAP client rule and needs review/reproduction.
- **Actively confirmed** means ZAP active rule `40026` produced reproducible scanner evidence.

## Configuration

Copy `.env.example` to `.env`. Important controls:

- `ALLOW_PRIVATE_TARGETS=false` blocks loopback, RFC1918, link-local, reserved, and metadata-style destinations.
- `MAX_QUEUED_SCANS=25` rejects excess work with HTTP 429 instead of exhausting the VPS.
- `MAX_PAGES=30` limits domain crawls.
- `MAX_CRAWL_DEPTH=2` limits crawl depth.
- `CRAWL_DELAY_MS=150` adds a small delay between same-origin page navigations.
- `REQUEST_TIMEOUT_SECONDS=20` limits page and HTTP operations.
- `MAX_PAGE_BYTES=5000000` caps collected content per page.
- `INCLUDE_THIRD_PARTY_SCRIPTS=false` excludes third-party JavaScript from ML analysis by default.
- `ML_THRESHOLD=0.50` controls the vulnerable-risk classification threshold.
- `ML_MAX_CODE_UNITS=500` caps function-level inference work per page.
- `ML_MAX_CODE_UNIT_BYTES=250000` caps the source size of one analyzed unit.
- `ZAP_MAX_MINUTES=10` limits the combined Client Spider, passive queue, and active verification work.
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

- `models/lightgbm_best_model_final.pkl`
- `preprocessing/vocab_top500_filtered.pkl`

During the isolated artifact-build stage, the conversion script verifies each file using its Git
blob SHA, loads the pinned source pickle, and exports LightGBM's native model format plus a JSON
vocabulary. The runtime image contains neither the source pickle nor its legacy scikit-learn
dependency. SHA-256 digests for the source and runtime files are saved in
`artifact-manifest.json` inside the image.

Reported model metrics from the source repository:

| Metric | Value |
|---|---:|
| Accuracy | 0.9614 |
| Precision | 0.9970 |
| Recall | 0.9165 |
| Approximate F1 | 0.9551 |
| False positives | 11 |

The source repository's reported metrics describe a stratified held-out split of function rows. They do not measure site-level generalization and do not guarantee the same performance on live websites.

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

The native model files must exist under `artifacts/`. To reproduce the isolated conversion
locally, create a disposable environment with the source model's original ABI dependencies:

```bash
python3 -m venv .artifact-venv
.artifact-venv/bin/pip install \
  'joblib==1.5.2' 'lightgbm==4.6.0' 'numpy==1.26.4' 'scikit-learn==1.3.2'
ARTIFACT_DIR=artifacts .artifact-venv/bin/python scripts/prepare_artifacts.py
rm -rf .artifact-venv
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
- DOM-XSS-only active scan policy plus bounded Client Spider coverage
- non-root application user
- Redis not published to the host
- security headers and API request-size limits
- CI lint, unit tests, dependency audit, and Trivy image scan
- automatic GHCR publishing only after all CI and container security gates pass
- image provenance attestation and SBOM generation
- optional Caddy TLS and basic authentication for VPS exposure

## Known limitations

- The training dataset represents individual JavaScript functions as bags of parsed AST tokens. This runtime follows that function-level contract with Tree-sitter, but it cannot exactly reproduce the modified Chromium/V8 instrumentation that created the original dataset. The UI exposes feature coverage and refuses to score zero-feature units, but the extractor still needs validation against a labeled deployment set.
- A low ML score does not rule out DOM XSS. For example, feature importance does not imply that every occurrence of `innerHTML` increases the model output; dynamic ZAP analysis remains important.
- Automated scanners can miss interaction-dependent or authentication-dependent DOM XSS.
- Authenticated crawling is not implemented yet.
- DNS re-resolution narrows but cannot completely eliminate DNS-rebinding time-of-check/time-of-use risk. Production deployments should also enforce outbound network policy and metadata-service blocking.
- The base Compose exposure is localhost-only. The production override adds authentication and TLS; add infrastructure-level rate limiting and an egress allowlist before exposing it to untrusted users.
- Some applications intentionally block headless browsers.

## License

MIT. Model artifacts remain attributable to their source repository and are downloaded during the image build rather than copied into this repository.

## References

- [DOM XSS Web Vulnerability Dataset](https://kilthub.cmu.edu/articles/dataset/DOM_XSS_Web_Vulnerability_Dataset/13870256)
- [Function-level AST feature representation used by the source research](https://www.contrib.andrew.cmu.edu/~liminjia/research/papers/www2021-dom-xss-dnn.pdf)
- [OWASP ZAP DOM XSS active scan rule 40026](https://www.zaproxy.org/docs/alerts/40026/)
- [OWASP ZAP Client Spider](https://www.zaproxy.org/docs/desktop/addons/client-side-integration/spider/)
- [OWASP ZAP vs Google Firing Range](https://www.zaproxy.org/docs/scans/firingrange/)
- [OWASP ZAP Docker guide](https://www.zaproxy.org/docs/docker/about/)
