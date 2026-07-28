from __future__ import annotations

from collections import Counter

from app.services.extractor import (
    ast_token_counts,
    extract_code_units,
    vectorize_counts,
)


def test_ast_tokens_include_symbols_operations_and_properties() -> None:
    source = """
    function render(value) {
      const output = document.getElementById('output');
      output.innerHTML = location.hash + value;
    }
    """
    counts = ast_token_counts(source)

    assert counts["function"] >= 1
    assert counts["assign"] >= 2
    assert counts["call"] >= 1
    assert counts["add"] >= 1
    assert counts["document"] >= 1
    assert counts["innerhtml"] >= 1
    assert counts["location"] >= 1
    assert counts["sec_source_url"] == 1
    assert counts["sec_sink_inner_html"] == 1
    assert counts["sec_pair_url_inner_html"] == 1


def test_ast_tokens_do_not_invent_a_source_sink_pair() -> None:
    counts = ast_token_counts(
        "function render(value) { output.textContent = location.hash + value; }"
    )

    assert counts["sec_source_url"] == 1
    assert not any(token.startswith("sec_sink_") for token in counts)
    assert not any(token.startswith("sec_pair_") for token in counts)


def test_extract_code_units_finds_functions_and_dom_handlers() -> None:
    units = extract_code_units(
        '<button onclick="preview(location.hash)">Preview</button>',
        "function preview(value) { document.write(value); }",
        max_units=10,
        max_unit_bytes=10_000,
    )

    assert any(unit.kind == "function" and "document.write" in unit.source for unit in units)
    assert any(unit.kind == "inline-handler" for unit in units)


def test_extract_code_units_enforces_unit_limit_and_deduplicates() -> None:
    units = extract_code_units(
        '<button onclick="run()"></button><button onclick="run()"></button>',
        "function one() {} function two() {}",
        max_units=2,
        max_unit_bytes=10_000,
    )

    assert len(units) == 2
    assert len({(unit.kind, unit.source) for unit in units}) == 2


def test_extract_code_units_ignores_comments_and_empty_statements() -> None:
    units = extract_code_units(
        "",
        "// model baseline must not score this\n;\ndocument.write(location.hash);",
        max_units=10,
        max_unit_bytes=10_000,
    )

    assert len(units) == 1
    assert "document.write" in units[0].source


def test_vectorize_counts_uses_vocabulary_indices() -> None:
    vocabulary = {"document": 0, "innerhtml": 1, "location": 2}
    vector, metadata = vectorize_counts(
        Counter({"document": 1, "innerhtml": 2, "location": 3, "ignored": 9}),
        vocabulary,
    )

    assert vector == [1.0, 2.0, 3.0]
    assert metadata.matched_tokens == 6
    assert metadata.total_tokens == 15
