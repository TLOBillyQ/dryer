"""Read Clojure source into forms and normalize them the way dry4clj does.

Names in argument position, keywords, and literals become generic markers.
The symbol at the head of a list keeps its spelling, so `filter` and `map`
stay distinct while the locals passed to them do not.

Reader conditionals keep the `:clj` branch, which is what dry4clj selects.
Syntax-quote is kept as a `syntax-quote` list instead of being expanded into
`seq` and `concat` forms.
"""

from __future__ import annotations

import re

from dryer.shape import K

_WHITESPACE = set(" \t\n\r,")
_TERMINATORS = set("()[]{}\";'@^`~\\,#:")
_NUMBER = re.compile(
    r"^[+-]?(?:"
    r"\d+/\d+"
    r"|\d+\.\d+(?:[eE][+-]?\d+)?"
    r"|\.\d+(?:[eE][+-]?\d+)?"
    r"|\d+(?:[eE][+-]?\d+)?"
    r"|0[xX][0-9A-Fa-f]+"
    r")[MN]?$"
)


class ReadError(Exception):
    def __init__(self, line: int, message: str):
        super().__init__(message)
        self.line = line


class Sym:
    def __init__(self, name: str, line: int):
        self.name = name
        self.line = line


class Kw:
    def __init__(self, name: str, line: int):
        self.name = name
        self.line = line


class Lit:
    def __init__(self, line: int):
        self.line = line


class Coll:
    def __init__(self, kind: str, line: int, items=None, pairs=None):
        self.kind = kind
        self.line = line
        self.items = [] if items is None else items
        self.pairs = [] if pairs is None else pairs


class Splice:
    def __init__(self, items: list):
        self.items = items


class Reader:
    def __init__(self, text: str):
        self.text = text
        self.n = len(text)
        self.i = 0
        self.line = 1

    def peek(self) -> str | None:
        if self.i >= self.n:
            return None
        return self.text[self.i]

    def eof(self) -> bool:
        return self.i >= self.n

    def get(self) -> str:
        ch = self.text[self.i]
        self.i += 1
        if ch == "\n":
            self.line += 1
        return ch

    def skip_ws(self) -> None:
        while not self.eof():
            ch = self.peek()
            if ch in _WHITESPACE:
                self.get()
                continue
            if ch == ";":
                while not self.eof() and self.peek() != "\n":
                    self.get()
                continue
            break

    def read_token(self) -> str:
        start = self.i
        line = self.line
        while not self.eof():
            ch = self.peek()
            if ch in _WHITESPACE or ch in _TERMINATORS:
                break
            self.get()
        if self.i == start:
            raise ReadError(line, "expected a symbol")
        return self.text[start:self.i]

    def read_string(self) -> Lit:
        line = self.line
        self.get()
        while not self.eof():
            ch = self.get()
            if ch == "\\":
                if self.eof():
                    break
                self.get()
                continue
            if ch == '"':
                return Lit(line)
        raise ReadError(line, "unterminated string")

    def read_char(self) -> Lit:
        line = self.line
        self.get()
        if self.eof():
            raise ReadError(line, "incomplete character")
        self.get()
        while not self.eof():
            ch = self.peek()
            if ch in _WHITESPACE or ch in _TERMINATORS:
                break
            self.get()
        return Lit(line)

    def read_keyword(self) -> Kw:
        line = self.line
        self.get()
        if self.peek() == ":":
            self.get()
        if self.eof() or self.peek() in _WHITESPACE or self.peek() in _TERMINATORS:
            return Kw("", line)
        return Kw(self.read_token(), line)

    def read_collection(self, end: str, kind: str) -> Coll:
        line = self.line
        self.get()
        items: list = []
        while True:
            self.skip_ws()
            if self.eof():
                raise ReadError(line, f"unterminated {kind}")
            if self.peek() == end:
                self.get()
                break
            form = self.read_form()
            if form is None:
                continue
            if isinstance(form, Splice):
                items.extend(form.items)
                continue
            items.append(form)
        if kind == "map":
            if len(items) % 2:
                raise ReadError(line, "map literal has an odd number of forms")
            pairs = [(items[i], items[i + 1]) for i in range(0, len(items), 2)]
            return Coll("map", line, pairs=pairs)
        return Coll(kind, line, items=items)

    def _wrap(self, name: str, line: int) -> Coll:
        inner = self.read_form()
        items = [Sym(name, line)]
        if inner is not None and not isinstance(inner, Splice):
            items.append(inner)
        return Coll("list", line, items=items)

    def read_dispatch(self):
        line = self.line
        self.get()
        ch = self.peek()
        if ch is None:
            raise ReadError(line, "incomplete dispatch")
        if ch == "_":
            self.get()
            self.read_form()
            return None
        if ch == "{":
            return self.read_collection("}", "set")
        if ch == "(":
            inner = self.read_collection(")", "list")
            return Coll("list", line, items=[Sym("fn*", line), *inner.items])
        if ch == '"':
            self.read_string()
            return Lit(line)
        if ch == "?":
            self.get()
            splicing = False
            if self.peek() == "@":
                self.get()
                splicing = True
            return self.read_cond(splicing)
        if ch == ":":
            self.get()
            if self.peek() == ":":
                self.get()
            elif self.peek() not in (None, "{") and self.peek() not in _WHITESPACE:
                self.read_token()
            return self.read_form()
        self.read_token()
        self.read_form()
        return Lit(line)

    def read_cond(self, splicing: bool):
        form = self.read_form()
        if not isinstance(form, Coll) or form.kind != "list":
            raise ReadError(self.line, "reader conditional body must be a list")
        chosen = _chosen_branch(form.items)
        if chosen is None:
            return None
        if not splicing:
            return chosen
        spliced = _spliced(chosen)
        if spliced is None:
            raise ReadError(self.line, "splicing reader conditional needs a collection")
        return spliced

    def read_form(self):
        self.skip_ws()
        if self.eof():
            raise ReadError(self.line, "unexpected end of file")
        ch = self.peek()
        line = self.line
        if ch == "(":
            return self.read_collection(")", "list")
        if ch == "[":
            return self.read_collection("]", "vector")
        if ch == "{":
            return self.read_collection("}", "map")
        if ch == '"':
            return self.read_string()
        if ch == "\\":
            return self.read_char()
        if ch == ":":
            return self.read_keyword()
        if ch == "'":
            self.get()
            return self._wrap("quote", line)
        if ch == "@":
            self.get()
            return self._wrap("deref", line)
        if ch == "`":
            self.get()
            return self._wrap("syntax-quote", line)
        if ch == "~":
            self.get()
            name = "unquote"
            if self.peek() == "@":
                self.get()
                name = "unquote-splicing"
            return self._wrap(name, line)
        if ch == "^":
            self.get()
            self.read_form()
            return self.read_form()
        if ch == "#":
            return self.read_dispatch()
        token = self.read_token()
        if _NUMBER.match(token):
            return Lit(line)
        return Sym(token, line)


def _branch_name(feature):
    if isinstance(feature, Kw):
        return feature.name
    return None


def _chosen_branch(items):
    index = 0
    while index + 1 < len(items):
        expr = items[index + 1]
        if _branch_name(items[index]) in {"clj", "default"}:
            return expr
        index += 2
    return None


def _spliced(chosen):
    if isinstance(chosen, Coll) and chosen.kind in {"list", "vector"}:
        return Splice(list(chosen.items))
    return None


def _strip_bom(text: str) -> str:
    if text.startswith("\ufeff"):
        return text[1:]
    return text


def _skip_shebang(reader: Reader, text: str) -> None:
    if not text.startswith("#!"):
        return
    while reader.peek() not in (None, "\n"):
        reader.get()


def read_source(text: str) -> tuple[list, str | None]:
    """Top-level forms, plus a warning if a later form could not be read."""

    text = _strip_bom(text)
    reader = Reader(text)
    _skip_shebang(reader, text)
    forms: list = []
    while True:
        reader.skip_ws()
        if reader.eof():
            return forms, None
        try:
            form = reader.read_form()
        except ReadError as exc:
            return forms, f"{exc.line}: {exc}"
        if form is None or isinstance(form, Splice):
            continue
        forms.append(form)


def _children(form):
    if isinstance(form, Coll):
        if form.kind == "map":
            for key, value in form.pairs:
                yield key
                yield value
        else:
            yield from form.items


def max_line(form) -> int:
    best = getattr(form, "line", 1) or 1
    for child in _children(form):
        if child is not None:
            best = max(best, max_line(child))
    return best


def _normalize_list(form):
    if not form.items:
        return [K("list"), K("literal")]
    head_form, *args = form.items
    return [K("list"), normalize(head_form, True), *[normalize(arg, False) for arg in args]]


def normalize(form, head: bool = False):
    """dry4clj's `normalize-form`. Collection heads are normalized in full."""

    if isinstance(form, Coll):
        if form.kind == "list":
            return _normalize_list(form)
        if form.kind == "vector":
            return [K("vector"), *[normalize(item, False) for item in form.items]]
        if form.kind == "set":
            return [K("set"), *[normalize(item, False) for item in form.items]]
        if form.kind == "map":
            pairs = [[normalize(key, False), normalize(value, False)] for key, value in form.pairs]
            return [K("map"), *pairs]
        return [K("literal")]
    if isinstance(form, Sym):
        if head:
            return [K("symbol"), form.name]
        return K("symbol")
    if isinstance(form, Kw):
        return K("keyword")
    return K("literal")


def is_candidate_form(form) -> bool:
    """A non-empty top-level list whose head is not `ns`."""

    if not isinstance(form, Coll) or form.kind != "list" or not form.items:
        return False
    head = form.items[0]
    return not (isinstance(head, Sym) and head.name == "ns")
