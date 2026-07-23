# Releases and rollback

The project publishes immutable container releases to GitHub Container Registry.
Production-style deployments must use either a `sha-*` tag or a semantic version
tag such as `v1.2.0`; the deployment script rejects `latest`.

## Create a release

After the main CI pipeline is green, create and push a semantic-version tag:

```bash
git checkout main
git pull --ff-only
git tag -s v1.0.0 -m "DOM XSS Pipeline v1.0.0"
git push origin v1.0.0
```

The release workflow builds the image, publishes both version and commit tags,
generates SBOM and provenance data, scans the published digest with Trivy, and
creates a GitHub Release containing the deploy command and immutable digest.

## Deploy a release

```bash
make release IMAGE=ghcr.io/layansabha/dom-xss:v1.0.0
```

The deployment process:

1. pulls the exact requested image;
2. starts the production Compose stack;
3. checks `/readyz` for up to three minutes;
4. records current and previous image references under `.deploy/`;
5. automatically restores the previous image when readiness fails.

The `.deploy/` directory contains deployment state only and must not be
committed.

## Manual rollback

```bash
make rollback
```

Rollback uses the previously healthy image reference and performs the same
readiness validation. This is intentionally host-local and requires no paid
CD platform or cloud service.
