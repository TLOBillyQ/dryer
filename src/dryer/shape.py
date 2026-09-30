"""Jaccard similarity over structural fingerprints.

This is the dry4clj score. A normalized form is a tree of keywords, names, and
vectors. The fingerprint set contains the printed form of every subtree. The
score is the size of the shared set divided by the size of the union.
"""

from __future__ import annotations


class K:
    """A keyword in the normalized tree. Prints the way Clojure prints keywords."""

    def __init__(self, name: str):
        self.name = name

    def __repr__(self) -> str:
        return ":" + self.name


def pr(node) -> str:
    """Print a normalized node the way Clojure `pr-str` prints it."""

    if isinstance(node, K):
        return ":" + node.name
    if isinstance(node, str):
        escaped = node.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if isinstance(node, list):
        return "[" + " ".join(pr(child) for child in node) + "]"
    raise TypeError(f"cannot print {node!r}")


def node_count(node) -> int:
    """One plus the count of every nested node. Atoms count as one."""

    if isinstance(node, list):
        return 1 + sum(node_count(child) for child in node)
    return 1


def fingerprints(node) -> frozenset[str]:
    found: set[str] = set()

    def walk(form) -> None:
        found.add(pr(form))
        if isinstance(form, list):
            for child in form:
                walk(child)

    walk(node)
    return frozenset(found)


def jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)
