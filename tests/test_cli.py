from __future__ import annotations

from app.cli import Console, _parser, _percentage, _render_result, _scan_exit_code


def test_scan_parser_uses_safe_defaults() -> None:
    args = _parser().parse_args(["scan", "https://example.com/path"])

    assert args.scope == "auto"
    assert args.verify is False
    assert args.detach is False
    assert args.fail_on_high_risk is False


def test_percentage_handles_numeric_and_missing_values() -> None:
    assert _percentage(0.967) == "96.7%"
    assert _percentage(None) == "n/a"


def test_high_risk_exit_code_is_opt_in() -> None:
    payload = {
        "state": "finished",
        "result": {"summary": {"ml_high_risk_pages": 1}},
    }

    assert _scan_exit_code(payload, fail_on_high_risk=False) == 0
    assert _scan_exit_code(payload, fail_on_high_risk=True) == 2


def test_result_renderer_prints_compact_security_summary(capsys: object) -> None:
    result = {
        "duration_seconds": 1.6,
        "summary": {
            "pages_collected": 1,
            "pages_scored": 1,
            "high_priority_pages": 1,
            "ml_high_risk_pages": 1,
            "verified_dom_xss_alerts": 0,
        },
        "pages": [
            {
                "url": "https://example.com/vulnerable",
                "collection_status": "complete",
                "warnings": [],
                "ml": {
                    "status": "scored",
                    "vulnerable": True,
                    "risk_score": 0.967,
                    "feature_coverage": 0.841,
                },
            }
        ],
    }

    _render_result(result, Console(color=False))
    output = capsys.readouterr().out  # type: ignore[attr-defined]

    assert "ANALYSIS COMPLETE" in output
    assert "high-priority 1" in output
    assert "96.7%" in output
    assert "84.1%" in output
    assert "https://example.com/vulnerable" in output
