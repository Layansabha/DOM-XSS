FROM python:3.12-slim-bookworm AS artifact-builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

COPY scripts/prepare_artifacts.py ./prepare_artifacts.py

# Fetch only commit-pinned native artifacts. No pickle deserialization or
# training-time scikit-learn ABI is needed in the image build.
RUN ARTIFACT_DIR=/artifacts python prepare_artifacts.py


FROM mcr.microsoft.com/playwright/python:v1.61.0-noble AS runtime

ARG APP_UID=10001
ARG APP_GID=10001

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    HOME=/home/app

WORKDIR /app

RUN apt-get update \
    && apt-get upgrade --yes --no-install-recommends \
    && apt-get install --yes --no-install-recommends libgomp1 python3.12-venv \
    && apt-get autoremove --yes \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid "${APP_GID}" app \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" --create-home --shell /usr/sbin/nologin app

COPY pyproject.toml README.md LICENSE ./
COPY app ./app
COPY --from=artifact-builder /artifacts ./artifacts

RUN python -m venv "${VIRTUAL_ENV}" \
    && python -m pip install --upgrade "pip==26.1.2" \
    && python -m pip install . \
    && chown -R app:app /app /home/app "${VIRTUAL_ENV}"

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
