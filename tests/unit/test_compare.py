"""The eval's scoring rules: right answers in a different shape pass, wrong ones don't."""

import pytest

from transitquery.eval.compare import is_ordered, normalize, results_match


def test_normalize_rounds_and_unifies_numbers():
    assert normalize(2024.0) == 2024
    assert normalize(3.14159) == 3.1
    assert normalize(" KENNEDY ") == "KENNEDY"
    assert normalize(None) is None


def test_is_ordered_looks_only_at_the_outer_query():
    assert is_ordered("SELECT a FROM t ORDER BY a")
    assert not is_ordered("SELECT a FROM t")
    assert not is_ordered("SELECT COUNT(*) FROM (SELECT a FROM t ORDER BY a) x")


@pytest.mark.parametrize("gold, pred, ordered, expected", [
    # extra predicted columns are fine; names don't matter
    ([["BLOOR-YONGE"]], [["BLOOR-YONGE", 540]], True, True),
    ([["BLOOR-YONGE"]], [[540, "BLOOR-YONGE"]], True, True),
    # a longer ranking passes if it starts with the gold rows
    ([["A"], ["B"]], [["A"], ["B"], ["C"]], True, True),
    ([["A"], ["B"]], [["B"], ["A"], ["C"]], True, False),
    # unordered: any row order, but the rows must still line up
    ([[1, "x"], [2, "y"]], [[2, "y"], [1, "x"]], False, True),
    ([[1, "x"], [2, "y"]], [[1, "y"], [2, "x"]], False, False),
    # a different unordered result is never accepted, even with more rows
    ([[1]], [[1], [2]], False, False),
    # numbers: rounding and int/float
    ([[12.34]], [[12.3]], False, True),
    ([[2024.0]], [[2024]], True, True),
    ([[12.34]], [[12.9]], False, False),
    # a one-column answer returned side by side in one row
    ([[17.8], [18.2]], [[18.2, 17.8]], False, True),
    ([[17.8], [18.2]], [[18.2, 99.0]], False, False),
    ([[17.8], [18.2]], [[18.2, 17.8, 5]], False, False),     # an extra value isn't the answer
    # wrong answer
    ([["KENNEDY"]], [["BLOOR-YONGE"]], True, False),
    ([], [], False, True),
])
def test_results_match(gold, pred, ordered, expected):
    assert results_match(gold, pred, ordered)[0] is expected
