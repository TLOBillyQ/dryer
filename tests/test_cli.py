from pathlib import Path

import pytest

from dryer.cli import _changed_files, _count, _tracked_source, main, parse_args, run, select_files
from dryer.discover import is_test_file, iter_source_files, language_of


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
    assert language_of("src/calc/init.lua") == "lua"
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


def test_names_that_are_tests():
    names = [
        "pkg/foo_test.go",
        "src/app_test.clj",
        "src/app_test.cljc",
        "src/app_test.cljs",
        "src/app_test.cljd",
        "src/app_test.bb",
        "ui/a.test.ts",
        "ui/a.spec.ts",
        "ui/a.test.tsx",
        "ui/a.spec.tsx",
        "ui/a.test.mts",
        "ui/a.spec.mts",
        "tests/conftest.py",
        "pkg/foo_test.py",
        "pkg/test_foo.py",
        "tests/app.py",
    ]
    for name in names:
        assert is_test_file(name), name
    assert not is_test_file("src/app.py")


class _Git:
    def __init__(self, returncode, stdout, stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_changed_files_reads_porcelain(tmp_path, monkeypatch):
    stdout = ' M src/a.py\nR  old.py -> src/b.py\n?? "src/c d.py"\n\nX\n'
    monkeypatch.setattr(
        "dryer.cli.subprocess.run",
        lambda *args, **kwargs: _Git(0, stdout),
    )
    assert _changed_files(tmp_path) == [
        (tmp_path / "src/a.py").resolve(),
        (tmp_path / "src/b.py").resolve(),
        (tmp_path / "src/c d.py").resolve(),
    ]


def test_changed_files_reports_git_failure(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        "dryer.cli.subprocess.run",
        lambda *args, **kwargs: _Git(1, "", "fatal: not a git repository\n"),
    )
    assert _changed_files(tmp_path) == []
    assert capsys.readouterr().err == "fatal: not a git repository\n"

    monkeypatch.setattr(
        "dryer.cli.subprocess.run",
        lambda *args, **kwargs: _Git(1, "", "  \n"),
    )
    assert _changed_files(tmp_path) == []
    assert capsys.readouterr().err == "git status failed\n"


def test_changed_limits_the_report(tmp_path, monkeypatch, capsys):
    body = "def alpha(xs):\n    ys = filter(xs, odd)\n    zs = map(ys, inc)\n    return list(zs)\n"
    other = "def beta(items):\n    kept = filter(items, even)\n    out = map(kept, dec)\n    return list(out)\n"
    write_source(tmp_path, "src/a.py", body)
    write_source(tmp_path, "src/b.py", other)
    write_source(tmp_path, "src/c.py", body)
    write_source(tmp_path, "tests/test_a.py", other)
    stdout = " M src/a.py\n M src/b.py\n M tests/test_a.py\n ?? README.md\n"
    monkeypatch.setattr(
        "dryer.cli.subprocess.run",
        lambda *args, **kwargs: _Git(0, stdout),
    )
    assert run(["--root", str(tmp_path), "--changed", "--min-lines", "3", "--min-nodes", "1"]) == 0
    out = capsys.readouterr().out
    assert "src/a.py" in out
    assert "src/b.py" in out
    assert "src/c.py" not in out
    assert "test_a.py" not in out


def test_an_option_without_a_value_is_a_usage_error(capsys):
    assert run(["--threshold"]) == 1
    assert "--threshold requires a value" in capsys.readouterr().err


def test_an_empty_value_is_rejected(capsys):
    assert run(["file.py", "--min-lines", ""]) == 1
    assert "--min-lines requires a value" in capsys.readouterr().err


def test_a_flag_is_not_a_value(capsys):
    assert run(["--min-lines", "--min-nodes", "1"]) == 1
    assert "--min-lines requires a value" in capsys.readouterr().err


def test_zero_is_a_valid_count():
    options = parse_args(["--min-lines", "0", "--min-nodes", "0"])
    assert options.action == "scan"
    assert options.min_lines == 0
    assert options.min_nodes == 0


def test_a_negative_count_is_rejected():
    with pytest.raises(ValueError, match="non-negative"):
        _count("-1", "--min-lines")


def test_a_count_must_be_an_integer(capsys):
    assert run(["--min-lines", "nope"]) == 1
    assert "--min-lines requires an integer" in capsys.readouterr().err


def test_a_threshold_must_be_a_number(capsys):
    assert run(["--threshold", "nope"]) == 1
    assert "--threshold requires a number" in capsys.readouterr().err


def test_parse_reads_the_process_arguments(monkeypatch):
    monkeypatch.setattr("dryer.cli.sys.argv", ["dryer", "only-this"])
    assert parse_args().positionals == ["only-this"]


def test_text_format_wins_when_it_comes_last(tmp_path, capsys):
    write_source(tmp_path, "one.py", "def alpha(xs):\n    return xs\n")
    assert run(["--root", str(tmp_path), "--edn", "--text", "--min-lines", "1", "--min-nodes", "1"]) == 0
    assert capsys.readouterr().out == "No duplicate candidates found.\n"


def test_source_root_limits_the_walk(tmp_path):
    write_source(tmp_path, "src/a.py", "x = 1\n")
    write_source(tmp_path, "extra/b.py", "x = 1\n")
    options = parse_args(["--root", str(tmp_path), "--source-root", "src"])
    files = [path.relative_to(tmp_path).as_posix() for path in select_files(options)]
    assert files == ["src/a.py"]


def test_git_status_asks_for_text_without_checking(tmp_path, monkeypatch):
    seen = {}

    def fake_run(args, **kwargs):
        seen["args"] = args
        seen["kwargs"] = kwargs
        return _Git(0, " M src/a.py\n")

    monkeypatch.setattr("dryer.cli.subprocess.run", fake_run)
    assert _changed_files(tmp_path) == [(tmp_path / "src/a.py").resolve()]
    assert seen["args"] == ["git", "status", "--porcelain"]
    assert seen["kwargs"]["check"] is False
    assert seen["kwargs"]["capture_output"] is True
    assert seen["kwargs"]["text"] is True
    assert seen["kwargs"]["cwd"] == tmp_path


def test_a_status_line_of_four_characters_is_a_path(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "dryer.cli.subprocess.run",
        lambda *args, **kwargs: _Git(0, " M a\n"),
    )
    assert _changed_files(tmp_path) == [(tmp_path / "a").resolve()]


def test_changed_source_skips_unknown_and_test_files(tmp_path):
    assert _tracked_source(tmp_path / "README.md") is False
    assert _tracked_source(tmp_path / "tests" / "test_a.py") is False
    assert _tracked_source(tmp_path / "src" / "a.py") is True


def test_test_files_and_skipped_directories_are_left_out(tmp_path):
    write_source(tmp_path, "src/app.py", "x = 1\n")
    write_source(tmp_path, "src/foo_test.py", "x = 1\n")
    write_source(tmp_path, "target/app.py", "x = 1\n")
    write_source(tmp_path, "tests/app.py", "x = 1\n")
    relative = [path.relative_to(tmp_path).as_posix() for path in iter_source_files([tmp_path])]
    assert relative == ["src/app.py"]


def test_a_second_report_replaces_the_snapshot(tmp_path, capsys):
    write_source(tmp_path, "one.py", "def alpha(xs):\n    return xs\n")
    args = ["--root", str(tmp_path), "--min-lines", "1", "--min-nodes", "1"]
    assert run(args) == 0
    assert run(args) == 0
    assert (tmp_path / ".metrics" / "dry.edn").read_text(encoding="utf-8") == "{:candidates []}\n"


def test_lua_fixture_reports_the_copied_function(tmp_path, monkeypatch):
    import shutil
    from pathlib import Path

    project = tmp_path / "lua_project"
    shutil.copytree(Path(__file__).parent / "fixtures" / "lua_project", project)
    monkeypatch.chdir(project)
    run([])
    snapshot = (project / ".metrics" / "dry.edn").read_text(encoding="utf-8")
    assert ':language "lua"' in snapshot
    assert ':left {:file "src/calc/init.lua", :start-line 14, :end-line 20}' in snapshot
    assert ':right {:file "src/calc/stats.lua", :start-line 5, :end-line 11}' in snapshot
