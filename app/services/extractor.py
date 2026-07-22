from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from bs4 import BeautifulSoup

_IDENTIFIER_RE = re.compile(r"\.?[A-Za-z_$][A-Za-z0-9_$]*")
_EVENT_RE = re.compile(r"\bon[a-z][a-z0-9_-]*\b", re.IGNORECASE)


@dataclass(frozen=True)
class ExtractedFeatures:
    counts: Counter[str]
    matched_tokens: int
    total_tokens: int


def token_counts(rendered_dom: str, javascript: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    combined = f"{rendered_dom}\n{javascript}"

    for token in _IDENTIFIER_RE.findall(combined):
        normalized = token.lower().strip().lstrip(".")
        if len(normalized) >= 3:
            counts[normalized] += 1

    for event_name in _EVENT_RE.findall(rendered_dom):
        counts[event_name.lower()] += 1

    soup = BeautifulSoup(rendered_dom, "html.parser")
    for tag in soup.find_all(True):
        counts[tag.name.lower()] += 1
        for attribute in tag.attrs:
            counts[str(attribute).lower()] += 1

    return counts


def vectorize(
    rendered_dom: str,
    javascript: str,
    vocabulary: dict[str, int],
) -> tuple[list[float], ExtractedFeatures]:
    counts = token_counts(rendered_dom, javascript)
    vector = [0.0] * len(vocabulary)
    matched = 0

    for token, count in counts.items():
        index = vocabulary.get(token)
        if index is None:
            continue
        vector[index] = float(count)
        matched += count

    return vector, ExtractedFeatures(
        counts=counts,
        matched_tokens=matched,
        total_tokens=sum(counts.values()),
    )
