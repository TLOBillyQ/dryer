from pathlib import Path

from dryer.report import format_text
from dryer.scan import find_duplicates, scan_files
from dryer.model import Duplicate, Span


def write_source(root: Path, name: str, text: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def duplicates(root: Path, **options):
    files = sorted(path for path in root.rglob("*") if path.is_file())
    entries, warnings = scan_files(
        files,
        root,
        options.get("min_lines", 4),
        options.get("min_nodes", 20),
    )
    assert warnings == []
    return find_duplicates(entries, options.get("threshold", 0.82))


def test_text_report_matches_dry4clj():
    candidate = Duplicate(
        0.875,
        "clojure",
        Span("a.clj", 10, 14),
        Span("b.clj", 20, 24),
        30,
        31,
    )
    assert (
        format_text([candidate])
        == "DUPLICATE score=0.88\n  a.clj:10-14\n  b.clj:20-24\n"
    )
    assert format_text([]) == "No duplicate candidates found.\n"


def test_reports_structural_duplicates_with_line_ranges(tmp_path):
    write_source(
        tmp_path,
        "left.cljc",
        "(ns sample.left)\n\n(defn alpha [xs]\n  (let [ys (filter odd? xs)]\n    (map inc ys)))\n",
    )
    write_source(
        tmp_path,
        "right.cljc",
        "(ns sample.right)\n\n(defn beta [items]\n  (let [kept (filter even? items)]\n    (map dec kept)))\n",
    )
    found = duplicates(tmp_path, threshold=0.80, min_lines=3, min_nodes=8)
    assert len(found) == 1
    assert found[0].score == 1.0
    assert found[0].language == "clojure"
    assert found[0].left.file == "left.cljc"
    assert (found[0].left.start_line, found[0].left.end_line) == (3, 5)
    assert found[0].right.file == "right.cljc"
    assert (found[0].right.start_line, found[0].right.end_line) == (3, 5)


def test_matches_maps_sets_and_keyword_calls(tmp_path):
    write_source(
        tmp_path,
        "left.cljc",
        "(ns sample.left)\n\n(defn gamma [m]\n  (when (#{:a :b} (:kind m))\n    {:left (:a m) :right (:b m)}))\n",
    )
    write_source(
        tmp_path,
        "right.cljc",
        "(ns sample.right)\n\n(defn delta [row]\n  (when (#{:c :d} (:kind row))\n    {:left (:c row) :right (:d row)}))\n",
    )
    found = duplicates(tmp_path, threshold=0.80, min_lines=3, min_nodes=8)
    assert len(found) == 1
    assert found[0].score == 1.0


def test_reads_cljc_reader_conditionals(tmp_path):
    write_source(
        tmp_path,
        "left.cljc",
        "(ns sample.left)\n\n(defn alpha [x]\n  #?(:clj (when (pos? x)\n            (inc x))))\n",
    )
    write_source(
        tmp_path,
        "right.cljc",
        "(ns sample.right)\n\n(defn beta [y]\n  #?(:clj (when (pos? y)\n            (inc y))))\n",
    )
    found = duplicates(tmp_path, threshold=0.50, min_lines=1, min_nodes=1)
    assert len(found) == 1
    assert found[0].score == 1.0


def test_filters_forms_shorter_than_the_minimum_line_count(tmp_path):
    write_source(tmp_path, "one.clj", "(ns one)\n(defn a [x] (+ x 1))\n")
    write_source(tmp_path, "two.clj", "(ns two)\n(defn b [y] (+ y 2))\n")
    assert duplicates(tmp_path, threshold=0.80, min_lines=3, min_nodes=1) == []


def test_metadata_comments_and_discards_are_not_structure(tmp_path):
    write_source(
        tmp_path,
        "left.clj",
        "(ns left)\n\n(defn alpha [xs] ; keep\n  #_(println xs)\n  (let [ys (filter odd? xs)]\n    (map inc ys)))\n",
    )
    write_source(
        tmp_path,
        "right.clj",
        "(ns right)\n\n(defn ^String beta [items]\n  (let [kept (filter even? items)]\n    (map dec kept)))\n",
    )
    found = duplicates(tmp_path, threshold=0.80, min_lines=3, min_nodes=8)
    assert len(found) == 1
    assert found[0].score == 1.0


def test_extra_binding_scores_below_one(tmp_path):
    write_source(
        tmp_path,
        "invoice.clj",
        """(ns billing.invoice)

(defn invoice-summary [orders]
  (let [paid (filter paid? orders), domestic (filter domestic? paid)
        sorted (sort-by :date domestic), amounts (map :amount sorted)
        taxes (map tax amounts), ids (map :id sorted)
        customers (map :customer sorted), regions (group-by :region sorted)
        flagged (filter flagged? sorted)]
    {:count (count sorted)
     :first-id (first ids), :last-id (last ids)
     :customers (set customers), :regions (keys regions)
     :flagged (count flagged), :total (reduce + 0 amounts)
     :tax (reduce + 0 taxes)}))
""",
    )
    write_source(
        tmp_path,
        "receipt.clj",
        """(ns billing.receipt)

(defn receipt-summary [rows]
  (let [closed (filter closed? rows), local (filter local? closed)
        ordered (sort-by :date local), amounts (map :amount ordered)
        taxable (filter taxable? ordered), taxes (map tax amounts)
        ids (map :id ordered), customers (map :customer ordered)
        regions (group-by :region ordered)
        flagged (filter flagged? ordered)]
    {:count (count ordered)
     :first-id (first ids), :last-id (last ids)
     :customers (set customers), :regions (keys regions)
     :flagged (count flagged), :total (reduce + 0 amounts)
     :tax (reduce + 0 taxes)}))
""",
    )
    found = duplicates(tmp_path)
    assert len(found) == 1
    assert 0.85 <= found[0].score < 1.0


def test_three_copies_make_three_pairs(tmp_path):
    body = "(let [ys (filter odd? xs)]\n    (map inc ys))"
    write_source(
        tmp_path,
        "same.clj",
        f"(ns same)\n\n(defn a [xs]\n  {body})\n\n(defn b [xs]\n  {body})\n\n(defn c [xs]\n  {body})\n",
    )
    found = duplicates(tmp_path, threshold=0.80, min_lines=3, min_nodes=8)
    assert len(found) == 3
    assert {item.score for item in found} == {1.0}


def test_unreadable_tail_does_not_drop_an_earlier_form(tmp_path):
    write_source(
        tmp_path,
        "left.clj",
        "(ns left)\n\n(defn alpha [xs]\n  (let [ys (filter odd? xs)]\n    (map inc ys)))\n(defn broken [x]\n",
    )
    write_source(
        tmp_path,
        "right.clj",
        "(ns right)\n\n(defn beta [items]\n  (let [kept (filter even? items)]\n    (map dec kept)))\n",
    )
    files = sorted(tmp_path.glob("*.clj"))
    entries, warnings = scan_files(files, tmp_path, 3, 8)
    assert warnings == ["left.clj:6: unterminated list"]
    found = find_duplicates(entries, 0.80)
    assert len(found) == 1
