from decimal import Decimal

import pandas as pd

from comparison.data_comparator import compare_frames, compare_numbers
from comparison.data_normalizer import DataNormalizer
from core.contracts import MismatchType, ToleranceConfig

EXACT = ToleranceConfig()
D = Decimal


def test_percentage_difference_formula():
    vc = compare_numbers(D("200"), D("250"), EXACT)
    assert vc.absolute == D("50") and vc.percentage == D("25.000000") and not vc.match


def test_negative_numbers_literal_formula():
    vc = compare_numbers(D("-100"), D("-110"), EXACT)
    assert vc.absolute == D("-10") and vc.percentage == D("10.000000")


def test_zero_original():
    assert compare_numbers(D(0), D(0), EXACT).match
    vc = compare_numbers(D(0), D(5), EXACT)
    assert not vc.match and vc.percentage is None and "zero" in vc.note


def test_null_handling():
    assert compare_numbers(None, None, EXACT).match
    vc = compare_numbers(None, D(1), EXACT)
    assert not vc.match and vc.mismatch_type == MismatchType.NULL_MISMATCH and vc.percentage is None


def test_tolerances():
    assert compare_numbers(D("100"), D("100.4"), ToleranceConfig(absolute=D("0.5"))).match
    assert not compare_numbers(D("100"), D("100.6"), ToleranceConfig(absolute=D("0.5"))).match
    assert compare_numbers(D("1000"), D("1009"), ToleranceConfig(percentage=D("1"))).match
    assert not compare_numbers(D("1000"), D("1011"), ToleranceConfig(percentage=D("1"))).match
    # pct tolerance can't excuse undefined % (original zero)
    assert not compare_numbers(D("0"), D("1"), ToleranceConfig(percentage=D("50"))).match


def test_large_numbers_exact():
    assert not compare_numbers(D("123456789012345678.01"), D("123456789012345678.02"), EXACT).match


def _nf(rows, numeric):
    return DataNormalizer().normalize(pd.DataFrame(rows), numeric)


def test_missing_additional_matching_unordered():
    o = _nf({"Cat": ["A", "B", "C"], "V": ["1", "2", "3"]}, ["V"])
    m = _nf({"Cat": ["D", "B", "A"], "V": ["4", "2", "1"]}, ["V"])  # different order
    r = compare_frames(o, m, ["Cat"], ["V"], EXACT)
    assert r.rows_matched == 2 and r.rows_compared == 2
    assert r.count(MismatchType.MISSING_RECORD) == 1 and r.count(MismatchType.ADDITIONAL_RECORD) == 1
    assert r.missing_categories == {"Cat": ["C"]} and r.additional_categories == {"Cat": ["D"]}


def test_unconfirmed_when_incomplete():
    o = _nf({"Cat": ["A", "B"], "V": ["1", "2"]}, ["V"])
    m = _nf({"Cat": ["A"], "V": ["1"]}, ["V"])
    r = compare_frames(o, m, ["Cat"], ["V"], EXACT, rows_confirmable=False)
    miss = [x for x in r.mismatches if x.mismatch_type == MismatchType.MISSING_RECORD]
    assert miss and not miss[0].confirmed


def test_duplicates_detected_and_excluded():
    o = _nf({"Cat": ["A", "A", "B"], "V": ["1", "1", "2"]}, ["V"])
    m = _nf({"Cat": ["A", "B"], "V": ["1", "2"]}, ["V"])
    r = compare_frames(o, m, ["Cat"], ["V"], EXACT)
    assert r.count(MismatchType.DUPLICATE_KEY) == 1
    assert r.rows_compared == 1  # only B


def test_card_single_row():
    o = _nf({"Total": ["1,000"]}, ["Total"])
    m = _nf({"Total": ["1,001"]}, ["Total"])
    r = compare_frames(o, m, [], ["Total"], EXACT)
    assert r.count(MismatchType.VALUE_MISMATCH) == 1 and r.mismatches[0].absolute_difference == D(1)


def test_keys_not_established_for_multirow_keyless():
    o = _nf({"V": ["1", "2"]}, ["V"])
    r = compare_frames(o, o, [], ["V"], EXACT)
    assert not r.keys_established


def test_derived_totals():
    o = _nf({"Cat": ["A", "B"], "V": ["1", "2"]}, ["V"])
    m = _nf({"Cat": ["A", "B"], "V": ["1", "5"]}, ["V"])
    r = compare_frames(o, m, ["Cat"], ["V"], EXACT)
    t = r.derived_totals[0]
    assert t["original_total"] == "3" and t["migrated_total"] == "6" and not t["within_tolerance"]


def test_text_value_columns_and_nulls():
    o = _nf({"K": ["a", "b"], "Label": ["x", ""]}, [])
    m = _nf({"K": ["a", "b"], "Label": ["y", ""]}, [])
    r = compare_frames(o, m, ["K"], ["Label"], EXACT)
    assert r.count(MismatchType.VALUE_MISMATCH) == 1 and r.rows_matched == 1
