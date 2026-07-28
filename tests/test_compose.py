from __future__ import annotations

from pathlib import Path

import yaml


def test_redis_can_reuse_its_append_only_volume_after_restart() -> None:
    compose = yaml.safe_load(Path("compose.yaml").read_text(encoding="utf-8"))
    redis = compose["services"]["redis"]

    assert redis["cap_drop"] == ["ALL"]
    assert set(redis["cap_add"]) == {
        "CHOWN",
        "DAC_READ_SEARCH",
        "SETGID",
        "SETUID",
    }
    assert "redis-data:/data" in redis["volumes"]
