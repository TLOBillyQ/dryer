"""Normalize a tree-sitter tree the way dry4clj normalizes a Clojure form.

The name in call position stays: `filter`, `Println`, `map`, an operator, the
type constructed by `new`. Local names, field names, type names in argument
position, and literals become generic markers. Two functions that call the
same operations in the same shape therefore share a fingerprint set even when
their locals differ.
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

_CALLS = {
    "call",
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
}

_SCOPED = {
    "scoped_identifier",
    "scoped_type_identifier",
}

_ARG_LISTS = {"argument_list", "arguments"}
_TYPE_ARGS = {"type_arguments", "type_parameters"}

_DATA: bytes = b""


def normalize(node, data: bytes):
    """Normalized tree for `node`, or None when the node is only punctuation."""

    global _DATA
    _DATA = data
    return _normalize(node)


def _text(node) -> str:
    return node_text(_DATA, node)


def _normalize(node, head: bool = False):
    if node.type in _SKIP:
        return None
    if node.type in _OPERATORS:
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


def _normalize_call(node):
    incoming = []
    args = None
    for child in node.named_children:
        if child.type in _ARG_LISTS:
            args = child
            break
        incoming.append(child)
    type_args = [child for child in incoming if child.type in _TYPE_ARGS]
    rest = [child for child in incoming if child.type not in _TYPE_ARGS]
    out = [K(node.type)]
    if rest:
        *receivers, callee = rest
        for receiver in receivers:
            norm = _normalize(receiver, False)
            if norm is not None:
                out.append(norm)
        out.append(_normalize_callee(callee))
    for type_node in type_args:
        norm = _normalize(type_node, False)
        if norm is not None:
            out.append(norm)
    if args is not None:
        norm = _normalize(args, False)
        if norm is not None:
            out.append(norm)
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


def _normalize_attr(node, head: bool):
    named = list(node.named_children)
    parts = [K(node.type)]
    if not named:
        return parts
    *objects, name = named
    for obj in objects:
        norm = _normalize(obj, False)
        if norm is not None:
            parts.append(norm)
    if name.type in _IDENTIFIERS:
        parts.append([K("symbol"), _text(name)] if head else K("symbol"))
    else:
        nested = _normalize_callee(name) if head else _normalize(name, False)
        if nested is not None:
            parts.append(nested)
    return parts
