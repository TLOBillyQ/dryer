from pathlib import Path

from dryer.scan import find_duplicates, scan_files


def write_source(root: Path, name: str, text: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def pairs(root: Path):
    files = sorted(path for path in root.rglob("*") if path.is_file())
    entries, warnings = scan_files(files, root, min_lines=1, min_nodes=1)
    assert warnings == []
    return find_duplicates(entries, threshold=0.99)


JAVA_LEFT = """\
class Left {
  int alpha(int[] xs) {
    int[] ys = filter(xs, odd);
    return map(ys, inc);
  }
}
"""

JAVA_RIGHT = """\
class Right {
  int beta(int[] items) {
    int[] kept = filter(items, even);
    return map(kept, dec);
  }
}
"""

GO_LEFT = """\
package demo

func (b *Board) alpha(xs []int) []int {
	ys := filter(xs, odd)
	return mapFn(ys, inc)
}
"""

GO_RIGHT = """\
package demo

func (p *Panel) beta(items []int) []int {
	kept := filter(items, even)
	return mapFn(kept, dec)
}
"""

PY_LEFT = """\
class Board:
    def alpha(self, xs):
        ys = filter(xs, odd)
        return map(ys, inc)
"""

PY_RIGHT = """\
class Panel:
    def beta(self, items):
        kept = filter(items, even)
        return map(kept, dec)
"""

TS_LEFT = """\
export function alpha(xs: number[]): number[] {
  const ys = filter(xs, odd);
  return map(ys, inc);
}
"""

TS_RIGHT = """\
export function beta(items: number[]): number[] {
  const kept = filter(items, even);
  return map(kept, dec);
}
"""

TSX_LEFT = """\
export const alpha = (xs: number[]): number[] => {
  const ys = filter(xs, odd);
  return map(ys, inc);
};
"""

TSX_RIGHT = """\
export const beta = (items: number[]): number[] => {
  const kept = filter(items, even);
  return map(kept, dec);
};
"""

RUST_LEFT = """\
pub fn alpha(xs: Vec<i32>) -> Vec<i32> {
    let ys = filter(xs, odd);
    map(ys, inc)
}
"""

RUST_RIGHT = """\
pub fn beta(items: Vec<i32>) -> Vec<i32> {
    let kept = filter(items, even);
    map(kept, dec)
}
"""


def test_each_language_matches_renamed_locals(tmp_path):
    samples = {
        "left.java": JAVA_LEFT,
        "right.java": JAVA_RIGHT,
        "left.go": GO_LEFT,
        "right.go": GO_RIGHT,
        "left.py": PY_LEFT,
        "right.py": PY_RIGHT,
        "left.ts": TS_LEFT,
        "right.ts": TS_RIGHT,
        "left.tsx": TSX_LEFT,
        "right.tsx": TSX_RIGHT,
        "left.rs": RUST_LEFT,
        "right.rs": RUST_RIGHT,
    }
    for name, source in samples.items():
        write_source(tmp_path, name, source)
    found = pairs(tmp_path)
    by_language = {}
    for item in found:
        by_language.setdefault(item.language, []).append(item)
    assert set(by_language) == {"java", "go", "python", "typescript", "rust"}
    assert [(item.left.file, item.right.file) for item in by_language["typescript"]] == [
        ("left.ts", "right.ts"),
        ("left.tsx", "right.tsx"),
    ]
    for language, group in by_language.items():
        assert all(item.score == 1.0 for item in group), language


def test_different_callee_is_not_the_same_structure(tmp_path):
    write_source(
        tmp_path,
        "a.py",
        "def alpha(xs):\n    return filter(xs, odd)\n",
    )
    write_source(
        tmp_path,
        "b.py",
        "def beta(xs):\n    return select(xs, odd)\n",
    )
    files = sorted(tmp_path.glob("*.py"))
    entries, warnings = scan_files(files, tmp_path, min_lines=1, min_nodes=1)
    assert warnings == []
    found = find_duplicates(entries, threshold=0.0)
    assert len(found) == 1
    assert found[0].score < 1.0


def test_nested_functions_stay_inside_the_enclosing_function(tmp_path):
    write_source(
        tmp_path,
        "a.py",
        """\
def alpha(xs):
    def inner(ys):
        return filter(ys, odd)
    return inner(xs)
""",
    )
    write_source(
        tmp_path,
        "b.py",
        """\
def beta(items):
    def inner(kept):
        return filter(kept, even)
    return inner(items)
""",
    )
    found = pairs(tmp_path)
    assert len(found) == 1
    assert found[0].score == 1.0
    assert found[0].left.start_line == 1


def test_rust_tests_module_is_not_production_code(tmp_path):
    write_source(
        tmp_path,
        "a.rs",
        """\
pub fn alpha(xs: Vec<i32>) -> Vec<i32> {
    let ys = filter(xs, odd);
    map(ys, inc)
}

mod tests {
    pub fn helper(xs: Vec<i32>) -> Vec<i32> {
        let ys = filter(xs, odd);
        map(ys, inc)
    }
}
""",
    )
    write_source(tmp_path, "b.rs", RUST_RIGHT)
    found = pairs(tmp_path)
    assert len(found) == 1
    assert found[0].left.file == "a.rs"
    assert found[0].left.start_line == 1


def test_an_extra_statement_lowers_the_score(tmp_path):
    write_source(tmp_path, "a.java", JAVA_LEFT)
    write_source(
        tmp_path,
        "b.java",
        """\
class Right {
  int beta(int[] items) {
    int[] kept = filter(items, even);
    int[] extra = filter(kept, even);
    return map(extra, dec);
  }
}
""",
    )
    files = sorted(tmp_path.glob("*.java"))
    entries, warnings = scan_files(files, tmp_path, min_lines=1, min_nodes=1)
    assert warnings == []
    found = find_duplicates(entries, threshold=0.5)
    assert len(found) == 1
    assert found[0].score < 1.0
