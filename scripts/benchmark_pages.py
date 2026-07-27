from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, TypedDict, cast

from app.config import get_settings
from app.services.ml import ModelService, Prediction

Label = Literal["safe", "vulnerable"]


class BenchmarkCase(TypedDict):
    id: str
    label: Label
    category: str
    rendered_dom: str
    javascript: str
    rationale: str


@dataclass(frozen=True)
class BenchmarkMetrics:
    total: int
    scored: int
    abstained: int
    true_positives: int
    false_positives: int
    true_negatives: int
    false_negatives: int
    accuracy: float
    precision: float
    recall: float
    f1: float
    false_positive_rate: float
    coverage: float


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def calculate_metrics(labels: list[Label], decisions: list[bool | None]) -> BenchmarkMetrics:
    if len(labels) != len(decisions):
        raise ValueError("labels and decisions must contain the same number of entries")

    true_positives = false_positives = true_negatives = false_negatives = abstained = 0
    for label, decision in zip(labels, decisions, strict=True):
        if decision is None:
            abstained += 1
        elif label == "vulnerable" and decision:
            true_positives += 1
        elif label == "vulnerable":
            false_negatives += 1
        elif decision:
            false_positives += 1
        else:
            true_negatives += 1

    total = len(labels)
    scored = total - abstained
    precision = _ratio(true_positives, true_positives + false_positives)
    recall = _ratio(true_positives, true_positives + false_negatives)
    return BenchmarkMetrics(
        total=total,
        scored=scored,
        abstained=abstained,
        true_positives=true_positives,
        false_positives=false_positives,
        true_negatives=true_negatives,
        false_negatives=false_negatives,
        accuracy=_ratio(true_positives + true_negatives, scored),
        precision=precision,
        recall=recall,
        f1=_ratio(2 * precision * recall, precision + recall),
        false_positive_rate=_ratio(false_positives, false_positives + true_negatives),
        coverage=_ratio(scored, total),
    )


def load_corpus(path: Path) -> list[BenchmarkCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("unsupported benchmark schema")
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("benchmark corpus contains no cases")

    required_fields = {
        "id",
        "label",
        "category",
        "rendered_dom",
        "javascript",
        "rationale",
    }
    cases: list[BenchmarkCase] = []
    seen_ids: set[str] = set()
    for position, raw_case in enumerate(raw_cases):
        if not isinstance(raw_case, dict) or set(raw_case) != required_fields:
            raise ValueError(f"benchmark case {position} has an invalid shape")
        if not all(isinstance(raw_case[field], str) for field in required_fields):
            raise ValueError(f"benchmark case {position} contains a non-string field")
        if raw_case["label"] not in {"safe", "vulnerable"}:
            raise ValueError(f"benchmark case {position} has an invalid label")
        case_id = str(raw_case["id"])
        if not case_id or case_id in seen_ids:
            raise ValueError(f"benchmark case {position} has a duplicate or empty id")
        seen_ids.add(case_id)
        cases.append(cast(BenchmarkCase, raw_case))
    return cases


def evaluate(
    service: ModelService,
    cases: list[BenchmarkCase],
) -> tuple[BenchmarkMetrics, list[dict[str, object]]]:
    labels: list[Label] = []
    decisions: list[bool | None] = []
    results: list[dict[str, object]] = []

    for case in cases:
        prediction: Prediction | None = service.predict(
            case["rendered_dom"],
            case["javascript"],
        )
        scored = prediction is not None and prediction.status == "scored"
        decision = prediction.vulnerable if scored and prediction is not None else None
        labels.append(case["label"])
        decisions.append(decision)
        results.append(
            {
                "id": case["id"],
                "label": case["label"],
                "category": case["category"],
                "decision": (
                    "vulnerable"
                    if decision is True
                    else "safe"
                    if decision is False
                    else "abstained"
                ),
                "risk_score": prediction.risk_score if prediction is not None else None,
                "feature_coverage": (
                    prediction.feature_coverage if prediction is not None else 0.0
                ),
            }
        )

    return calculate_metrics(labels, decisions), results


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the transparent page-level model regression corpus.",
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path("benchmarks/page-level-corpus.json"),
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main() -> None:
    arguments = _parser().parse_args()
    settings = get_settings()
    service = ModelService(
        model_path=settings.ml_model_path,
        vocab_path=settings.ml_vocab_path,
        threshold=settings.ml_threshold,
        max_code_units=settings.ml_max_code_units,
        max_code_unit_bytes=settings.ml_max_code_unit_bytes,
    )
    metrics, results = evaluate(service, load_corpus(arguments.corpus))
    report = {
        "corpus": str(arguments.corpus),
        "threshold": service.threshold,
        "scope": "curated synthetic page-level regression; not external validation",
        "metrics": asdict(metrics),
        "cases": results,
    }

    if arguments.as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return

    print("Page-level regression benchmark")
    print(f"Scope: {report['scope']}")
    print(f"Threshold: {service.threshold:.5f}")
    print(
        "Cases: "
        f"{metrics.total} total, {metrics.scored} scored, {metrics.abstained} abstained"
    )
    print(
        "Confusion: "
        f"TP={metrics.true_positives} FP={metrics.false_positives} "
        f"TN={metrics.true_negatives} FN={metrics.false_negatives}"
    )
    print(
        "Metrics: "
        f"accuracy={metrics.accuracy:.4f} precision={metrics.precision:.4f} "
        f"recall={metrics.recall:.4f} f1={metrics.f1:.4f} "
        f"false_positive_rate={metrics.false_positive_rate:.4f} "
        f"coverage={metrics.coverage:.4f}"
    )
    for result in results:
        score = result["risk_score"]
        score_text = "n/a" if score is None else f"{float(score):.4f}"
        print(
            f"- {result['id']}: label={result['label']} "
            f"decision={result['decision']} risk_score={score_text}"
        )


if __name__ == "__main__":
    main()
