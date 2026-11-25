<p align="center">
  <img src="docs/assets/banner.svg" alt="Power BI Visual Data Comparator — animated banner" width="100%">
</p>

<p align="center">
  <img alt="Python 3.12" src="https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white">
  <img alt="Streamlit" src="https://img.shields.io/badge/UI-Streamlit-FF4B4B?logo=streamlit&logoColor=white">
  <img alt="Power BI JavaScript SDK" src="https://img.shields.io/badge/Power%20BI-JS%20SDK%202.25-F2C811?logo=powerbi&logoColor=black">
  <img alt="Playwright" src="https://img.shields.io/badge/Playwright-Chromium-2EAD33?logo=playwright&logoColor=white">
  <img alt="Tests" src="https://img.shields.io/badge/tests-158%20passed%20(mock)-0ca30c">
  <img alt="Read-only" src="https://img.shields.io/badge/Power%20BI%20access-read--only-1f3864">
</p>

<p align="center">
  <b><a href="MANUAL.md">📘 User manual</a></b> ·
  <a href="#quick-start">⚡ Quick start</a> ·
  <a href="docs/TECHNICAL_VALIDATION.md">🔬 Technical validation</a> ·
  <a href="docs/SETUP_ENTRA_AND_PERMISSIONS.md">🔐 Entra setup</a> ·
  <a href="docs/IMPLEMENTATION_STATUS.md">📋 Status</a>
</p>

Read-only reconciliation of **actual exported visual-level data** between an *original* Power BI report (13 countries, filtered to China) and a *migrated* report (China only). It identifies matching and mismatching values, missing and additional records, category and total differences, duplicates, and incomplete or unsupported extractions, with evidence for each.

Out of scope by design: DAX definitions, schemas, relationships, data types, model metadata, and report styling.

> [!IMPORTANT]
> **Verification state:** all modules are implemented and tested against **mocks**. **No live Power BI tenant was available**, so live authentication, embedding and `exportData` have **not** been verified. See [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md).

## See it in action

<p align="center">
  <img src="docs/assets/demo.gif" alt="Demo: run the mock comparison, open the dashboard, drill into a failing visual, and export the results" width="90%">
</p>
<p align="center"><sub>Recorded from the built-in demo, which uses <b>mock data</b>: Home → dashboard → visual details (value mismatch, missing and additional records) → exports & history.</sub></p>

<p align="center">
  <img src="docs/assets/pipeline.svg" alt="Animated pipeline: sign in, discover, embed and apply the China filter, export visuals, match, reconcile, report" width="100%">
</p>

## Quick start
```bash
python -m venv .venv && .venv\Scripts\activate        # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
python -m playwright install chromium
copy .env.example .env                                 # fill TENANT_ID and CLIENT_ID (see MANUAL.md §3)
streamlit run app.py                                   # then Home → "Run demo with mock data"
```
New here? Start with the **[User manual](MANUAL.md)**. It covers every page and every `.env` setting, step by step.

## How it works (technical)
```
Entra ID (MSAL) ──► REST discovery (workspaces, reports, pages) ── read-only GETs
        │
        └─► Playwright Chromium ─► frontend/embed_host.html (official powerbi-client 2.25.0, View mode)
                 └─ window.pbiExtractor: capture filters → apply China filter (Add/Replace only) →
                    enumerate pages/visuals → visual.exportData() sequentially → CSV back to Python
                         │
Python: VisualExtractor (status, truncation, completeness, context validation)
        → visual matching (scored, explainable) → column mapping → normalization (derived copies)
        → key-based reconciliation (Decimal) → status classification → SQLite → Streamlit / exports
```
The full API research, limits and decisions are in **`docs/TECHNICAL_VALIDATION.md`**.

## Install (Windows / macOS / Linux, Python 3.12)
```bash
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
python -m playwright install chromium
copy .env.example .env           # then fill TENANT_ID / CLIENT_ID (see docs/SETUP_ENTRA_AND_PERMISSIONS.md)
python -m database.migrations.migrate
```
**Windows Application Control note:** on this development machine, a Smart App Control / WDAC policy blocked SQLAlchemy's freshly downloaded compiled extension (`_processors_cy`). The workaround is a pure-Python install, which is functionally identical:
`set DISABLE_SQLALCHEMY_CEXT=1 && pip install --force-reinstall --no-deps --no-binary sqlalchemy "SQLAlchemy==2.1.9"`

## Run
| What | Command |
|------|---------|
| UI | `streamlit run app.py` (then open http://localhost:8501) |
| Demo without Power BI | Home → **Run demo with mock data** (labelled MOCK everywhere) |
| Read-only API | `uvicorn api.main:app --host 127.0.0.1 --port 8000` (docs at `/docs`) |
| Sample outputs | `python -m scripts.generate_sample_output` → `sample_output/` |

## Tests
```bash
pytest                       # unit + mock integration + browser (mock SDK) + UI smoke; live tests excluded
pytest --cov=. -q            # with coverage
pytest -m browser            # only Chromium tests (real powerbi_extractor.js + MOCK Power BI SDK)
pytest -m live -s            # LIVE tests: need .env + LIVE_* env vars (see tests/live/)
```
Mock tests use `tests/fixtures/fake_http.py`, `powerbi/mock_driver.py`, `frontend/mock/mock_powerbi.js` and `sample_data/mock_reports.py`. They are **never** live tests.

## Statuses and precedence
Defined in `comparison/status_manager.py`:
- **Per visual:** UNSUPPORTED → NOT_MAPPED → INCONCLUSIVE (failed extraction, context not validated, data/visual-filter context violation, keys not established, integrity failure) → FAIL (confirmed mismatches) → PARTIAL (truncated or unknown completeness, unconfirmed rows, duplicate keys, unmapped columns, unconfirmed fallback) → PASS.
- **Overall:** INCONCLUSIVE if any report failed to load or the context is not validated → INCONCLUSIVE if nothing could be compared → FAIL → INCONCLUSIVE → PARTIAL → PASS. PASS is impossible while any mandatory extraction, context or mapping is incomplete.

### Difference rules
- `Absolute = Migrated − Original` and `Percentage = Absolute / Original × 100`. The formula is applied literally, so a negative original flips the sign.
- Values are compared as exact `Decimal`. Tolerances default to 0/0. A value matches if `|abs| ≤ abs_tol` or `|pct| ≤ pct_tol` (the second test only applies when `pct_tol > 0` and the percentage is defined).
- Both values null → match. One value null → NULL_MISMATCH with no percentage (unless "treat blanks as zero" is on). Original 0 and migrated 0 → 0%. Original 0 and migrated non-zero → percentage **undefined** (never ∞).
- Missing and additional records are *confirmed* only if both exports are complete. Otherwise they are reported as unconfirmed, which yields PARTIAL.

## Security
- **Read-only:** the HTTP client allows only GET plus allow-listed read-only POSTs (`executeQueries`, view-only `GenerateToken`). Any other method raises `ReadOnlyViolation`. The JS extractor forces View mode and Read permission, refuses `RemoveAll`/`ReplaceAll`, and never calls save. Filter changes exist only in the in-browser session.
- **No RLS bypass:** user-owns-data embedding runs as the signed-in user. Neither `identities` nor `impersonatedUserName` is ever sent.
- **Secrets:** `CLIENT_SECRET` is held as `SecretStr`. Tokens stay in memory. Optional cache persistence is Fernet-encrypted with its key in the OS keyring, and if no secure keyring exists, persistence is refused. The log filter redacts JWTs, bearer tokens and secrets. Users are stored only as SHA-256 hashes of the account name.
- **Input validation:** workspace, report and dataset IDs must be GUIDs. All SQL goes through the SQLAlchemy ORM with bound parameters. Paths are confined with `safe_join`. CSV exports neutralize formula injection. The HTML report is autoescaped.
- **Local deployment trade-offs:** the SQLite file contains extracted business data (not secrets). Protect the host and disk (BitLocker/FileVault), restrict file ACLs, and use retention (`DATA_RETENTION_DAYS`, History → Retention). The embed host listens only on 127.0.0.1.

## Database: backup and restore
- The default is `sqlite:///data/comparator.db`. **Backup:** stop the app, then copy `data/comparator.db`, or run `sqlite3 data/comparator.db ".backup backup.db"` while it is running. **Restore:** stop the app and replace the file.
- Migrations: `python -m database.migrations.migrate` applies ordered migrations recorded in `schema_version`.
- PostgreSQL: set `DATABASE_URL=postgresql+psycopg://user:pass@host/db` and install `psycopg[binary]`. The models use portable types. *This path has not been tested yet.*

## Deployment
- **Single-user desktop (recommended):** run the steps above. Interactive sign-in opens the system browser.
- **Shared host:** use `AUTH_MODE=device_code`, run `streamlit run app.py --server.address 127.0.0.1` behind an authenticating reverse proxy (TLS). Note that each Streamlit session holds its own tokens in memory. Live extraction needs Chromium (`playwright install --with-deps chromium` on Linux).
- The FastAPI service is read-only and unauthenticated. Expose it only on localhost or behind an authenticating proxy.

## Troubleshooting
| Symptom | Likely cause / action |
|---------|----------------------|
| `Configuration incomplete` on Connection page | `.env` missing `CLIENT_ID`/`TENANT_ID` |
| `Access denied (HTTP 403)` | No workspace role. Permissions can take time to propagate |
| `Not found (HTTP 404)` | Wrong, deleted or invisible workspace/report ID |
| `throttled` | 429 retries exhausted (the client honours `Retry-After`). Try later |
| Report load timeout | Network/proxy blocks app.powerbi.com, license missing, or capacity paused |
| Every visual FAILED with an export error | Export data disabled by the admin or the report setting, or the visuals use measures (see the doc note) |
| Visual UNSUPPORTED | Custom or R/Python visual. Consider the Execute Queries fallback (labelled reconstructed) |
| Context CONFLICT | The report already filters the country field to another value. Enable replace explicitly or fix the report |
| Context UNVERIFIED | A filter or slicer on the country field could not be interpreted, or a filter capture failed |
| POSSIBLY_TRUNCATED | 30,000-row `exportData` limit reached. Completeness cannot be established |
| `DLL load failed … Application Control policy` | See the install note above |

## Known limitations
See `docs/TECHNICAL_VALIDATION.md` §10–11. In brief:
- Live behaviour is unverified.
- The API row limit is 30,000.
- CSV exports carry no totals, so totals are derived as evidence only.
- Custom and R visuals are unsupported.
- Visuals that use model measures may not export, per Microsoft's doc. This needs live confirmation.
- Effective filters from hidden filters, cross-highlighting and RLS are not fully observable.
- The matrix export layout is undocumented. Both long and wide layouts are handled heuristically.
- The XMLA query path is untested (ADOMD.NET not available).
- The visual crop for screenshots is approximate.

## Project layout
`config/` settings · `core/` contracts & security · `authentication/` MSAL & tokens · `powerbi/` REST clients, embed, filter manager, extractor, mock driver, fallbacks · `frontend/` JS extractor, embed host, vendored SDK, mock SDK · `comparison/` normalizer, mapper, matcher, comparator, matrix, reconciliation, status · `database/` models, repository, migrations · `reporting/` Excel/CSV/JSON/HTML/screenshots · `services/` orchestration · `ui/` + `views/` Streamlit · `api/` FastAPI · `tests/` unit, integration (mock), live · `sample_data/` fixtures · `sample_output/` generated MOCK outputs · `scripts/` sample-output & demo-GIF generators · `docs/` (incl. `docs/assets/` animated SVGs and demo GIF) · `MANUAL.md` user manual.
