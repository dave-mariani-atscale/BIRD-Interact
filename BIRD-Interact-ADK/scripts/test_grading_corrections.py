"""Unit tests for the 2026-09-08 grading corrections: ties_as_ties and
numeric_rel_tolerance. Run: PYTHONPATH=. .venv-adk/bin/python scripts/test_grading_corrections.py"""
import sys
from decimal import Decimal
sys.path.insert(0, ".")
from shared import db_utils as U

ORD = {"order": True}
UNORD = {"order": False}


def cmp(pred, gold, cond, key=None, cell=U.canonical_cell):
    return U._compare_rows(U.preprocess_results(pred), U.preprocess_results(gold), cond,
                           cell=cell, raw=(pred, gold, key))


def test_key_parsing():
    assert U.gold_sort_key_indices("SELECT a, SUM(x) AS s FROM t GROUP BY a ORDER BY s DESC", ["a", "s"]) == [1]
    assert U.gold_sort_key_indices("SELECT a, SUM(x) AS s FROM t GROUP BY a ORDER BY SUM(x) DESC", ["a", "s"]) == [1]
    assert U.gold_sort_key_indices("SELECT t.a, t.b FROM t ORDER BY t.b, 1", ["a", "b"]) == [1, 0]
    assert U.gold_sort_key_indices("WITH c AS (SELECT 1 AS a) SELECT a FROM c ORDER BY a", ["a"]) == [0]
    # ORDER BY something not projected -> None -> forgive nothing
    assert U.gold_sort_key_indices("SELECT a FROM t ORDER BY b", ["a"]) is None
    assert U.gold_sort_key_indices("SELECT a FROM t", ["a"]) is None


def test_ties_as_ties():
    gold = [("x", 5), ("y", 3), ("z", 3), ("w", 1)]
    swapped = [("x", 5), ("z", 3), ("y", 3), ("w", 1)]      # permutation inside the tie
    wrong = [("x", 5), ("w", 1), ("y", 3), ("z", 3)]         # breaks gold's order on the key
    assert cmp(swapped, gold, ORD) == 0                      # no key -> strict, as before
    assert cmp(swapped, gold, ORD, key=[1]) == 1
    assert cmp(wrong, gold, ORD, key=[1]) == 0
    # ties are read at full precision: 3.001 vs 3.004 round alike but are NOT a tie
    gold2 = [("y", 3.004), ("z", 3.001)]
    assert cmp([("z", 3.001), ("y", 3.004)], gold2, ORD, key=[1]) == 0
    # typed raw path (cell=None) behaves the same
    assert cmp(swapped, gold, ORD, key=[1], cell=None) == 1


def test_numeric_rel_tolerance():
    gold = [("a", Decimal("12.065"))]           # numeric, rounds half-up to 12.07
    pred = [("a", 12.064999999)]                # float8, rounds to 12.06
    assert cmp(pred, gold, UNORD) == 1
    assert cmp([("a", 12.06)], gold, UNORD) == 0  # 4e-4 relative: not forgiven
    assert cmp([("a", 12.064999)], gold, ORD) == 1
    # a non-numeric never matches a numeric; text still needs equality
    assert cmp([("b", 12.065)], gold, UNORD) == 0
    # multiset under tolerance, unordered
    g = [("a", Decimal("1.005")), ("b", Decimal("2.005"))]
    assert cmp([("b", 2.00499999), ("a", 1.00499999)], g, UNORD) == 1
    # -0 renders as 0 now via tolerance path too
    assert cmp([("a", -0.0)], [("a", Decimal("0.00"))], UNORD) == 1


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
    print("all grading correction tests passed")
