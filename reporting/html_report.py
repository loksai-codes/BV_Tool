"""Self-contained HTML report (Jinja2 with autoescaping — no script, no external assets)."""
from __future__ import annotations

from jinja2 import Environment, select_autoescape

from core.contracts import ComparisonRunResult
from reporting import common as c

_TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>{{ run.name }} — Visual Data Comparison</title>
<style>
body{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#1f2937;max-width:1400px}
h1{font-size:22px;margin:0 0 4px} h2{font-size:17px;margin-top:28px;border-bottom:1px solid #e5e7eb;padding-bottom:4px}
.banner{background:#fde2e2;color:#9b1c1c;padding:8px 12px;border-radius:6px;font-weight:600;margin:12px 0}
.kpis{display:flex;flex-wrap:wrap;gap:10px;margin:12px 0}.kpi{border:1px solid #e5e7eb;border-radius:8px;padding:10px 14px;min-width:120px}
.kpi b{display:block;font-size:20px}.kpi span{font-size:12px;color:#6b7280}
table{border-collapse:collapse;width:100%;font-size:12.5px;margin-top:8px}th,td{border:1px solid #e5e7eb;padding:5px 7px;text-align:left;vertical-align:top}
th{background:#f3f4f6}.s{font-weight:600;padding:2px 8px;border-radius:10px;white-space:nowrap}
.PASS{background:#c6efce;color:#006100}.FAIL{background:#ffc7ce;color:#9c0006}.PARTIAL,.INCONCLUSIVE{background:#ffeb9c;color:#7a5b00}
.UNSUPPORTED,.NOT_MAPPED{background:#e5e7eb;color:#374151} .muted{color:#6b7280;font-size:12px}
</style></head><body>
<h1>{{ run.name }}</h1>
<div class="muted">Run {{ run.run_id or "—" }} · {{ run.started_at.strftime("%Y-%m-%d %H:%M UTC") }} · context: {{ run.config.country.value }}</div>
{% if run.is_mock %}<div class="banner">{{ mock_banner }}</div>{% endif %}
<p>Overall status: <span class="s {{ run.overall_status.value }}">{{ run.overall_status.value }}</span></p>
<ul>{% for r in run.overall_reasons %}<li>{{ r }}</li>{% endfor %}</ul>
<div class="kpis">{% for k, v in summary.items() %}<div class="kpi"><b>{{ v }}</b><span>{{ k.replace('_',' ') }}</span></div>{% endfor %}</div>
<h2>Context evidence</h2>
<table><tr><th>Report</th><th>Status</th><th>Action</th><th>Messages</th></tr>
{% for e in [run.original, run.migrated] %}<tr><td>{{ e.role }} — {{ e.report_name }}</td><td><span class="s {{ 'PASS' if e.context.status.value in ('VALIDATED','NOT_REQUIRED') else 'INCONCLUSIVE' }}">{{ e.context.status.value }}</span></td>
<td>{{ e.context.action_taken or "" }}</td><td>{{ e.context.messages|join(" · ") }}</td></tr>{% endfor %}</table>
<h2>Visual summary</h2>
<table><tr><th>Status</th><th>Original</th><th>Migrated</th><th>Type</th><th>Compared</th><th>Missing</th><th>Additional</th><th>Value mismatches</th><th>Reasons</th></tr>
{% for r in run.visual_results %}<tr><td><span class="s {{ r.status.value }}">{{ r.status.value }}</span></td>
<td>{{ r.original_page_display or "" }} › {{ r.original_title or r.original_visual or "—" }}</td>
<td>{{ r.migrated_page_display or "" }} › {{ r.migrated_title or r.migrated_visual or "—" }}</td>
<td>{{ r.visual_type }}</td><td>{{ r.rows_compared }}</td><td>{{ r.missing_rows }}</td><td>{{ r.additional_rows }}</td><td>{{ r.numeric_mismatches }}</td>
<td>{{ r.reasons|join(" · ") }}</td></tr>{% endfor %}</table>
<h2>Differences</h2>
{% if mismatches %}<table><tr><th>Visual</th><th>Type</th><th>Confirmed</th><th>Key</th><th>Column</th><th>Original</th><th>Migrated</th><th>Abs diff</th><th>% diff</th></tr>
{% for m in mismatches %}<tr><td>{{ m["Original visual"] }}</td><td>{{ m["Mismatch type"] }}</td><td>{{ m["Confirmed"] }}</td><td>{{ m["Key"] }}</td><td>{{ m["Column"] or "" }}</td>
<td>{{ m["Original value"] if m["Original value"] is not none else "" }}</td><td>{{ m["Migrated value"] if m["Migrated value"] is not none else "" }}</td>
<td>{{ m["Absolute difference"] or "" }}</td><td>{{ m["Percentage difference"] or (m["Percentage note"] or "") }}</td></tr>{% endfor %}</table>
{% else %}<p>No differences recorded.</p>{% endif %}
<h2>Extraction errors &amp; unsupported visuals</h2>
{% if errors %}<table><tr><th>Role</th><th>Page</th><th>Visual</th><th>Type</th><th>Status</th><th>Detail</th></tr>
{% for e in errors %}<tr><td>{{ e.Role }}</td><td>{{ e.Page }}</td><td>{{ e.Visual }}</td><td>{{ e.Type }}</td><td>{{ e.Status }}</td><td>{{ e.Detail }}</td></tr>{% endfor %}</table>
{% else %}<p>None.</p>{% endif %}
<p class="muted">Scope: actual exported visual data only. DAX definitions, schemas, relationships and model metadata are not compared.
Context validation covers filters exposed by the Power BI JavaScript API; it cannot prove equivalence of hidden filters or RLS.</p>
</body></html>"""

_env = Environment(autoescape=select_autoescape(default=True, default_for_string=True))
_tpl = _env.from_string(_TEMPLATE)


def build_html(run: ComparisonRunResult) -> str:
    errors = [{"Role": e["Role"], "Page": e["Page"], "Visual": e["Visual"], "Type": e["Type"], "Status": e["Status"],
               "Detail": e["Error"]} for e in c.extraction_error_rows(run)]
    errors += [{"Role": u["Role"], "Page": u["Page"], "Visual": u["Visual"], "Type": u["Type"], "Status": "UNSUPPORTED",
                "Detail": u["Reason"]} for u in c.unsupported_rows(run)]
    from core.contracts import MismatchType

    mismatches = c.mismatch_rows(run, set(MismatchType))[:2000]
    return _tpl.render(run=run, summary=run.summary(), mismatches=mismatches, errors=errors, mock_banner=c.MOCK_BANNER)
