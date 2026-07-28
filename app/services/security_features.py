from __future__ import annotations

from collections import Counter
from collections.abc import Mapping

FEATURE_CONTRACT = "cmu-ast-bow-security-interactions-v2"

SOURCE_GROUPS: dict[str, tuple[frozenset[str], ...]] = {
    "url": (
        frozenset({"location"}),
        frozenset({"hash"}),
        frozenset({"search"}),
        frozenset({"href"}),
        frozenset({"pathname"}),
    ),
    "cookie": (frozenset({"cookie"}),),
    "referrer": (frozenset({"referrer"}),),
    "storage": (
        frozenset({"localstorage"}),
        frozenset({"sessionstorage"}),
    ),
    "message": (
        frozenset({"postmessage"}),
        frozenset({"message", "data"}),
    ),
    "window_name": (frozenset({"window", "name"}),),
}

SINK_GROUPS: dict[str, tuple[frozenset[str], ...]] = {
    "inner_html": (frozenset({"innerhtml"}),),
    "outer_html": (frozenset({"outerhtml"}),),
    "insert_html": (frozenset({"insertadjacenthtml"}),),
    "script_eval": (frozenset({"eval"}),),
    "document_write": (frozenset({"document", "write"}),),
}

SANITIZER_GROUPS: dict[str, tuple[frozenset[str], ...]] = {
    "dompurify": (
        frozenset({"dompurify", "sanitize"}),
        frozenset({"dompurify"}),
    ),
}


def _present_groups(
    tokens: set[str],
    groups: Mapping[str, tuple[frozenset[str], ...]],
) -> list[str]:
    return [
        name
        for name, alternatives in groups.items()
        if any(required.issubset(tokens) for required in alternatives)
    ]


def augment_security_features(counts: Mapping[str, int]) -> Counter[str]:
    """Add the same co-occurrence features used during model training."""

    augmented = Counter({str(token): int(value) for token, value in counts.items()})
    present_tokens = {token for token, value in augmented.items() if value > 0}
    sources = _present_groups(present_tokens, SOURCE_GROUPS)
    sinks = _present_groups(present_tokens, SINK_GROUPS)
    sanitizers = _present_groups(present_tokens, SANITIZER_GROUPS)

    for source in sources:
        augmented[f"sec_source_{source}"] = 1
    for sink in sinks:
        augmented[f"sec_sink_{sink}"] = 1
    for sanitizer in sanitizers:
        augmented[f"sec_sanitizer_{sanitizer}"] = 1
    for source in sources:
        for sink in sinks:
            augmented[f"sec_pair_{source}_{sink}"] = 1

    return augmented
