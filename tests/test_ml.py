from __future__ import annotations

import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pytest

from app.services.ml import ModelArtifactError, ModelService


def _write_artifacts(tmp_path: Path) -> tuple[Path, Path]:
    vocabulary = {"document": 0, "write": 1, "location": 2}
    features = np.asarray(
        [
            [0, 0, 0],
            [1, 0, 0],
            [1, 1, 1],
            [2, 2, 2],
            [0, 1, 0],
            [3, 3, 3],
        ],
        dtype=np.float32,
    )
    labels = np.asarray([0, 0, 1, 1, 0, 1])
    dataset = lgb.Dataset(features, label=labels)
    model = lgb.train(
        {
            "objective": "binary",
            "verbosity": -1,
            "min_data_in_leaf": 1,
            "min_data_in_bin": 1,
            "num_leaves": 4,
        },
        dataset,
        num_boost_round=5,
    )

    model_path = tmp_path / "model.txt"
    vocab_path = tmp_path / "vocab.json"
    model.save_model(model_path)
    vocab_path.write_text(json.dumps(vocabulary), encoding="utf-8")
    return model_path, vocab_path


def test_model_service_scores_function_units(tmp_path: Path) -> None:
    model_path, vocab_path = _write_artifacts(tmp_path)
    service = ModelService(model_path, vocab_path, 0.5, 20, 20_000)

    result = service.predict("", "function sink() { document.write(location.hash); }")

    assert result is not None
    assert result.code_units_analyzed >= 1
    assert result.matched_tokens >= 3
    assert 0 <= result.probability <= 1


def test_model_service_rejects_invalid_native_artifact(tmp_path: Path) -> None:
    model_path = tmp_path / "model.txt"
    vocab_path = tmp_path / "vocab.json"
    model_path.write_text("not a LightGBM model", encoding="utf-8")
    vocab_path.write_text('{"document": 0}', encoding="utf-8")

    with pytest.raises(ModelArtifactError):
        ModelService(model_path, vocab_path, 0.5, 20, 20_000)
