from __future__ import annotations

import pytest

from app.config import Settings
from app.schemas import ScanRequest
from app.services.pipeline import run_pipeline


@pytest.mark.asyncio
async def test_pipeline_rejects_zap_when_not_enabled() -> None:
    request = ScanRequest(
        target_url="https://example.com/",
        scope_mode="page",
        dynamic_verification=True,
    )
    settings = Settings(_env_file=None, zap_enabled=False)

    with pytest.raises(
        RuntimeError,
        match="dynamic verification was requested but ZAP is not enabled",
    ):
        await run_pipeline(request, settings, lambda _progress, _stage: None)
