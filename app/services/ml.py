from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, TypedDict

import joblib
import numpy as np

from app.config import get_settings
from app.services.extractor import vectorize


class ModelArtifactError(RuntimeError):
    pass


class MatchedFeature(TypedDict):
    token: str
    count: int


@dataclass(frozen=True)
class Prediction:
    probability: float
    vulnerable: bool
    threshold: float
    matched_tokens: int
    total_tokens: int
    top_matched_features: list[MatchedFeature]


class ModelService:
    def __init__(self, model_path: Path, vocab_path: Path, threshold: float) -> None:
        if not model_path.is_file():
            raise ModelArtifactError(f"model artifact not found: {model_path}")
        if not vocab_path.is_file():
            raise ModelArtifactError(f"vocabulary artifact not found: {vocab_path}")

        self.model: Any = joblib.load(model_path)
        self.vocabulary: dict[str, int] = joblib.load(vocab_path)
        self.threshold = threshold

        if not isinstance(self.vocabulary, dict) or not self.vocabulary:
            raise ModelArtifactError("vocabulary artifact is empty or invalid")
        if not hasattr(self.model, "predict_proba"):
            raise ModelArtifactError("model does not provide predict_proba")
        expected_features = getattr(self.model, "n_features_in_", len(self.vocabulary))
        if int(expected_features) != len(self.vocabulary):
            raise ModelArtifactError(
                "model feature count does not match the vocabulary size"
            )

    def predict(self, rendered_dom: str, javascript: str) -> Prediction:
        vector, extracted = vectorize(rendered_dom, javascript, self.vocabulary)
        features = np.asarray([vector], dtype=np.float32)
        probability = float(self.model.predict_proba(features)[0][1])

        matched: list[MatchedFeature] = []
        for token, count in extracted.counts.most_common():
            if token not in self.vocabulary:
                continue
            matched.append({"token": token, "count": int(count)})
            if len(matched) == 20:
                break

        return Prediction(
            probability=probability,
            vulnerable=probability >= self.threshold,
            threshold=self.threshold,
            matched_tokens=extracted.matched_tokens,
            total_tokens=extracted.total_tokens,
            top_matched_features=matched,
        )


@lru_cache
def get_model_service() -> ModelService:
    settings = get_settings()
    return ModelService(
        model_path=settings.ml_model_path,
        vocab_path=settings.ml_vocab_path,
        threshold=settings.ml_threshold,
    )
