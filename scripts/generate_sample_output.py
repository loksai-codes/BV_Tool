"""Generate sample (MOCK) comparison outputs into sample_output/.

    python -m scripts.generate_sample_output
"""
from __future__ import annotations

from pathlib import Path

from reporting.csv_export import build_zip
from reporting.excel_export import build_workbook
from reporting.html_report import build_html
from reporting.json_export import build_json
from services.comparison_service import run_demo

OUT = Path(__file__).resolve().parent.parent / "sample_output"


def main() -> None:
    OUT.mkdir(exist_ok=True)
    run = run_demo(None, approve_all_suggestions=True)
    (OUT / "sample_comparison_MOCK.xlsx").write_bytes(build_workbook(run))
    (OUT / "sample_comparison_MOCK_csv.zip").write_bytes(build_zip(run))
    (OUT / "sample_comparison_MOCK.json").write_text(build_json(run), encoding="utf-8")
    (OUT / "sample_comparison_MOCK.html").write_text(build_html(run), encoding="utf-8")
    print(f"{run.overall_status.value}: wrote {len(list(OUT.iterdir()))} files to {OUT}")


if __name__ == "__main__":
    main()
