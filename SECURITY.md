# Security Policy

## Supported version

Only the latest `main` branch is supported.

## Authorized use

Do not scan systems without explicit authorization. Dynamic verification sends active payloads and can change application state.

## Reporting a vulnerability

Open a private GitHub security advisory for this repository. Do not include secrets, private targets, access tokens, or live exploit payloads in a public issue.

## Deployment guidance

- Keep `ALLOW_PRIVATE_TARGETS=false` for any shared or public deployment.
- Do not publish Redis or ZAP ports.
- Use a long random `ZAP_API_KEY`.
- Put the UI behind authentication before exposing it outside localhost.
- Apply egress controls at the container or host firewall layer.
- Rotate secrets and rebuild images regularly.
