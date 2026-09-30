from pathlib import Path

from dryer.cli import main, parse_args, run
from dryer.discover import language_of


def write_source(root: Path, name: str, text: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_language_detection():
    assert language_of("src/app/core.clj") == "clojure"
    assert language_of("src/app/core.cljd") == "clojure"
    assert language_of("Widget.java") == "java"
    assert language_of("board.go") == "go"
    assert language_of("ui/view.tsx") == "typescript"
    assert language_of("src/lib.rs") == "rust"
    assert language_of("src/dryer/cli.py") == "python"
    assert language_of("types.d.ts") is None
    assert language_of("notes.md") is None


def test_help_does_not_scan(capsys):
    assert run(["--help"]) == 0
    out = capsys.readouterr().out
    assert "Usage: dryer" in out
    assert "--threshold" in out


def test_unknown_format(capsys):
    assert run(["--format", "csv"]) == 2
    err = capsys.readouterr().err
    assert err == "Unknown format: csv\n"


def test_unknown_option(capsys):
    assert run(["--nope"]) == 1
    assert "Unknown option: --nope" in capsys.readouterr().err


def test_parse_defaults_and_flags():
    options = parse_args(
        ["--threshold", "0.9", "--min-lines", "5", "--min-nodes", "30", "--edn", "spec"]
    )
    assert options.threshold == 0.9
    assert options.min_lines == 5
    assert options.min_nodes == 30
    assert options.format == "edn"
    assert options.positionals == ["spec"]


def test_project_report_and_snapshot(tmp_path, capsys):
    write_source(
        tmp_path,
        "src/left.py",
        "def alpha(xs):\n    ys = filter(xs, odd)\n    zs = map(ys, inc)\n    return list(zs)\n",
    )
    write_source(
        tmp_path,
        "src/right.py",
        "def beta(items):\n    kept = filter(items, even)\n    out = map(kept, dec)\n    return list(out)\n",
    )
    write_source(
        tmp_path,
        "tests/test_left.py",
        "def alpha(xs):\n    ys = filter(xs, odd)\n    zs = map(ys, inc)\n    return list(zs)\n",
    )
    code = run(["--root", str(tmp_path), "--min-lines", "3", "--min-nodes", "1"])
    captured = capsys.readouterr()
    assert code == 0
    assert "DUPLICATE score=1.00" in captured.out
    assert "src/left.py:1-" in captured.out
    assert "src/right.py:1-" in captured.out
    assert "test_left.py" not in captured.out
    text = (tmp_path / ".metrics" / "dry.edn").read_text(encoding="utf-8")
    assert ':language "python"' in text
    assert ':file "src/left.py"' in text
    assert "Wrote" in captured.err


def test_edn_stdout(tmp_path, capsys):
    write_source(tmp_path, "one.py", "def alpha(xs):\n    return xs\n")
    assert run(["--root", str(tmp_path), "--edn", "--min-lines", "1", "--min-nodes", "1"]) == 0
    out = capsys.readouterr().out
    assert out == "{:candidates []}\n"


def test_empty_project(tmp_path, capsys):
    assert run(["--root", str(tmp_path)]) == 0
    assert capsys.readouterr().out == "No source files to analyze.\n"


def test_path_filter(tmp_path, capsys):
    body_a = "def alpha(xs):\n    ys = filter(xs, odd)\n    zs = map(ys, inc)\n    return list(zs)\n"
    body_b = "def beta(items):\n    kept = filter(items, even)\n    out = map(kept, dec)\n    return list(out)\n"
    write_source(tmp_path, "src/board/a.py", body_a)
    write_source(tmp_path, "src/board/b.py", body_b)
    write_source(tmp_path, "src/other/a.py", body_a)
    write_source(tmp_path, "src/other/b.py", body_b)
    assert run(["--root", str(tmp_path), "--min-lines", "3", "--min-nodes", "1", "board"]) == 0
    out = capsys.readouterr().out
    assert "src/board/a.py" in out
    assert "src/other/a.py" not in out


def test_explicit_test_file_is_included(tmp_path, capsys):
    body = "def alpha(xs):\n    ys = filter(xs, odd)\n    zs = map(ys, inc)\n    return list(zs)\n"
    other = "def beta(items):\n    kept = filter(items, even)\n    out = map(kept, dec)\n    return list(out)\n"
    write_source(tmp_path, "src/a.py", body)
    write_source(tmp_path, "tests/test_a.py", other)
    assert (
        run(
            [
                "--root",
                str(tmp_path),
                "--min-lines",
                "3",
                "--min-nodes",
                "1",
                "src/a.py",
                "tests/test_a.py",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "src/a.py" in out
    assert "tests/test_a.py" in out


def test_main_exits(monkeypatch):
    codes = []
    monkeypatch.setattr("dryer.cli.sys.exit", lambda code: codes.append(code))
    main(["--help"])
    assert codes == [0]
