from __future__ import annotations

from app.services.extractor import token_counts, vectorize


def test_token_counts_include_dom_attributes_and_javascript_identifiers() -> None:
    dom = '<div id="output" onclick="run()">Hello</div>'
    javascript = "document.getElementById('output').innerHTML = location.hash"
    counts = token_counts(dom, javascript)

    assert counts["div"] >= 1
    assert counts["onclick"] >= 1
    assert counts["document"] >= 1
    assert counts["innerhtml"] >= 1
    assert counts["location"] >= 1


def test_vectorize_uses_vocabulary_indices() -> None:
    vocabulary = {"document": 0, "innerhtml": 1, "location": 2}
    vector, metadata = vectorize(
        "<div></div>",
        "document.body.innerHTML = location.hash",
        vocabulary,
    )

    assert len(vector) == 3
    assert vector[0] >= 1
    assert vector[1] >= 1
    assert vector[2] >= 1
    assert metadata.matched_tokens >= 3
