from decimal import Decimal

import pandas as pd
import pytest

from comparison.data_normalizer import DataNormalizer, NotANumber, coarsest
from core.contracts import NormalizationRules


@pytest.fixture
def n():
    return DataNormalizer()


@pytest.mark.parametrize("raw,expected", [
    ("1,234.50", Decimal("1234.50")),
    ("$1,234.50", Decimal("1234.50")),
    ("(1,234.50)", Decimal("-1234.50")),
    ("-12", Decimal("-12")),
    ("12.5%", Decimal("12.5")),
    ("¥ 9,999,999,999.99", Decimal("9999999999.99")),
    ("1.5E+3", Decimal("1500")),
    ("  42  ", Decimal("42")),
    ("CNY 100", Decimal("100")),
    ("0.1", Decimal("0.1")),
])
def test_parse_number(n, raw, expected):
    assert n.parse_number(raw) == expected


def test_nulls_and_blanks(n):
    for v in ["", "  ", "(Blank)", "null", "NaN", None]:
        assert n.parse_number(v) is None


def test_invalid_number(n):
    with pytest.raises(NotANumber):
        n.parse_number("abc")
    with pytest.raises(NotANumber):
        n.parse_number("1.2.3")


def test_percent_fraction_and_locale():
    n = DataNormalizer(NormalizationRules(percent_mode="as_fraction"))
    assert n.parse_number("12.5%") == Decimal("0.125")
    eu = DataNormalizer(NormalizationRules(decimal_separator=",", thousands_separator="."))
    assert eu.parse_number("1.234,56") == Decimal("1234.56")


def test_float_precision_exact(n):
    # 0.1 + 0.2 issue does not arise with Decimal
    assert n.parse_number("0.1") + n.parse_number("0.2") == n.parse_number("0.3")


def test_rounding_half_up():
    n = DataNormalizer(NormalizationRules(decimal_places=2))
    assert n.round_number(Decimal("2.345")) == Decimal("2.35")
    assert n.round_number(Decimal("-2.345")) == Decimal("-2.35")


@pytest.mark.parametrize("raw,gran,expected", [
    ("January 2024", "monthly", "2024-01"),
    ("Jan 2024", "monthly", "2024-01"),
    ("2024-01-15", "daily", "2024-01-15"),
    ("2024-01-15", "monthly", "2024-01"),
    ("2024-02-15", "quarterly", "2024-Q1"),
    ("2024 Q3", "quarterly", "2024-Q3"),
    ("Q3 2024", "quarterly", "2024-Q3"),
    ("Qtr 3 2024", "quarterly", "2024-Q3"),
    ("2024", "yearly", "2024"),
    ("12/31/2024", "daily", "2024-12-31"),
    ("2024-01-15T00:00:00", "yearly", "2024"),
])
def test_dates(n, raw, gran, expected):
    assert n.parse_date(raw).render(gran) == expected


def test_dayfirst():
    n = DataNormalizer(NormalizationRules(date_dayfirst=True))
    assert n.parse_date("05/01/2024").render("daily") == "2024-01-05"


def test_infer_granularity_and_coarsest(n):
    assert n.infer_date_granularity(pd.Series(["January 2024", "February 2024"])) == "monthly"
    assert n.infer_date_granularity(pd.Series(["2024-01-01", "2024-02-01"])) == "daily"
    assert n.infer_date_granularity(pd.Series(["2024-01-01", "x"])) is None
    assert coarsest("daily", "monthly") == "monthly"


def test_infer_numeric_excludes_date_names(n):
    df = pd.DataFrame({"Year": ["2023", "2024"], "Category": ["A", "B"], "Sales": ["1,000", "(5)"]})
    assert n.infer_numeric_columns(df) == ["Sales"]


def test_normalize_keeps_original_unchanged(n):
    df = pd.DataFrame({"Cat": [" A ", "B"], "Sales": ["1,000.00", ""]})
    snapshot = df.copy(deep=True)
    nf = n.normalize(df, ["Sales"])
    pd.testing.assert_frame_equal(df, snapshot)
    assert nf.df["Cat"].tolist() == ["A", "B"]
    assert nf.df["Sales"].tolist() == [Decimal("1000.00"), None]
    assert any("numeric parse 'Sales'" in a for a in nf.applied)


def test_null_as_zero_and_invalid_tracking():
    n = DataNormalizer(NormalizationRules(treat_null_as_zero=True))
    nf = n.normalize(pd.DataFrame({"v": ["", "x", "3"]}), ["v"])
    assert nf.df["v"].tolist()[0] == Decimal(0)
    assert nf.invalid_numbers == {"v": 1}


def test_text_case_rule():
    n = DataNormalizer(NormalizationRules(text_case="lower"))
    nf = n.normalize(pd.DataFrame({"c": ["China "]}), [])
    assert nf.df["c"].tolist() == ["china"]
