from __future__ import annotations

from pathlib import Path

import pytest

from scripts.verify_artifacts import verify_bundle

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_committed_model_bundle_is_complete_and_verified() -> None:
    verified = verify_bundle(REPOSITORY_ROOT / "artifacts")

    assert set(verified) == {
        "lightgbm_grouped_metadata.json",
        "lightgbm_grouped_model.txt",
        "vocab_top500_grouped.json",
    }


def test_modified_artifact_is_rejected(tmp_path: Path) -> None:
    source = REPOSITORY_ROOT / "artifacts"
    for path in source.iterdir():
        (tmp_path / path.name).write_bytes(path.read_bytes())
    (tmp_path / "vocab_top500_grouped.json").write_text("{}", encoding="utf-8")

    with pytest.raises(RuntimeError, match="integrity check failed"):
        verify_bundle(tmp_path)
