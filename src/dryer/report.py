"""Text and EDN reports. The text layout matches dry4clj."""

from __future__ import annotations

from pathlib import Path

from dryer.model import Duplicate


def format_text(candidates: list[Duplicate]) -> str:
    if not candidates:
        return "No duplicate candidates found.\n"
    blocks = []
    for candidate in candidates:
        left = candidate.left
        right = candidate.right
        blocks.append(
            f"DUPLICATE score={candidate.score:.2f}\n"
            f"  {left.file}:{left.start_line}-{left.end_line}\n"
            f"  {right.file}:{right.start_line}-{right.end_line}"
        )
    return "\n\n".join(blocks) + "\n"


def _edn_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _edn_float(value: float) -> str:
    text = f"{value:.12f}".rstrip("0").rstrip(".")
    if "." not in text:
        text += ".0"
    return text


def render_edn(candidates: list[Duplicate]) -> str:
    """EDN map `{:candidates [...]}` with dry4clj's keys, plus `:language`."""

    if not candidates:
        return "{:candidates []}\n"
    rows = []
    for candidate in candidates:
        left = candidate.left
        right = candidate.right
        rows.append(
            " {:score "
            + _edn_float(candidate.score)
            + "\n  :language "
            + _edn_string(candidate.language)
            + "\n  :left {:file "
            + _edn_string(left.file)
            + f", :start-line {left.start_line}, :end-line {left.end_line}"
            + "}"
            + "\n  :right {:file "
            + _edn_string(right.file)
            + f", :start-line {right.start_line}, :end-line {right.end_line}"
            + "}"
            + f"\n  :left-nodes {candidate.left_nodes}"
            + f"\n  :right-nodes {candidate.right_nodes}"
            + "}"
        )
    return "{:candidates [\n" + "\n".join(rows) + "\n]}\n"


def metrics_path(root: Path) -> Path:
    return root / ".metrics" / "dry.edn"


def write_metrics(candidates: list[Duplicate], root: Path) -> Path:
    path = metrics_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_edn(candidates), encoding="utf-8")
    return path
