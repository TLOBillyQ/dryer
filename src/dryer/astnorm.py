"""Normalize a tree-sitter tree the way dry4clj normalizes a Clojure form.

The name in call position stays: `filter`, `Println`, `map`, an operator, the
type constructed by `new`. Local names, field names, type names in argument
position, and literals become generic markers. Two functions that call the
same operations in the same shape therefore share a fingerprint set even when
their locals differ.

Lua's `~=`, `//`, `..`, and `#` count as operators only in Lua. Rust and
Python spell other tokens the same way, and their scores must not move.
"""

from __future__ import annotations

from dryer.shape import K
from dryer.treesitter import node_text

_SKIP = {
    "comment",
    "line_comment",
    "block_comment",
    "documentation_comment",
    "doc_comment",
}

_IDENTIFIERS = {
    "identifier",
    "type_identifier",
    "field_identifier",
    "property_identifier",
    "shorthand_property_identifier",
    "shorthand_property_identifier_pattern",
    "package_identifier",
}

_LITERALS = {
    "string",
    "string_literal",
    "interpreted_string_literal",
    "raw_string_literal",
    "char_literal",
    "rune_literal",
    "character_literal",
    "number",
    "integer",
    "float",
    "decimal_integer_literal",
    "hex_integer_literal",
    "octal_integer_literal",
    "binary_integer_literal",
    "decimal_floating_point_literal",
    "hex_floating_point_literal",
    "int_literal",
    "float_literal",
    "imaginary_literal",
    "integer_literal",
    "true",
    "false",
    "null",
    "nil",
    "none",
    "undefined",
    "null_literal",
    "boolean_literal",
    "template_string",
    "regex",
    "regex_literal",
}

_OPERATORS = {
    "+",
    "-",
    "*",
    "/",
    "%",
    "**",
    "==",
    "!=",
    "<",
    ">",
    "<=",
    ">=",
    "===",
    "!==",
    "&&",
    "||",
    "&",
    "|",
    "^",
    "<<",
    ">>",
    ">>>",
    "+=",
    "-=",
    "*=",
    "/=",
    "%=",
    "&=",
    "|=",
    "^=",
    "<<=",
    ">>=",
    ">>>=",
    "!",
    "~",
    "++",
    "--",
    "and",
    "or",
    "not",
    "??",
    "?.",
    "=",
    ":=",
    "=>",
    "?",
}

_LANGUAGE_OPERATORS = {
    "lua": frozenset({"~=", "//", "..", "#"}),
}

_CALLS = {
    "call",
    "function_call",
    "call_expression",
    "method_invocation",
    "object_creation_expression",
    "new_expression",
}

_ATTRIBUTES = {
    "attribute",
    "member_expression",
    "selector_expression",
    "field_access",
    "field_expression",
    "dot_index_expression",
    "method_index_expression",
}

_SCOPED = {
    "scoped_identifier",
    "scoped_type_identifier",
}

_ARG_LISTS = {"argument_list", "arguments"}
_TYPE_ARGS = {"type_arguments", "type_parameters"}

_DATA: bytes = b""
_EXTRA_OPERATORS: frozenset = frozenset()


def normalize(node, data: bytes, language: str | None = None):
    """Normalized tree for `node`, or None when the node is only punctuation."""

    global _DATA, _EXTRA_OPERATORS
    _DATA = data
    _EXTRA_OPERATORS = _LANGUAGE_OPERATORS.get(language, frozenset())
    return _normalize(node)


def _text(node) -> str:
    return node_text(_DATA, node)


def _normalize(node, head: bool = False):
    if node.type in _SKIP:
        return None
    if node.type in _OPERATORS or node.type in _EXTRA_OPERATORS:
        return [K("symbol"), node.type]
    if not node.is_named:
        return None
    if node.type in _IDENTIFIERS:
        if head:
            return [K("symbol"), _text(node)]
        return K("symbol")
    if _is_literal(node):
        return K("literal")
    if node.type == "parenthesized_expression":
        named = node.named_children
        if len(named) == 1:
            return _normalize(named[0], head)
    if node.type in _CALLS:
        return _normalize_call(node)
    if node.type in _ATTRIBUTES:
        return _normalize_attr(node, head)
    children = []
    for child in node.children:
        norm = _normalize(child, False)
        if norm is not None:
            children.append(norm)
    return [K(node.type), *children]


def _is_literal(node) -> bool:
    if node.type not in _LITERALS:
        return False
    if node.type == "string" and any(child.type == "interpolation" for child in node.children):
        return False
    return True


def _named_before_args(node):
    incoming = []
    for child in node.named_children:
        if child.type in _ARG_LISTS:
            return incoming, child
        incoming.append(child)
    return incoming, None


def _without_type_args(nodes):
    type_args = [child for child in nodes if child.type in _TYPE_ARGS]
    rest = [child for child in nodes if child.type not in _TYPE_ARGS]
    return rest, type_args


def _extend_normalized(out, nodes) -> None:
    for node in nodes:
        norm = _normalize(node, False)
        if norm is not None:
            out.append(norm)


def _normalize_call(node):
    incoming, args = _named_before_args(node)
    rest, type_args = _without_type_args(incoming)
    out = [K(node.type)]
    if rest:
        *receivers, callee = rest
        _extend_normalized(out, receivers)
        out.append(_normalize_callee(callee))
    _extend_normalized(out, type_args)
    if args is not None:
        _extend_normalized(out, [args])
    return out


def _normalize_callee(node):
    if node.type in _IDENTIFIERS:
        return [K("symbol"), _text(node)]
    if node.type in _ATTRIBUTES:
        return _normalize_attr(node, True)
    if node.type in _SCOPED or node.type == "generic_type":
        return _normalize_path(node)
    return _normalize(node, True)


def _normalize_path(node):
    """A callee path keeps each name in the path. Type arguments stay structural."""

    parts = [K(node.type)]
    for child in node.named_children:
        if child.type in _IDENTIFIERS:
            parts.append([K("symbol"), _text(child)])
        elif child.type in _SCOPED or child.type == "generic_type":
            parts.append(_normalize_path(child))
        else:
            norm = _normalize(child, False)
            if norm is not None:
                parts.append(norm)
    return parts


def _normalized_name(name, head: bool):
    """Keep a member's spelling when it is the thing being called."""

    if name.type in _IDENTIFIERS:
        if head:
            return [K("symbol"), _text(name)]
        return K("symbol")
    if head:
        return _normalize_callee(name)
    return _normalize(name, False)


def _normalize_attr(node, head: bool):
    named = list(node.named_children)
    if not named:
        return [K(node.type)]
    *objects, name = named
    parts = [K(node.type)]
    for obj in objects:
        norm = _normalize(obj, False)
        if norm is not None:
            parts.append(norm)
    nested = _normalized_name(name, head)
    if nested is not None:
        parts.append(nested)
    return parts
