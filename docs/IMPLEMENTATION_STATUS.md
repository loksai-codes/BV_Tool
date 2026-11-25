# Implementation Status Ledger

**Last updated:** 2026-11-25
**Environment:** Windows 11, Python 3.12.10 (venv), Node 24.11.1, Playwright 1.65.2 + Chromium, powerbi-client 2.25.0 (vendored)
**Live Power BI access:** **NONE.** No tenant, credentials or reports were available. Nothing below is live-tested.

Legend: **Implemented** · **Unit-tested** (pure logic) · **Mock-tested** (fake HTTP / MockDriver / mock JS SDK) · **Browser-tested** (real Chromium + real `powerbi_extractor.js` + MOCK SDK) · **Live-tested** (real Power BI) · **Not verified**

## Latest test run
`pytest --cov=.` → **158 passed, 0 failed, 2 deselected (live)**. Total line coverage **90%**.
- Collected: 91 unit, 67 integration (mock / browser / UI / API), 2 live (deselected by default; when run with `-m live` they **skip** because `LIVE_*` variables are missing).
- One third-party deprecation warning (Starlette TestClient/httpx). It is harmless.
- Command for the live tests: `pytest -m live -s` (see `tests/live/test_live_powerbi.py`).

### Failures found and fixed during development
1. SQLAlchemy's compiled extension was blocked by Windows Application Control (`DLL load failed … _processors_cy`). **Fix:** reinstalled SQLAlchemy as pure Python (`--no-binary`, `DISABLE_SQLALCHEMY_CEXT=1`). Documented in the README.
2. Browser tests skipped because a second `sync_playwright()` instance can't start in the same thread. **Fix:** the fixture closes the previous driver. Production code uses one driver for both reports.
3. Column headers with whitespace broke key grouping (`KeyError: ' A '`). The normalizer renamed columns after keys had been chosen. **Fix:** headers are trimmed at the start of reconciliation, and the normalizer no longer renames columns.
4. The fallback copied `rows_requested` twice from the template (`TypeError`). **Fix:** it is excluded from the copy.
5. UI: `AppTest.switch_page` needs file-based pages. **Fix:** pages are registered as `views/*.py` wrappers.
6. UI visual check (screenshot): the differences chart hid every other y-label, and the details banner said "Overall status" for a single visual. **Both fixed.**

## Phase ledger

| Phase | State | Evidence |
|-------|-------|----------|
| 1 Research & validation | **Done** | `docs/TECHNICAL_VALIDATION.md`: 20 sources, verified 2026-11-25; SDK signatures checked against the npm `.d.ts`; doc discrepancies recorded (`setFilters` → `updateFilters`, `FilterType.BasicFilter` does not exist) |
| 2 Foundation | **Done (mock)** | Settings, MSAL (interactive, device code, SP), token manager, encrypted cache, read-only HTTP client with retries, workspace/report/page discovery, SQLAlchemy models, migrations, repository. Tests: `test_auth_mock`, `test_discovery_mock`, `test_security`, `test_token_cache_and_db` |
| 3 Extraction engine | **Done (mock + browser)**, live **not verified** | `frontend/powerbi_extractor.js`, `embed_host.html`, localhost host server, `PlaywrightDriver`, `VisualExtractor`, `MockDriver`, mock SDK. Tests: `test_extraction_mock` (13), `test_browser_extractor_mock` (3, real Chromium) |
| 4 China filtering | **Done (mock + browser)**, live **not verified** | `filter_manager.py`: plan add/none/conflict/replace, validation of report/page/slicer/visual filters, unrelated-filter preservation, data-level check. Tests: `test_filter_manager` (14), extraction context tests |
| 5 Visual matching | **Done** | `visual_matcher.py` (7 weighted signals, renormalization, ambiguity margin, auto-approve threshold), manual mappings, page mappings, saved profiles. Tests: `test_matching_and_mapping`, `test_mapping_profile_reuse` |
| 6 Reconciliation | **Done** | Normalizer (Decimal, currency, %, locale, dates daily/monthly/quarterly/yearly), column mapper, comparator, matrix unpivot, status manager, reconciliation. Tests: `test_normalizer` (32), `test_comparator` (13), `test_status_and_reconciliation` (16), end-to-end mock |
| 7 UI | **Done (mock)** | 7 Streamlit pages. Tests: `test_ui_smoke` (15, AppTest). Rendered in real Chromium and screenshots inspected. The live connection page flow is **not verified** |
| 8 Exports | **Done** | Excel (11 sheets, conditional formatting), CSV zip (formula-injection safe), JSON evidence (raw CSV + SHA-256), HTML (autoescaped). Tests: `test_exports` (workbook opened with openpyxl, contents asserted). Sample files in `sample_output/` |
| 9 QA | **Done for local scope** | Unsupported visuals, truncation, failed loads, filter conflicts, context violations, integrity failures and fallback labelling are all tested. Live connectivity was **not attempted** (no credentials) |
| 10 Delivery | **Done for local scope** | README, setup guide, validation doc, this ledger, fixtures, sample output |

Additional components: Execute Queries fallback (mock-tested); XMLA connection-string helper (unit-tested; the query path is **untested**, no ADOMD.NET); screenshot crop/OCR/cleanup helpers (unit-tested; OCR is optional and not installed); read-only FastAPI (`test_api`).

## Acceptance criteria

| Criterion | State |
|-----------|-------|
| User can authenticate to Power BI | Implemented; **mock-tested only. NOT live-tested** |
| User can select two workspaces | Implemented (Connection page + `WorkspaceClient`); mock-tested; not live-tested |
| User can select two reports | Implemented; mock-tested; not live-tested |
| Application can discover report pages | REST + JS `getPages`; mock- and browser-tested; not live-tested |
| Application can enumerate supported visuals | JS `getVisuals` + classification; browser-tested with mock SDK; not live-tested |
| Application can apply and validate China context on the original report | Implemented (`updateFilters` Add/Replace + validation); browser-tested with mock SDK; **not live-tested** |
| Application can extract actual visual-level summarized data | `visual.exportData(Summarized, 30000)`; browser-tested with mock SDK; **no real export performed** |
| Application can extract corresponding migrated report visual data | Same path; mock-tested; not live-tested |
| Application can map corresponding visuals | Done (auto + manual + profiles); unit/mock-tested |
| Application can normalize datasets without altering originals | Done; tests assert originals unchanged and the SHA-256 intact |
| Application can compare visual values | Done; unit/mock-tested |
| Application can identify missing records | Done; tested (injected D2 detected) |
| Application can identify additional records | Done; tested (injected D3 detected) |
| Application can identify numeric mismatches | Done; tested (injected D1 detected, +1500.00) |
| Application calculates absolute and percentage differences safely | Done; zero/null/negative/large/tolerance cases tested |
| Application displays detailed evidence | Done (Details page, 9 tabs); UI smoke-tested |
| Application generates Excel output | Done; workbook contents tested |
| Application retains comparison history | Done (SQLite, reload round-trip, history comparison); tested |
| Application distinguishes PASS, FAIL, PARTIAL, INCONCLUSIVE, UNSUPPORTED, NOT MAPPED | Done; each status tested |
| Application never reports PASS when required extraction or context is incomplete | Enforced by precedence; tests for truncated, failed, unsupported, unmapped, context not validated, fatal load |
| Unit tests pass | **Yes**: 158/158 |
| Mock tests are clearly distinguished from live tests | Yes: `live` marker is deselected by default; mock modules are labelled; mock runs carry `is_mock` and a MOCK banner in the UI and every export |
| Security and limitations are documented | Yes: README (Security, Limitations), TECHNICAL_VALIDATION §9–11, setup guide |

## Documentation & presentation (added 2026-11-25)
- `MANUAL.md`: user manual covering install, every `.env` setting, the mock demo, the live step-by-step workflow, reading results, exports, commands, backups, troubleshooting and a glossary.
- README: animated banner (`docs/assets/banner.svg`), animated pipeline (`docs/assets/pipeline.svg`) and a demo GIF (`docs/assets/demo.gif`, 1.8 MB, 9 captioned scenes). The GIF was recorded from the running app with MOCK data by `scripts/record_demo_gif.py`. All three were rendered in Chromium and checked visually; a chip-overlap bug in the banner and a palette issue in the GIF were found and fixed.

## Blockers
1. **No Power BI tenant or credentials.** This blocks live authentication, discovery, embedding, `exportData`, filter application and screenshot capture. The procedure to unblock is in `docs/SETUP_ENTRA_AND_PERMISSIONS.md` §6.
2. **Open questions that only live testing can answer** (TECHNICAL_VALIDATION §11):
   - Does `exportData` work on visuals that use model measures? Microsoft's page says export is "not available on visuals using model or report measures".
   - The real CSV format: headers, number formatting and culture.
   - Whether `getFilters` exposes pre-existing country filters.
   - Whether AAD-token embedding from `http://127.0.0.1` works.
3. The XMLA query path needs ADOMD.NET plus `pyadomd`, neither of which is available here.

## Next steps
1. Configure `.env` and run the live checklist. Record the outcomes below.
2. Adjust the CSV/number parsing defaults to the real export format if needed.
3. If measure-based visuals fail to export, configure Execute Queries fallbacks per visual. Each one stays labelled as reconstructed data and capped at PARTIAL unless equivalence is confirmed.
4. Test the PostgreSQL deployment (`DATABASE_URL`) if needed.

## Live verification log
| Date | Item | Result |
|------|------|--------|
| — | No live tests performed yet | — |
