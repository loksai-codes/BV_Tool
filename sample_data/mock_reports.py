"""MOCK report specifications — deterministic fixtures for tests and demo mode.

THIS IS NOT POWER BI DATA. It simulates two reports:
- Original (13 countries incl. China), report filter on Geography[CountryName]
- Migrated (China only), different page/visual names, titles and column names

Injected, known differences (so tests can assert exact findings):
  D1  migrated Electronics / 2024-03 Sales +1500.00               -> value mismatch
  D2  original Home / 2024-07 exists (Units 0), migrated lacks it -> missing record
  D3  migrated adds Accessories / 2024-12 (Sales 800, Units 0)    -> additional record
  D4  migrated Apparel / 2024-05 Sales +0.004                     -> only visible without 2-dp rounding
Units totals are unaffected by D1-D4, so "Units Trend" should PASS.

Each visual carries pre-computed export CSVs keyed by the effective country
selection ("__all__" or a country name) so both the Python MockDriver and the
browser mock SDK return consistent data without a second aggregation engine.
"""
from __future__ import annotations

import io
import random
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from typing import Any

import pandas as pd

COUNTRIES = ["China", "India", "Japan", "Germany", "France", "United Kingdom", "United States",
             "Brazil", "Canada", "Australia", "Mexico", "Italy", "Spain"]
CATEGORIES = ["Electronics", "Apparel", "Home", "Sports"]
MONTHS = pd.period_range("2024-01", "2024-12", freq="M")

ORIGINAL_REPORT_ID = "0a0a0a0a-0000-4000-8000-000000000001"
MIGRATED_REPORT_ID = "0b0b0b0b-0000-4000-8000-000000000002"
ORIGINAL_WS = "1a1a1a1a-0000-4000-8000-000000000001"
MIGRATED_WS = "1b1b1b1b-0000-4000-8000-000000000002"
COUNTRY_TARGET_ORIGINAL = {"table": "Geography", "column": "CountryName"}
COUNTRY_TARGET_MIGRATED = {"table": "Geography", "column": "Country"}


def _money(x: float | Decimal) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


@lru_cache(maxsize=1)
def base_facts() -> pd.DataFrame:
    rng = random.Random(42)
    rows = []
    for c in COUNTRIES:
        for m in MONTHS:
            for cat in CATEGORIES:
                sales = _money(round(rng.uniform(1000, 50000), 2))
                units = rng.randint(10, 900)
                if c == "China" and cat == "Home" and str(m) == "2024-07":
                    units = 0  # D2 helper: removing this row must not change Units totals
                rows.append({"Country": c, "Month": m, "Category": cat, "Sales": sales, "Units": units})
    return pd.DataFrame(rows)


def migrated_facts() -> pd.DataFrame:
    df = base_facts()
    df = df[df["Country"] == "China"].copy()
    m = lambda s: df["Month"].astype(str) == s  # noqa: E731
    df.loc[(df["Category"] == "Electronics") & m("2024-03"), "Sales"] += Decimal("1500.00")          # D1
    df = df[~((df["Category"] == "Home") & m("2024-07"))]                                             # D2
    df = pd.concat([df, pd.DataFrame([{"Country": "China", "Month": pd.Period("2024-12", "M"),
                                       "Category": "Accessories", "Sales": Decimal("800.000"), "Units": 0}])])  # D3
    df.loc[(df["Category"] == "Apparel") & m("2024-05"), "Sales"] += Decimal("0.004")                # D4
    return df.reset_index(drop=True)


# ---------------------------------------------------------------- formatting helpers
def _fmt_month_original(p: pd.Period) -> str:
    return p.strftime("%B %Y")             # "January 2024"


def _fmt_month_migrated(p: pd.Period) -> str:
    return p.start_time.strftime("%Y-%m-%d")  # "2024-01-01"


def _quarter_original(p: pd.Period) -> str:
    return f"{p.year} Q{p.quarter}"


def _quarter_migrated(p: pd.Period) -> str:
    return f"Q{p.quarter} {p.year}"


def _num(d: Decimal) -> str:
    s = format(d.normalize(), "f")
    return s


def _csv(df: pd.DataFrame) -> str:
    buf = io.StringIO()
    df.to_csv(buf, index=False, lineterminator="\r\n")
    return buf.getvalue()


def _agg(df: pd.DataFrame, by: list[str], measures: dict[str, str]) -> pd.DataFrame:
    if by:
        g = df.groupby(by, sort=True, observed=True).agg({src: "sum" for src in measures.values()}).reset_index()
    else:
        g = pd.DataFrame([{src: df[src].sum() for src in measures.values()}])
    return g.rename(columns={v: k for k, v in measures.items()})


def _visual_csvs(facts: pd.DataFrame, builder, countries: list[str]) -> dict[str, str]:
    out = {"__all__": _csv(builder(facts))}
    for c in countries:
        out[c] = _csv(builder(facts[facts["Country"] == c]))
    return out


def _original_builders():
    def card(df):
        return pd.DataFrame([{"Total Sales": _num(sum(df["Sales"], Decimal(0)))}])

    def by_month(df):
        g = _agg(df, ["Month"], {"Sales": "Sales"})
        return pd.DataFrame({"Month": g["Month"].map(_fmt_month_original), "Sales": g["Sales"].map(_num)})

    def table(df):
        g = _agg(df, ["Category", "Month"], {"Sales": "Sales", "Units": "Units"})
        return pd.DataFrame({"Category": g["Category"], "Month": g["Month"].map(_fmt_month_original),
                             "Sales": g["Sales"].map(_num), "Units": g["Units"].astype(str)})

    def pie(df):
        g = _agg(df, ["Category"], {"Sales": "Sales"})
        return pd.DataFrame({"Category": g["Category"], "Sales": g["Sales"].map(_num)})

    def units(df):
        g = _agg(df, ["Month"], {"Units": "Units"})
        return pd.DataFrame({"Month": g["Month"].map(_fmt_month_original), "Units": g["Units"].astype(str)})

    def matrix(df):
        d = df.assign(Quarter=df["Month"].map(lambda p: p.asfreq("Q")))
        g = _agg(d, ["Category", "Quarter"], {"Sales": "Sales"})
        return pd.DataFrame({"Category": g["Category"], "Quarter": g["Quarter"].map(lambda q: f"{q.year} Q{q.quarter}"),
                             "Sales": g["Sales"].map(_num)})

    def by_country(df):
        g = _agg(df, ["Country"], {"Sales": "Sales"})
        return pd.DataFrame({"CountryName": g["Country"], "Sales": g["Sales"].map(_num)})

    return card, by_month, table, pie, units, matrix, by_country


def _migrated_builders():
    def card(df):
        return pd.DataFrame([{"Total Revenue": _num(sum(df["Sales"], Decimal(0)))}])

    def by_month(df):
        g = _agg(df, ["Month"], {"Revenue": "Sales"})
        return pd.DataFrame({"Period": g["Month"].map(_fmt_month_migrated), "Revenue": g["Revenue"].map(_num)})

    def table(df):
        g = _agg(df, ["Category", "Month"], {"Revenue": "Sales", "Units": "Units"})
        return pd.DataFrame({"Category": g["Category"], "Period": g["Month"].map(_fmt_month_migrated),
                             "Revenue": g["Revenue"].map(_num), "Units": g["Units"].astype(str)})

    def pie(df):
        g = _agg(df, ["Category"], {"Revenue": "Sales"})
        return pd.DataFrame({"Category": g["Category"], "Revenue": g["Revenue"].map(_num)})

    def units(df):
        g = _agg(df, ["Month"], {"Units": "Units"})
        return pd.DataFrame({"Period": g["Month"].map(_fmt_month_migrated), "Units": g["Units"].astype(str)})

    def matrix(df):
        d = df.assign(Quarter=df["Month"].map(lambda p: p.asfreq("Q")))
        g = _agg(d, ["Category", "Quarter"], {"Revenue": "Sales"})
        return pd.DataFrame({"Category": g["Category"], "Quarter": g["Quarter"].map(lambda q: f"Q{q.quarter} {q.year}"),
                             "Revenue": g["Revenue"].map(_num)})

    def by_country(df):
        g = _agg(df, ["Country"], {"Revenue": "Sales"})
        return pd.DataFrame({"Country": g["Country"], "Revenue": g["Revenue"].map(_num)})

    def margin(df):
        return pd.DataFrame([{"Margin %": "23.4%"}])

    return card, by_month, table, pie, units, matrix, by_country, margin


def _layout(x, y, w=400, h=250):
    return {"x": x, "y": y, "z": 0, "width": w, "height": h, "displayState": {"mode": 0}}


def original_spec() -> dict[str, Any]:
    f = base_facts()
    card, by_month, table, pie, units, matrix, by_country = _original_builders()
    cs = COUNTRIES
    return {
        "reportId": ORIGINAL_REPORT_ID,
        "countryTarget": COUNTRY_TARGET_ORIGINAL,
        "initialReportFilters": [
            {"$schema": "http://powerbi.com/product/schema#basic", "target": {"table": "Calendar", "column": "Year"},
             "operator": "In", "values": [2024], "filterType": 1},
        ],
        "pages": [
            {"name": "ReportSection1a2b", "displayName": "Sales Overview", "visibility": 0, "filters": []},
            {"name": "ReportSection3c4d", "displayName": "Trends", "visibility": 0, "filters": []},
        ],
        "visuals": {
            "ReportSection1a2b": [
                {"name": "a1f00c11d2e3f4a5b6c7", "type": "card", "title": "Total Sales", "layout": _layout(0, 0, 200, 120), "csvByCountry": _visual_csvs(f, card, cs)},
                {"name": "a1f00c11d2e3f4a5b6c8", "type": "clusteredColumnChart", "title": "Sales by Month", "layout": _layout(220, 0), "csvByCountry": _visual_csvs(f, by_month, cs)},
                {"name": "a1f00c11d2e3f4a5b6c9", "type": "tableEx", "title": "Sales by Category and Month", "layout": _layout(0, 260, 620, 300), "csvByCountry": _visual_csvs(f, table, cs)},
                {"name": "a1f00c11d2e3f4a5b6d0", "type": "pieChart", "title": "Sales Share by Category", "layout": _layout(640, 0), "csvByCountry": _visual_csvs(f, pie, cs)},
                {"name": "a1f00c11d2e3f4a5b6d1", "type": "slicer", "title": "Country", "layout": _layout(1060, 0, 200, 300),
                 "slicerState": {"filters": [], "targets": [COUNTRY_TARGET_ORIGINAL]}},
                {"name": "a1f00c11d2e3f4a5b6d2", "type": "textbox", "title": None, "layout": _layout(0, 600, 300, 40)},
                {"name": "a1f00c11d2e3f4a5b6d3", "type": "bulletChart1A2B3C4D5E6F7A8B9C0D1E2F3A4B", "title": "Target Bullet",
                 "layout": _layout(640, 260), "exportError": {"message": "Export data is not supported for this visual", "errorCode": "ExportDataNotSupported"}},
                {"name": "a1f00c11d2e3f4a5b6d4", "type": "scriptVisual", "title": "R Forecast", "layout": _layout(640, 520)},
            ],
            "ReportSection3c4d": [
                {"name": "b2e00c11d2e3f4a5b6c7", "type": "lineChart", "title": "Units Trend", "layout": _layout(0, 0, 800, 300), "csvByCountry": _visual_csvs(f, units, cs)},
                {"name": "b2e00c11d2e3f4a5b6c8", "type": "pivotTable", "title": "Category by Quarter", "layout": _layout(0, 320, 600, 300), "csvByCountry": _visual_csvs(f, matrix, cs)},
                {"name": "b2e00c11d2e3f4a5b6c9", "type": "tableEx", "title": "Sales by Country", "layout": _layout(620, 320), "csvByCountry": _visual_csvs(f, by_country, cs)},
            ],
        },
    }


def migrated_spec() -> dict[str, Any]:
    f = migrated_facts()
    card, by_month, table, pie, units, matrix, by_country, margin = _migrated_builders()
    cs = ["China"]
    return {
        "reportId": MIGRATED_REPORT_ID,
        "countryTarget": COUNTRY_TARGET_MIGRATED,
        "initialReportFilters": [],
        "pages": [
            {"name": "ReportSectionAA01", "displayName": "Overview", "visibility": 0, "filters": []},
            {"name": "ReportSectionBB02", "displayName": "Trend Analysis", "visibility": 0, "filters": []},
        ],
        "visuals": {
            "ReportSectionAA01": [
                {"name": "c3d11e22f3a4b5c6d7e8", "type": "card", "title": "Total Revenue", "layout": _layout(0, 0, 200, 120), "csvByCountry": _visual_csvs(f, card, cs)},
                {"name": "c3d11e22f3a4b5c6d7e9", "type": "clusteredColumnChart", "title": "Revenue by Month", "layout": _layout(220, 0), "csvByCountry": _visual_csvs(f, by_month, cs)},
                {"name": "c3d11e22f3a4b5c6d7f0", "type": "tableEx", "title": "Revenue by Category & Period", "layout": _layout(0, 260, 620, 300), "csvByCountry": _visual_csvs(f, table, cs)},
                {"name": "c3d11e22f3a4b5c6d7f1", "type": "donutChart", "title": "Revenue Share by Category", "layout": _layout(640, 0), "csvByCountry": _visual_csvs(f, pie, cs)},
                {"name": "c3d11e22f3a4b5c6d7f2", "type": "card", "title": "Margin %", "layout": _layout(1060, 0, 200, 120), "csvByCountry": _visual_csvs(f, margin, cs)},
                {"name": "c3d11e22f3a4b5c6d7f3", "type": "textbox", "title": None, "layout": _layout(0, 600, 300, 40)},
            ],
            "ReportSectionBB02": [
                {"name": "d4e22f33a4b5c6d7e8f9", "type": "lineChart", "title": "Units Trend", "layout": _layout(0, 0, 800, 300), "csvByCountry": _visual_csvs(f, units, cs)},
                {"name": "d4e22f33a4b5c6d7e8fa", "type": "pivotTable", "title": "Category by Quarter", "layout": _layout(0, 320, 600, 300), "csvByCountry": _visual_csvs(f, matrix, cs)},
                {"name": "d4e22f33a4b5c6d7e8fb", "type": "tableEx", "title": "Revenue by Country", "layout": _layout(620, 320), "csvByCountry": _visual_csvs(f, by_country, cs)},
            ],
        },
    }


def mock_report_info(role: str):
    from core.contracts import ReportInfo

    if role == "original":
        return ReportInfo(id=ORIGINAL_REPORT_ID, name="Sales Report (Original) [MOCK]", workspace_id=ORIGINAL_WS,
                          dataset_id="2a2a2a2a-0000-4000-8000-000000000001",
                          embed_url=f"https://app.powerbi.com/reportEmbed?reportId={ORIGINAL_REPORT_ID}")
    return ReportInfo(id=MIGRATED_REPORT_ID, name="Sales Report (Migrated) [MOCK]", workspace_id=MIGRATED_WS,
                      dataset_id="2b2b2b2b-0000-4000-8000-000000000002",
                      embed_url=f"https://app.powerbi.com/reportEmbed?reportId={MIGRATED_REPORT_ID}")


def demo_country_config():
    from core.contracts import CountryContextConfig

    return CountryContextConfig(
        original_table="Geography", original_column="CountryName",
        migrated_table="Geography", migrated_column="Country", value="China",
    )
