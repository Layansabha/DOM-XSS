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
    && apt-get install --yes --no-install-recommends libgomp1 python3.12-venv \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid "${APP_GID}" app \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" --create-home --shell /usr/sbin/nologin app

COPY pyproject.toml README.md LICENSE ./
COPY app ./app
COPY artifacts ./artifacts
COPY scripts/verify_artifacts.py /tmp/verify_artifacts.py

# Refuse to build an image when the committed model bundle is incomplete,
# modified, or incompatible with the runtime feature contract.
RUN python /tmp/verify_artifacts.py --artifact-dir /app/artifacts \
    && rm /tmp/verify_artifacts.py

RUN python -m venv "${VIRTUAL_ENV}" \
    && python -m pip install --upgrade "pip==26.1.2" \
    && python -m pip install . \
    && chown -R app:app /app /home/app "${VIRTUAL_ENV}"

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
