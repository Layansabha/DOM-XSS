from pathlib import Path

import pytest

from scripts.benchmark_pages import calculate_metrics, load_corpus


def test_calculate_page_benchmark_metrics_includes_abstentions() -> None:
    metrics = calculate_metrics(
        ["vulnerable", "vulnerable", "safe", "safe", "safe"],
        [True, False, True, False, None],
    )

    assert metrics.total == 5
    assert metrics.scored == 4
    assert metrics.abstained == 1
    assert metrics.true_positives == 1
    assert metrics.false_positives == 1
    assert metrics.true_negatives == 1
    assert metrics.false_negatives == 1
    assert metrics.accuracy == pytest.approx(0.5)
    assert metrics.precision == pytest.approx(0.5)
    assert metrics.recall == pytest.approx(0.5)
    assert metrics.f1 == pytest.approx(0.5)
    assert metrics.false_positive_rate == pytest.approx(0.5)
    assert metrics.coverage == pytest.approx(0.8)


def test_page_benchmark_corpus_has_unique_balanced_labels() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    cases = load_corpus(repository_root / "benchmarks/page-level-corpus.json")

    assert len(cases) == 12
    assert len({case["id"] for case in cases}) == len(cases)
    assert sum(case["label"] == "vulnerable" for case in cases) == 6
    assert sum(case["label"] == "safe" for case in cases) == 6
