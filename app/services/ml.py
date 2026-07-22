from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TypedDict

import numpy as np
from lightgbm import Booster
from lightgbm.basic import LightGBMError

from app.config import get_settings
from app.services.extractor import ast_token_counts, extract_code_units, vectorize_counts


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
    code_units_analyzed: int
    riskiest_unit_kind: str
    matched_tokens: int
    total_tokens: int
    top_matched_features: list[MatchedFeature]


class ModelService:
    def __init__(
        self,
        model_path: Path,
        vocab_path: Path,
        threshold: float,
        max_code_units: int,
        max_code_unit_bytes: int,
    ) -> None:
        if not model_path.is_file():
            raise ModelArtifactError(f"model artifact not found: {model_path}")
        if not vocab_path.is_file():
            raise ModelArtifactError(f"vocabulary artifact not found: {vocab_path}")

        try:
            self.model = Booster(model_file=str(model_path))
            raw_vocabulary = json.loads(vocab_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, LightGBMError) as exc:
            raise ModelArtifactError("model artifacts could not be loaded") from exc

        if not isinstance(raw_vocabulary, dict) or not raw_vocabulary:
            raise ModelArtifactError("vocabulary artifact is empty or invalid")
        if not all(
            isinstance(token, str) and isinstance(index, int)
            for token, index in raw_vocabulary.items()
        ):
            raise ModelArtifactError("vocabulary entries are invalid")
        if sorted(raw_vocabulary.values()) != list(range(len(raw_vocabulary))):
            raise ModelArtifactError("vocabulary indexes must be contiguous and unique")

        self.vocabulary: dict[str, int] = raw_vocabulary
        self.threshold = threshold
        self.max_code_units = max_code_units
        self.max_code_unit_bytes = max_code_unit_bytes

        if self.model.num_feature() != len(self.vocabulary):
            raise ModelArtifactError("model feature count does not match the vocabulary size")

    def predict(self, rendered_dom: str, javascript: str) -> Prediction | None:
        units = extract_code_units(
            rendered_dom,
            javascript,
            max_units=self.max_code_units,
            max_unit_bytes=self.max_code_unit_bytes,
        )
        if not units:
            return None

        vectors: list[list[float]] = []
        extracted_units = []
        for unit in units:
            vector, extracted = vectorize_counts(
                ast_token_counts(unit.source),
                self.vocabulary,
            )
            vectors.append(vector)
            extracted_units.append(extracted)

        features = np.asarray(vectors, dtype=np.float32)
        probabilities = np.asarray(self.model.predict(features), dtype=np.float64)
        riskiest_index = int(np.argmax(probabilities))
        probability = float(probabilities[riskiest_index])
        extracted = extracted_units[riskiest_index]

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
            code_units_analyzed=len(units),
            riskiest_unit_kind=units[riskiest_index].kind,
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
        max_code_units=settings.ml_max_code_units,
        max_code_unit_bytes=settings.ml_max_code_unit_bytes,
    )
