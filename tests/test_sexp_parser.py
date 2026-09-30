"""Port of sexpistol's own examples — the parser contract.

Source of truth: https://github.com/aarongough/sexpistol (README).
"""

from __future__ import annotations

import pytest

from sp.sexp import Symbol, parse, to_sexp
from sp.shared.errors import ParseError

# --- type mapping (sexpistol "Type mappings") ----------------------------


def test_lists_become_nested_lists():
    assert parse("(string (to (parse)))") == ["string", ["to", ["parse"]]]


def test_readme_define_lambda_example_verbatim():
    src = r"""
    (define test (lambda () (
      (print "Hello world!\n")
      (print 1)
      (print 9.01)
      (print 2.0e10)
      (print (+ 10 12 13))
    )))
    """
    assert parse(src) == [
        "define",
        "test",
        [
            "lambda",
            [],
            [
                ["print", "Hello world!\n"],
                ["print", 1],
                ["print", 9.01],
                ["print", 2.0e10],
                ["print", ["+", 10, 12, 13]],
            ],
        ],
    ]


def test_integers_stay_ints():
    values = parse("(1 2 3)")
    assert values == [1, 2, 3]
    assert all(isinstance(v, int) for v in values)


def test_floats_including_exponents():
    assert parse("(1.0 42.9 3e6 1.2e2)") == [1.0, 42.9, 3e6, 1.2e2]


def test_symbols_keep_their_names():
    symbols = parse("(symbol symbol? + - a+ e$)")
    assert [str(s) for s in symbols] == ["symbol", "symbol?", "+", "-", "a+", "e$"]
    assert all(isinstance(s, Symbol) for s in symbols)


def test_symbols_and_numbers_are_distinguished():
    # parse() of an atom returns the atom itself, not a list
    assert isinstance(parse("+"), Symbol)
    assert isinstance(parse("-5"), int)
    quoted = parse('"-5"')
    assert isinstance(quoted, str) and not isinstance(quoted, Symbol)


def test_strings_unescape():
    assert parse(r'("a\tb")') == ["a\tb"]
    assert parse(r'("say \"hi\"")') == ['say "hi"']
    assert parse(r'("line\nbreak")') == ["line\nbreak"]
    assert parse(r'("A")') == ["A"]


def test_unicode_escape_via_backslash_u():
    backslash = chr(92)  # build '\' explicitly so the test source stays literal
    assert parse(f'("{backslash}u0041{backslash}u00e9")') == ["Aé"]
    assert parse(f'("{backslash}x41")') == ["A"]


def test_empty_list():
    assert parse("()") == []


# --- python-literal option (sexpistol: parse_ruby_keyword_literals) -----


def test_keyword_literals_stay_symbols_by_default():
    assert parse("(nil false true)") == ["nil", "false", "true"]


def test_python_literals_map_when_enabled():
    assert parse("(nil false true)", python_literals=True) == [None, False, True]


# --- serialization (sexpistol: to_sexp / scheme_compatability) ----------


def test_to_sexp_round_trip():
    src = "(define test (lambda () ((print 1) (print 9.01) (print (+ 10 12)))))"
    ast = parse(src)
    assert parse(to_sexp(ast)) == ast


def test_to_sexp_distinguishes_symbols_from_strings():
    assert to_sexp(["a", Symbol("b")]) == '("a" b)'


def test_to_sexp_python_values():
    assert to_sexp([True, False, None]) == "(true false nil)"


def test_to_sexp_scheme_compatible():
    assert to_sexp([True, False, None], scheme_compatible=True) == "(#t #f ())"


def test_to_sexp_rejects_unknown_types():
    with pytest.raises(TypeError):
        to_sexp(object())


# --- errors --------------------------------------------------------------


def test_incomplete_list_is_flagged_for_multiline():
    with pytest.raises(ParseError) as exc:
        parse('(open "a.mp4"')
    assert exc.value.incomplete


def test_incomplete_string_is_flagged():
    with pytest.raises(ParseError) as exc:
        parse('"abc')
    assert exc.value.incomplete


def test_unbalanced_close_paren_is_an_error_not_incomplete():
    with pytest.raises(ParseError) as exc:
        parse("(a))")
    assert not exc.value.incomplete


def test_extra_input_rejected():
    with pytest.raises(ParseError):
        parse("(a) (b)")


def test_empty_input_rejected():
    with pytest.raises(ParseError):
        parse("   ")


def test_error_message_carries_position():
    with pytest.raises(ParseError) as exc:
        parse("(a))")
    assert "char" in str(exc.value)
