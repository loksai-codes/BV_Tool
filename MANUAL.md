# User Manual — Power BI Visual Data Comparator

This manual explains, step by step, how to install, configure and use the tool.
For the architecture and API research behind it, see [`docs/TECHNICAL_VALIDATION.md`](docs/TECHNICAL_VALIDATION.md).

> **What this tool does in one sentence:** it opens your two Power BI reports read-only, applies the China context to the original report, exports the data that each visual actually displays, and tells you, visual by visual and row by row, where the migrated report differs.
>
> **What it does not do:** it never compares DAX, measures, schemas, relationships or report design, and it never changes a report, a semantic model or any data.

---

## Contents
1. [Before you start](#1-before-you-start)
2. [Install](#2-install)
3. [The `.env` file: how to use it](#3-the-env-file-how-to-use-it)
4. [Try it in 1 minute with mock data](#4-try-it-in-1-minute-with-mock-data)
5. [Compare your real reports, step by step](#5-compare-your-real-reports-step-by-step)
6. [Reading the results](#6-reading-the-results)
7. [Exports & history](#7-exports--history)
8. [Command reference](#8-command-reference)
9. [Data, backups & clean-up](#9-data-backups--clean-up)
10. [Troubleshooting & FAQ](#10-troubleshooting--faq)
11. [Glossary](#11-glossary)

---

## 1. Before you start

| You need | Why |
|----------|-----|
| Windows, macOS or Linux with **Python 3.12** | Runs the application |
| Internet access to `login.microsoftonline.com`, `api.powerbi.com` and `app.powerbi.com` | Sign-in, discovery and embedding |
| A **Microsoft Entra app registration** (your admin can create it) | Lets the tool sign you in. See [`docs/SETUP_ENTRA_AND_PERMISSIONS.md`](docs/SETUP_ENTRA_AND_PERMISSIONS.md) |
| **Viewer** access (or higher) to both workspaces | To read and export the reports |
| Power BI **Pro / PPU** license, or content on a capacity | Microsoft's requirement for embedding |
| "Export data" allowed by your tenant admin **and** in both reports' settings | The tool reads the same data as *Export data* in Power BI |

You **do not** need edit rights, Build permission or admin rights for the normal summarized comparison.

---

## 2. Install

Open a terminal in the project folder (the folder that contains `app.py`):

```bash
# 1. Create an isolated Python environment
python -m venv .venv

# 2. Activate it
.venv\Scripts\activate              # Windows
source .venv/bin/activate           # macOS / Linux

# 3. Install the dependencies
pip install -r requirements-dev.txt

# 4. Install the browser used to open the reports
python -m playwright install chromium

# 5. Create your settings file (see section 3)
copy .env.example .env              # Windows
cp .env.example .env                # macOS / Linux

# 6. Create the database
python -m database.migrations.migrate
```

> **Windows only:** if you see `DLL load failed … An Application Control policy has blocked this file`, run
> `set DISABLE_SQLALCHEMY_CEXT=1` and then `pip install --force-reinstall --no-deps --no-binary sqlalchemy "SQLAlchemy==2.1.9"`.
> This installs a pure-Python build that works the same way.

Every time you open a new terminal, activate the environment again (step 2) before running the tool.

---

## 3. The `.env` file: how to use it

The tool reads its settings from a file named **`.env`** in the project folder. The repository ships a template called **`.env.example`**.

**How to use it:**
1. **Copy** `.env.example` to a new file named `.env`. Never edit or commit `.env.example` with real values.
2. **Open `.env`** in any text editor (Notepad, VS Code…) and fill in the values below.
3. **Save** and restart the app (`Ctrl+C`, then `streamlit run app.py`). Settings are read at start-up.
4. **Keep `.env` private.** It is listed in `.gitignore`, so git will not upload it. Never paste it into chats or tickets.

Rules for the file: one `NAME=value` per line, no spaces around `=`, no quotes needed, and lines starting with `#` are comments.

### Every setting explained

| Setting | Required? | What to put there | Example |
|---------|-----------|-------------------|---------|
| `TENANT_ID` | **Yes** | Your organization's *Directory (tenant) ID*, from the Entra app registration overview page | `11111111-2222-3333-4444-555555555555` |
| `CLIENT_ID` | **Yes** | The app registration's *Application (client) ID* | `aaaaaaaa-bbbb-…` |
| `CLIENT_SECRET` | Only for `service_principal` | The app's client secret. Leave **empty** for normal user sign-in | *(empty)* |
| `REDIRECT_URI` | No | Must match the redirect URI registered for the app | `http://localhost` |
| `AUTH_MODE` | No | How you sign in: `interactive` (browser pop-up, recommended), `device_code` (enter a code on another device), `service_principal` (app identity, no RLS models) | `interactive` |
| `POWERBI_API_BASE_URL` | No | Power BI REST endpoint. Change it only for sovereign clouds | `https://api.powerbi.com/v1.0/myorg` |
| `DATABASE_URL` | No | Where comparison history is stored. See below | `sqlite:///data/comparator.db` |
| `PERSIST_TOKEN_CACHE` | No | `true` keeps you signed in between restarts. The cache is encrypted and its key is stored in the OS keyring. `false` keeps sign-in in memory only | `false` |
| `HEADLESS_BROWSER` | No | `false` shows the browser window while reports are extracted, which is useful for troubleshooting | `true` |
| `EMBED_RENDER_TIMEOUT_MS` | No | How long to wait for a report or page to render, in milliseconds. Increase for slow reports | `90000` |
| `DATA_RETENTION_DAYS` | No | Default for the "delete old runs" action | `90` |

### About `DATABASE_URL`
`sqlite:///data/comparator.db` means "store everything in the SQLite file `data/comparator.db`". The tool creates it automatically.
- The path is **relative to the folder you start the app from**, so always start the app from the project folder. Alternatively, use an absolute path with forward slashes: `sqlite:///C:/PBI/comparator.db`.
- If you remove the line, the tool uses `data/comparator.db` inside the project folder.
- If the project lives in OneDrive or Dropbox, the database is synced too. It contains extracted business data, so consider an absolute path outside the synced folder.
- PostgreSQL (not yet tested): `postgresql+psycopg://user:password@host:5432/comparator`, plus `pip install "psycopg[binary]"`.

### Minimal working example
```ini
TENANT_ID=11111111-2222-3333-4444-555555555555
CLIENT_ID=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee
AUTH_MODE=interactive
```
Everything else falls back to sensible defaults.

---

## 4. Try it in 1 minute with mock data

No Power BI account is needed.

1. Run `streamlit run app.py`. Your browser opens at http://localhost:8501.
2. On **Home**, click **Run demo with mock data**.
3. You land on the **Comparison dashboard** with a **FAIL** result. The demo contains planted differences:
   - Electronics, March 2024: **+1,500.00** (value mismatch)
   - Home, July 2024: present in the original, **missing** from the migrated report
   - Accessories, Dec 2024: **additional** record in the migrated report only
   - "Units Trend": identical, so it **PASSES**
   - A custom visual and an R visual: **UNSUPPORTED**

Everything produced from fixtures carries a yellow **MOCK DATA** banner on screen and in every export, so it can't be mistaken for real results.

---

## 5. Compare your real reports, step by step

The sidebar lists the pages in the order you use them.

### Step 1: Power BI connection
1. Open **Power BI connection**. If you see *Configuration incomplete*, fix your `.env` (section 3).
2. Click **Sign in with Microsoft**.
   - `interactive`: a browser window opens. Sign in, then return to the app.
   - `device_code`: a code appears. Open https://microsoft.com/devicelogin, enter the code and sign in.
3. Click **Load / refresh workspaces**.
4. **Original:** choose Workspace A, then the original report.
   **Migrated:** choose Workspace B, then the migrated report.
5. Click **Validate both connections**. Each report should show ✅ with its page count. The table shows the report ID and the semantic-model (dataset) ID separately.

### Step 2: Configuration, first tab (context, tolerance & normalization)
1. **Country context.** Enter the *table* and *column* that hold the country in each report, for example:
   - Original: table `Geography`, column `CountryName`
   - Migrated: table `Geography`, column `Country`
   - Country value: `China`

   These are the model names, as shown in the Power BI field list. If the column header in exported data differs, fill in **Export header**.
2. **Also apply to migrated:** leave this off if the migrated report is China-only by design. Its filters are still captured and checked.
3. **Allow replacing a conflicting country filter:** leave this off. If the original report already filters the country to something else, the tool stops and reports **INCONCLUSIVE** rather than silently overriding it.
4. **Tolerances:** the default is `0` and `0`, meaning exact. Example: an absolute tolerance of `0.01` ignores rounding differences of up to one cent.
5. **Normalization:** these rules only affect *copies* of the data. The originals are kept unchanged.
   - Decimal places: for example `2` to compare at cent precision
   - Text case, percent handling, decimal and thousands separators, day-first dates, blank handling
6. Click **Save configuration**.

### Step 3: Extraction
1. Open **Extraction** and click **Run extraction**. Progress appears live: report loading → page discovery → filter application → visual discovery → visual data extraction.
2. Check the result for each report:
   - **Context** should be ✅ VALIDATED for the original (and ✅ NOT_REQUIRED or VALIDATED for the migrated). Expand *Context evidence* to see the filters before and after.
   - The visual table lists **every** visual with a status:

| Extraction status | Meaning |
|-------------------|---------|
| ✅ SUCCESS | Data exported |
| 🟡 POSSIBLY_TRUNCATED | Hit the 30,000-row export limit, so completeness is unknown |
| ❌ FAILED | Export failed. The exact Power BI error is shown |
| ⛔ UNSUPPORTED | Custom, R or Python visual, which Power BI cannot export through the API |
| ➖ SKIPPED_NON_DATA | Text boxes, shapes, images, buttons, slicers (slicer states are kept as context evidence) |

### Step 4: Configuration, second tab (visual & column mapping)
The tool suggests which migrated visual corresponds to each original visual, using title, type, page, columns, data shape and categories.
1. Review the table. **Confidence** and **Why** explain each suggestion. Only high-confidence, unambiguous matches are pre-approved.
2. Tick **Approve** for correct matches. To fix a wrong match, pick another visual in **Migrated visual**, or choose *— not mapped —*.
3. Untick **Mandatory** for visuals that should not block an overall PASS.
4. Click **Save mapping review**.
5. Optional: select a visual under **Column mapping & keys** to:
   - map columns, for example `MonthName` → `Period` and `SalesAmount` → `Revenue`
   - choose **key columns**, the business dimensions used to match rows (row order is never used)
   - set a per-visual tolerance

   Then click **Approve column mapping for this visual**.
6. Click **Save approved mappings as profile** to reuse them next time. Use **Saved mapping profiles → Apply profile**.

### Step 5: Run the comparison
Back on **Extraction**, click **Run comparison**. The result is saved to history and the dashboard opens.

---

## 6. Reading the results

### Comparison dashboard
- **Overall status** banner with the reasons.
- Counters: total, matched, passed, failed, partial, inconclusive, unsupported and not-mapped visuals; rows compared; missing rows; additional rows; numeric mismatches.
- **Visuals by status** and **Differences by visual** charts, plus a full table.

### What each status means

| Status | Meaning | What to do |
|--------|---------|------------|
| ✅ **PASS** | Everything was extracted, the context was validated, the mapping was approved, and all values are within tolerance | Nothing |
| ❌ **FAIL** | Confirmed differences in values or records | Open **Visual details** to see each difference |
| 🟡 **PARTIAL** | Something was compared, but not everything: truncated export, unmapped columns, duplicate keys, or unconfirmed rows | Check the reasons and complete the mapping or keys |
| ⚠️ **INCONCLUSIVE** | Could not be judged: China context not validated, export failed, or no reliable key | Fix the cause shown, then re-run |
| ⛔ **UNSUPPORTED** | The visual type cannot be exported | Check it manually, or configure a fallback query |
| ➖ **NOT MAPPED** | No approved counterpart | Approve or choose a mapping in Configuration |

The **overall** result is never PASS while any mandatory visual is incomplete, unmapped or unsupported, or while the China context is unvalidated.

### How differences are calculated
- **Absolute difference** = Migrated − Original
- **Percentage difference** = Absolute ÷ Original × 100
- If the original is **0** and the migrated is not, the percentage is shown as *undefined*. It is never infinity or a misleading number.
- If one side is blank and the other is not, the row is a **NULL mismatch** (unless "Treat blanks as zero" is on).
- Values are compared as exact decimals, so there are no floating-point rounding surprises.

### Visual details page
Filter by status, page, mismatch type or title, then pick a visual. The tabs are:

| Tab | Shows |
|-----|-------|
| Mismatches | Each differing value: key, column, original, migrated, absolute and % difference |
| Missing | Records in the original but not in the migrated report |
| Additional | Records in the migrated report only |
| Matching | Records that agree |
| Original (raw) / Migrated (raw) | The data exactly as exported, with its SHA-256 integrity fingerprint |
| Normalized | The derived copies that were compared, plus the rules and column mappings applied |
| Totals & categories | Totals derived by summing rows (exports contain no total rows), plus missing and additional categories |
| Evidence | Visual ID and type, extraction time, completeness, errors, visual-level filters, mapping confidence |

---

## 7. Exports & history

On **Export & history**:
- **Download Excel**: a stakeholder workbook with 11 sheets (Executive Summary, Comparison Configuration, Visual Mapping, Visual Summary, Matching, Mismatching, Missing, Additional Records, Extraction Errors, Unsupported Visuals, Detailed Evidence). Rows are colour-coded: green for match, red for mismatch, yellow for partial or inconclusive, grey for unsupported.
- **Download CSV (zip)**: the same tables as CSV files.
- **Download JSON evidence**: the complete run, including raw exported data and integrity hashes.
- **Download HTML report**: a single self-contained page you can share or print.
- **Previous runs**:
  - *Open run* loads it into the dashboard.
  - *Rerun this configuration* re-runs it.
  - *Delete run* removes it.
- **Compare historical results**: pick two runs to see which visuals changed status.
- **Retention**: delete runs older than N days.

---

## 8. Command reference

| Task | Command |
|------|---------|
| Start the app | `streamlit run app.py` |
| Start on another port | `streamlit run app.py --server.port 8600` |
| Read-only REST API (history and exports) | `uvicorn api.main:app --host 127.0.0.1 --port 8000`, then open http://127.0.0.1:8000/docs |
| Create or upgrade the database | `python -m database.migrations.migrate` |
| Generate sample (mock) outputs | `python -m scripts.generate_sample_output` |
| Re-record the README demo GIF | `python -m scripts.record_demo_gif` (with the app running on port 8599) |
| Run all automated tests | `pytest` |
| Tests with coverage | `pytest --cov=. -q` |
| Live Power BI tests | Set the `LIVE_*` variables (see `tests/live/test_live_powerbi.py`), then `pytest -m live -s` |

---

## 9. Data, backups & clean-up
- **Where data lives:** the database named in `DATABASE_URL`. It holds comparison history, mappings, raw exported visual data and the audit log. It never holds passwords or tokens.
- **Backup:** close the app and copy the `.db` file.
- **Restore:** close the app and put the copy back.
- **Screenshots** (live runs) are saved in `exports/screenshots/`.
- **Logs** are in `logs/app.log`. Tokens and secrets are automatically redacted.
- **Clean-up:** use *Retention* on the History page, or delete individual runs.

---

## 10. Troubleshooting & FAQ

| Problem | Fix |
|---------|-----|
| *Configuration incomplete* | `.env` is missing `TENANT_ID` or `CLIENT_ID`, or is not in the project folder |
| Sign-in window doesn't open | Use `AUTH_MODE=device_code` |
| *Access denied (HTTP 403)* | Ask for Viewer access to the workspace. New permissions can take a while to apply |
| *Not found (HTTP 404)* | The report was deleted or moved, or you can't see it |
| *throttled* | Power BI asked the tool to slow down. Wait a few minutes and retry |
| Report never loads (timeout) | Check your network or proxy, your license, or whether the capacity is paused. Raise `EMBED_RENDER_TIMEOUT_MS`. Set `HEADLESS_BROWSER=false` to watch it |
| Every visual ❌ FAILED | "Export data" is disabled by your admin or in the report settings |
| Context ⚠️ CONFLICT | The original report already filters the country to another value. Fix the report, or explicitly allow replacing |
| Context ⚠️ UNVERIFIED | A filter or slicer on the country field couldn't be read. See *Context evidence* |
| Visual 🟡 POSSIBLY_TRUNCATED | More than 30,000 rows. Compare a more aggregated visual |
| A visual is NOT MAPPED | Approve or choose its counterpart in Configuration → Visual & column mapping |
| Dates don't line up | Turn on *Auto-detect date columns*, or set *Dates are day-first* |

**FAQ**
- *Does it change my reports?* No. Reports open in view mode and are never saved. Filters are applied only inside the tool's private browser session.
- *Does it bypass row-level security?* No. It sees exactly what **you** are allowed to see.
- *Why compare exported data and not the model?* Because the goal is to prove that what users see is the same.
- *Can it compare custom visuals?* Power BI's API cannot export them. They are listed as UNSUPPORTED, never silently skipped.

---

## 11. Glossary

| Term | Meaning |
|------|---------|
| **Original / Migrated report** | The source report (13 countries) and its replacement (China only) |
| **Context** | The filters in effect. For the original report, the China filter the tool applies |
| **Export / exportData** | Power BI's official function that returns the data behind a visual |
| **Summarized data** | What the visual shows (the default). *Underlying* data is the detailed rows, which needs extra permission |
| **Mapping** | Which migrated visual or column corresponds to which original one |
| **Key columns** | The dimension columns used to match rows, such as Category + Month |
| **Normalization** | Making formats comparable (numbers, dates, text) on copies of the data |
| **Tolerance** | How large a difference is still treated as a match |
| **Mock data** | Built-in sample data for demos and tests. Never real Power BI data |
