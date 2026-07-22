from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

import tree_sitter_javascript
from bs4 import BeautifulSoup
from tree_sitter import Language, Node, Parser

_LANGUAGE = Language(tree_sitter_javascript.language())
_FUNCTION_NODES = {
    "arrow_function",
    "function_declaration",
    "function_expression",
    "generator_function",
    "generator_function_declaration",
    "method_definition",
}
_IDENTIFIER_NODES = {
    "identifier",
    "private_property_identifier",
    "property_identifier",
    "shorthand_property_identifier",
}
_LITERAL_KIND = {
    "array": "array",
    "array_pattern": "array",
    "false": "boolean",
    "function_declaration": "function",
    "function_expression": "function",
    "generator_function": "function",
    "generator_function_declaration": "function",
    "method_definition": "function",
    "number": "number",
    "object": "object",
    "object_pattern": "object",
    "regex": "regexp",
    "string": "string",
    "template_string": "string",
    "true": "boolean",
}
_OPERATOR_NAMES = {
    "!": "not",
    "!=": "ne",
    "!==": "ne_strict",
    "%": "mod",
    "%=": "assign_mod",
    "&": "bit_and",
    "&&": "and",
    "&=": "assign_bit_and",
    "*": "mul",
    "**": "exp",
    "**=": "assign_exp",
    "*=": "assign_mul",
    "+": "add",
    "++": "inc",
    "+=": "assign_add",
    ",": "comma",
    "-": "sub",
    "--": "dec",
    "-=": "assign_sub",
    "/": "div",
    "/=": "assign_div",
    "<": "lt",
    "<<": "shl",
    "<<=": "assign_shl",
    "<=": "lte",
    "=": "assign",
    "==": "eq",
    "===": "eq_strict",
    ">": "gt",
    ">=": "gte",
    ">>": "sar",
    ">>=": "assign_sar",
    ">>>": "shr",
    ">>>=": "assign_shr",
    "?": "conditional",
    "^": "bit_xor",
    "^=": "assign_bit_xor",
    "delete": "delete",
    "in": "in",
    "instanceof": "instanceof",
    "typeof": "typeof",
    "void": "void",
    "|": "bit_or",
    "|=": "assign_bit_or",
    "||": "or",
    "~": "bit_not",
}
_TOKEN_CLEANUP = re.compile(r"^[\s'\"`]+|[\s'\"`]+$")


@dataclass(frozen=True)
class CodeUnit:
    source: str
    kind: str


@dataclass(frozen=True)
class ExtractedFeatures:
    counts: Counter[str]
    matched_tokens: int
    total_tokens: int


def _parser() -> Parser:
    return Parser(_LANGUAGE)


def _walk(node: Node) -> list[Node]:
    nodes: list[Node] = []
    stack = [node]
    while stack:
        current = stack.pop()
        nodes.append(current)
        stack.extend(reversed(current.children))
    return nodes


def _node_text(node: Node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="ignore")


def _valid_term(value: str) -> str | None:
    normalized = _TOKEN_CLEANUP.sub("", value).lower().strip()
    if len(normalized) < 3 or normalized.isnumeric():
        return None
    if not any(character.isalnum() or character in "_$<>./" for character in normalized):
        return None
    return normalized


def ast_token_counts(source_code: str) -> Counter[str]:
    """Build the function-level AST bag-of-words used by the ML feature contract."""
    source = source_code.encode("utf-8", errors="ignore")
    if not source:
        return Counter()

    tree = _parser().parse(source)
    counts: Counter[str] = Counter()

    for node in _walk(tree.root_node):
        if node.type in _IDENTIFIER_NODES and (term := _valid_term(_node_text(node, source))):
            counts[term] += 1

        literal_kind = _LITERAL_KIND.get(node.type)
        if literal_kind:
            counts[literal_kind] += 1

        if node.type in {"string_fragment", "template_chars"} and (
            term := _valid_term(_node_text(node, source))
        ):
            counts[term] += 1

        if node.type == "call_expression":
            counts["call"] += 1
        elif node.type == "variable_declarator" and node.child_by_field_name("value"):
            counts["assign"] += 1

        if node.type in {
            "assignment_expression",
            "augmented_assignment_expression",
            "binary_expression",
            "sequence_expression",
            "ternary_expression",
            "unary_expression",
            "update_expression",
        }:
            for child in node.children:
                if child.is_named:
                    continue
                operator = _node_text(child, source).strip()
                if name := _OPERATOR_NAMES.get(operator):
                    counts[name] += 1

    return counts


def _inline_handler_units(rendered_dom: str) -> list[CodeUnit]:
    if not rendered_dom:
        return []
    soup = BeautifulSoup(rendered_dom, "html.parser")
    units: list[CodeUnit] = []
    for tag in soup.find_all(True):
        for attribute, raw_value in tag.attrs.items():
            value = " ".join(raw_value) if isinstance(raw_value, list) else str(raw_value)
            attribute_name = str(attribute).lower()
            if attribute_name.startswith("on") and value.strip():
                units.append(CodeUnit(value.strip(), "inline-handler"))
            elif attribute_name in {"action", "formaction", "href", "src"}:
                prefix, separator, code = value.partition(":")
                if separator and prefix.strip().lower() == "javascript" and code.strip():
                    units.append(CodeUnit(code.strip(), "javascript-url"))
    return units


def extract_code_units(
    rendered_dom: str,
    javascript: str,
    *,
    max_units: int,
    max_unit_bytes: int,
) -> list[CodeUnit]:
    """Segment collected JavaScript into function-sized units before inference."""
    units = _inline_handler_units(rendered_dom)
    source = javascript.encode("utf-8", errors="ignore")
    if source:
        tree = _parser().parse(source)
        function_nodes = [node for node in _walk(tree.root_node) if node.type in _FUNCTION_NODES]
        for node in function_nodes:
            text = _node_text(node, source).strip()
            if text:
                units.append(CodeUnit(text, "function"))

        function_ranges = [(node.start_byte, node.end_byte) for node in function_nodes]
        for child in tree.root_node.named_children:
            if any(
                start <= child.start_byte and child.end_byte <= end
                for start, end in function_ranges
            ):
                continue
            text = _node_text(child, source).strip()
            if text:
                units.append(CodeUnit(text, "top-level"))

    bounded: list[CodeUnit] = []
    seen: set[str] = set()
    for unit in units:
        encoded = unit.source.encode("utf-8", errors="ignore")
        if not encoded:
            continue
        text = encoded[:max_unit_bytes].decode("utf-8", errors="ignore")
        fingerprint = f"{unit.kind}\0{text}"
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        bounded.append(CodeUnit(text, unit.kind))
        if len(bounded) >= max_units:
            break
    return bounded


def vectorize_counts(
    counts: Counter[str],
    vocabulary: dict[str, int],
) -> tuple[list[float], ExtractedFeatures]:
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
