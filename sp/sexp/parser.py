"""Python port of the sexpistol S-expression parser.

Faithful to sexpistol's Ruby semantics (MIT, Aaron Gough,
https://github.com/aarongough/sexpistol): lists, integers, floats
including exponents (``2.0e10``), double-quoted strings with escapes,
and symbols — mapped to native Python data structures:

- ``(a b c)``      -> ``[Symbol('a'), Symbol('b'), Symbol('c')]``
- ``1 2 3``        -> ``1 2 3`` (int)
- ``1.0 2.0e10``   -> ``1.0 20000000000.0`` (float)
- ``"hi\\n"``      -> ``'hi\\n'`` (str)
- ``(+ 10 12)``    -> ``[Symbol('+'), 10, 12]``

Pythonic twists over the Ruby original:

- :class:`Symbol` is a ``str`` subclass: symbols behave like plain text
  in command handlers but remain distinguishable for round-trips.
- ``python_literals=True`` maps ``nil``/``false``/``true`` to
  ``None``/``False``/``True`` (sexpistol: ``parse_ruby_keyword_literals``).
- Parsing stops at the first complete top-level expression and reports
  trailing junk as an error, so one REPL input equals one command form.

sexpistol reference: https://github.com/aarongough/sexpistol
"""

from __future__ import annotations

import re
from typing import Any

from sp.shared.errors import ParseError

__all__ = ["Symbol", "parse", "to_sexp"]

_ESCAPES = {
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
    "0": "\0",
    "\\": "\\",
    '"': '"',
    "'": "'",
    "/": "/",
}

_INT_RE = re.compile(r"[+-]?\d+\Z")
_EXP_RE = re.compile(r"[eE][+-]?\d+\Z")
_PY_KEYWORDS = {"nil": None, "false": False, "true": True}


class Symbol(str):
    """An s-expression symbol such as ``trim``, ``+`` or ``a?``.

    Subclasses ``str`` so commands can treat symbols and strings
    uniformly, while ``isinstance(x, Symbol)`` still distinguishes them.
    """


def parse(source: str, *, python_literals: bool = False) -> Any:
    """Parse *source* containing exactly one S-expression.

    Args:
        source: S-expression text, e.g. ``'(trim 0 10)'``.
        python_literals: map ``nil``/``false``/``true`` to Python
            ``None``/``False``/``True`` instead of leaving them symbols.

    Returns:
        Nested lists of :class:`Symbol`, ``int``, ``float``, ``str`.

    Raises:
        ParseError: on malformed input; ``.incomplete`` is ``True`` when
            the input simply ended too early (open list / open string).
    """
    parser = _Parser(source, python_literals)
    parser.skip_ws()
    if parser.eof():
        raise ParseError("empty input", pos=parser.pos, incomplete=False)
    value = parser.parse_expr()
    parser.skip_ws()
    if not parser.eof():
        raise ParseError("extra input after top-level expression", pos=parser.pos)
    return value


def to_sexp(structure: Any, *, scheme_compatible: bool = False) -> str:
    """Render *structure* back into S-expression text.

    Inverse of :func:`parse`.  With ``scheme_compatible=True`` booleans
    and ``None`` render as ``#t``/``#f``/``()`` (sexpistol's Scheme mode).
    """
    if isinstance(structure, (list, tuple)):
        inner = " ".join(to_sexp(item, scheme_compatible=scheme_compatible) for item in structure)
        return f"({inner})"
    if isinstance(structure, Symbol):
        return str(structure)
    if isinstance(structure, bool):
        if scheme_compatible:
            return "#t" if structure else "#f"
        return "true" if structure else "false"
    if structure is None:
        return "()" if scheme_compatible else "nil"
    if isinstance(structure, int):
        return str(structure)
    if isinstance(structure, float):
        return repr(structure)
    if isinstance(structure, str):
        return '"' + _escape(structure) + '"'
    raise TypeError(f"cannot render {type(structure).__name__} as an s-expression")


def _escape(text: str) -> str:
    out = []
    for ch in text:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\r":
            out.append("\\r")
        else:
            out.append(ch)
    return "".join(out)


class _Parser:
    """Single-pass recursive-descent scanner over the source text."""

    def __init__(self, source: str, python_literals: bool) -> None:
        self.src = source
        self.pos = 0
        self.python_literals = python_literals

    # -- character helpers -------------------------------------------------
    def eof(self) -> bool:
        return self.pos >= len(self.src)

    def peek(self) -> str:
        return self.src[self.pos]

    def skip_ws(self) -> None:
        while not self.eof() and self.peek().isspace():
            self.pos += 1

    # -- expressions -------------------------------------------------------
    def parse_expr(self) -> Any:
        if self.eof():
            raise ParseError("unexpected end of input", pos=self.pos, incomplete=True)
        ch = self.peek()
        if ch == "(":
            return self.parse_list()
        if ch == ")":
            raise ParseError("unexpected ')'", pos=self.pos)
        if ch == '"':
            return self.parse_string()
        return self.parse_atom()

    def parse_list(self) -> list[Any]:
        start = self.pos
        self.pos += 1  # consume '('
        items: list[Any] = []
        while True:
            self.skip_ws()
            if self.eof():
                raise ParseError("unexpected end of input inside list", pos=start, incomplete=True)
            if self.peek() == ")":
                self.pos += 1
                return items
            items.append(self.parse_expr())

    def parse_string(self) -> str:
        start = self.pos
        self.pos += 1  # consume opening quote
        out: list[str] = []
        while True:
            if self.eof():
                raise ParseError("unterminated string", pos=start, incomplete=True)
            ch = self.peek()
            self.pos += 1
            if ch == '"':
                return "".join(out)
            if ch != "\\":
                out.append(ch)
                continue
            if self.eof():
                raise ParseError("unterminated escape", pos=self.pos, incomplete=True)
            esc = self.peek()
            self.pos += 1
            if esc == "u":
                hex_digits = self.src[self.pos : self.pos + 4]
                if len(hex_digits) < 4:
                    raise ParseError("truncated \\u escape", pos=self.pos, incomplete=True)
                try:
                    out.append(chr(int(hex_digits, 16)))
                except ValueError as exc:
                    raise ParseError(f"invalid \\u escape: {hex_digits}", pos=self.pos) from exc
                self.pos += 4
            elif esc == "x":
                hex_digits = self.src[self.pos : self.pos + 2]
                if len(hex_digits) < 2:
                    raise ParseError("truncated \\x escape", pos=self.pos, incomplete=True)
                try:
                    out.append(chr(int(hex_digits, 16)))
                except ValueError as exc:
                    raise ParseError(f"invalid \\x escape: {hex_digits}", pos=self.pos) from exc
                self.pos += 2
            elif esc in _ESCAPES:
                out.append(_ESCAPES[esc])
            else:
                out.append(esc)  # unknown escapes keep the character, like Ruby

    def parse_atom(self) -> Any:
        start = self.pos
        while not self.eof():
            ch = self.peek()
            if ch.isspace() or ch in '()"':
                break
            self.pos += 1
        token = self.src[start : self.pos]
        if not token:
            raise ParseError("expected a value", pos=start)
        return self._atom(token, start)

    def _atom(self, token: str, pos: int) -> Any:
        if _INT_RE.match(token):
            return int(token)
        if "." in token or _EXP_RE.search(token):
            try:
                return float(token)
            except ValueError:
                pass
        if self.python_literals and token in _PY_KEYWORDS:
            return _PY_KEYWORDS[token]
        return Symbol(token)
