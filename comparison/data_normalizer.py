"""Configurable, auditable normalization of *derived* copies of extracted data.

Originals are never modified: ``normalize`` always works on ``df.copy()``.
Every transformation applied is recorded in ``NormalizedFrame.applied``.
Numbers are parsed into ``decimal.Decimal`` (exact) to avoid float artefacts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

import pandas as pd

from core.contracts import NormalizationRules

_CURRENCY = re.compile(r"[\$€£¥₹¢₩₽฿₫₪₴₦]|\b(?:USD|EUR|GBP|CNY|RMB|JPY|INR)\b", re.IGNORECASE)
_DATEISH_NAME = re.compile(r"date|month|period|quarter|year|week|day|fiscal|time", re.IGNORECASE)
_QUARTER_A = re.compile(r"^\s*(\d{4})\s*[-/ ]?\s*Q([1-4])\s*$", re.IGNORECASE)
_QUARTER_B = re.compile(r"^\s*Q([1-4])\s*[-/ ]?\s*(\d{4})\s*$", re.IGNORECASE)
_QUARTER_C = re.compile(r"^\s*(?:Qtr|Quarter)\s*([1-4])\s*[-/ ]?\s*(\d{4})\s*$", re.IGNORECASE)
_YEAR = re.compile(r"^\s*(\d{4})\s*$")
_GRAN_ORDER = {"daily": 0, "monthly": 1, "quarterly": 2, "yearly": 3}

_MONTH_FORMATS = ["%B %Y", "%b %Y", "%Y-%m", "%Y/%m", "%m/%Y", "%Y %B", "%Y %b", "%b-%Y", "%B-%Y", "%b-%y"]
_DAY_FORMATS_MF = ["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d", "%m/%d/%Y", "%m/%d/%Y %I:%M:%S %p",
                   "%m/%d/%Y %H:%M:%S", "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y"]
_DAY_FORMATS_DF = ["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d", "%d/%m/%Y", "%d/%m/%Y %H:%M:%S",
                   "%d.%m.%Y", "%d %B %Y", "%d %b %Y"]


class NotANumber(ValueError):
    pass


@dataclass
class ParsedDate:
    year: int
    month: int | None = None
    day: int | None = None
    quarter: int | None = None
    granularity: str = "daily"  # finest granularity present in the source text

    def render(self, gran: str) -> str:
        if gran == "yearly":
            return f"{self.year:04d}"
        if gran == "quarterly":
            q = self.quarter or ((self.month - 1) // 3 + 1 if self.month else None)
            return f"{self.year:04d}-Q{q}" if q else f"{self.year:04d}"
        if gran == "monthly":
            return f"{self.year:04d}-{self.month:02d}" if self.month else self.render("quarterly")
        if self.day and self.month:
            return f"{self.year:04d}-{self.month:02d}-{self.day:02d}"
        return self.render("monthly")


@dataclass
class NormalizedFrame:
    df: pd.DataFrame
    applied: list[str] = field(default_factory=list)
    numeric_columns: list[str] = field(default_factory=list)
    date_columns: dict[str, str] = field(default_factory=dict)
    invalid_numbers: dict[str, int] = field(default_factory=dict)
    unparsed_dates: dict[str, int] = field(default_factory=dict)


class DataNormalizer:
    def __init__(self, rules: NormalizationRules | None = None) -> None:
        self.rules = rules or NormalizationRules()
        self._null_tokens = {t.strip().lower() for t in self.rules.null_tokens}

    # ------------------------------------------------------------------ scalars
    def is_null(self, v: Any) -> bool:
        if v is None:
            return True
        if isinstance(v, float) and v != v:
            return True
        return str(v).strip().lower() in self._null_tokens

    def parse_number(self, v: Any) -> Decimal | None:
        """Parse a formatted number. Returns None for null tokens; raises NotANumber otherwise."""
        if isinstance(v, Decimal):
            return v
        if self.is_null(v):
            return None
        s = str(v).strip().replace(" ", " ")
        negative = False
        if self.rules.parentheses_negative and s.startswith("(") and s.endswith(")"):
            negative, s = True, s[1:-1].strip()
        if self.rules.strip_currency_symbols:
            s = _CURRENCY.sub("", s).strip()
        percent = s.endswith("%")
        if percent:
            s = s[:-1].strip()
        if s.startswith("-"):
            negative, s = (not negative), s[1:].strip()
        elif s.startswith("+"):
            s = s[1:].strip()
        if s.endswith("-"):  # trailing minus (some locales)
            negative, s = (not negative), s[:-1].strip()
        ts = self.rules.thousands_separator
        ds = self.rules.decimal_separator
        if ts:
            s = s.replace(ts, "")
        s = s.replace(" ", "") if ts != " " else s
        if ds != ".":
            s = s.replace(ds, ".")
        if not s or not re.fullmatch(r"\d*\.?\d+(?:[eE][-+]?\d+)?|\d+\.", s):
            raise NotANumber(str(v))
        try:
            d = Decimal(s)
        except InvalidOperation as exc:
            raise NotANumber(str(v)) from exc
        if percent and self.rules.percent_mode == "as_fraction":
            d = d / Decimal(100)
        return -d if negative else d

    def round_number(self, d: Decimal | None) -> Decimal | None:
        if d is None or self.rules.decimal_places is None:
            return d
        q = Decimal(1).scaleb(-self.rules.decimal_places)
        return d.quantize(q, rounding=ROUND_HALF_UP)

    def normalize_text(self, v: Any) -> str | None:
        if self.is_null(v):
            return None
        s = str(v)
        if self.rules.trim_whitespace:
            s = s.strip()
        if self.rules.text_case == "lower":
            s = s.lower()
        elif self.rules.text_case == "upper":
            s = s.upper()
        return s

    def parse_date(self, v: Any) -> ParsedDate | None:
        if self.is_null(v):
            return None
        s = str(v).strip()
        for rx, yi, qi in ((_QUARTER_A, 1, 2), (_QUARTER_B, 2, 1), (_QUARTER_C, 2, 1)):
            m = rx.match(s)
            if m:
                return ParsedDate(year=int(m.group(yi)), quarter=int(m.group(qi)), granularity="quarterly")
        m = _YEAR.match(s)
        if m:
            return ParsedDate(year=int(m.group(1)), granularity="yearly")
        for fmt in (_DAY_FORMATS_DF if self.rules.date_dayfirst else _DAY_FORMATS_MF):
            try:
                dt = datetime.strptime(s, fmt)
                return ParsedDate(dt.year, dt.month, dt.day, granularity="daily")
            except ValueError:
                pass
        for fmt in _MONTH_FORMATS:
            try:
                dt = datetime.strptime(s, fmt)
                return ParsedDate(dt.year, dt.month, granularity="monthly")
            except ValueError:
                pass
        return None

    # ------------------------------------------------------------------ inference
    def infer_numeric_columns(self, df: pd.DataFrame, exclude: set[str] | None = None) -> list[str]:
        out = []
        for c in df.columns:
            if exclude and c in exclude:
                continue
            if _DATEISH_NAME.search(str(c)):
                continue  # Year/Month/etc. are dimensions even if numeric-looking
            vals = [x for x in df[c].tolist() if not self.is_null(x)]
            if not vals:
                continue
            try:
                for x in vals:
                    self.parse_number(x)
                out.append(c)
            except NotANumber:
                continue
        return out

    def infer_date_granularity(self, series: pd.Series) -> str | None:
        """Finest granularity present if *all* non-null values parse as dates, else None."""
        vals = [x for x in series.tolist() if not self.is_null(x)]
        if not vals:
            return None
        grans = set()
        for x in vals:
            p = self.parse_date(x)
            if p is None:
                return None
            grans.add(p.granularity)
        if grans == {"daily"}:
            # all first-of-month dates usually denote a month bucket; keep daily unless caller coarsens
            return "daily"
        return min(grans, key=lambda g: _GRAN_ORDER[g])

    # ------------------------------------------------------------------ frame
    def normalize(
        self,
        df: pd.DataFrame,
        numeric_columns: list[str],
        date_columns: dict[str, str] | None = None,
        text_columns: list[str] | None = None,
    ) -> NormalizedFrame:
        out = df.copy(deep=True)  # never mutate the original/raw-derived frame
        nf = NormalizedFrame(df=out)
        r = self.rules
        date_columns = date_columns or {}
        if r.trim_whitespace:
            nf.applied.append("trim whitespace (text values)")
        for c in out.columns:
            if c in numeric_columns:
                parsed, bad = [], 0
                for x in out[c].tolist():
                    try:
                        d = self.parse_number(x)
                        if d is None and r.treat_null_as_zero:
                            d = Decimal(0)
                        parsed.append(self.round_number(d))
                    except NotANumber:
                        bad += 1
                        parsed.append(("__INVALID__", str(x)))
                out[c] = pd.Series(parsed, index=out.index, dtype=object)
                if bad:
                    nf.invalid_numbers[c] = bad
                nf.numeric_columns.append(c)
                desc = f"numeric parse '{c}' (currency={'stripped' if r.strip_currency_symbols else 'kept'}, thousands='{r.thousands_separator}', decimal='{r.decimal_separator}', percent={r.percent_mode})"
                if r.decimal_places is not None:
                    desc += f", rounded to {r.decimal_places} dp (ROUND_HALF_UP)"
                if r.treat_null_as_zero:
                    desc += ", nulls treated as 0"
                nf.applied.append(desc)
            elif c in date_columns:
                gran = date_columns[c]
                vals, bad = [], 0
                for x in out[c].tolist():
                    p = self.parse_date(x)
                    if p is None:
                        if not self.is_null(x):
                            bad += 1
                            vals.append(self.normalize_text(x))
                        else:
                            vals.append(None)
                    else:
                        vals.append(p.render(gran))
                out[c] = pd.Series(vals, index=out.index, dtype=object)
                nf.date_columns[c] = gran
                if bad:
                    nf.unparsed_dates[c] = bad
                nf.applied.append(f"date '{c}' normalized to {gran} granularity" + (f" ({bad} unparsed values kept as text)" if bad else ""))
            elif text_columns is None or c in text_columns:
                out[c] = pd.Series([self.normalize_text(x) for x in out[c].tolist()], index=out.index, dtype=object)
        if r.text_case != "preserve":
            nf.applied.append(f"text case -> {r.text_case}")
        nf.applied.append("null tokens " + ", ".join(repr(t) for t in r.null_tokens) + " -> null")
        return nf


def coarsest(*grans: str | None) -> str | None:
    gs = [g for g in grans if g]
    return max(gs, key=lambda g: _GRAN_ORDER[g]) if gs else None
