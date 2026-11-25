# Entra ID, Power BI Permissions & Tenant Setup

Everything here is grounded in the sources listed in `TECHNICAL_VALIDATION.md` (verified 2026-11-25).
Free/open-source software in this app does **not** remove any Microsoft licensing, capacity, tenant-setting or permission requirement.

## 1. Choose an authentication flow

| Flow | `AUTH_MODE` | Identity used for extraction | When to use |
|------|-------------|------------------------------|-------------|
| Interactive (system browser) | `interactive` | Signed-in user (RLS applies to them) | **Recommended.** Local desktop use |
| Device code | `device_code` | Signed-in user | Remote/headless host; Streamlit shows the code |
| Service principal | `service_principal` | App identity + view-only embed token | Automation; **not** for RLS models (no impersonation is performed) |

Username/password (ROPC) is deliberately not supported.

## 2. Register the Entra application

1. In the Entra admin center go to **App registrations → New registration**.
2. Give it a name such as `PBI Visual Comparator`. Choose **single tenant**.
3. For delegated flows, add the **Mobile and desktop applications** platform with redirect URI `http://localhost`. Enable **Allow public client flows** (needed for device code).
4. Under **API permissions → Add a permission → Power BI Service → Delegated permissions**, add these least-privilege scopes:
   - `Workspace.Read.All` (list workspaces)
   - `Report.Read.All` (reports, pages, embedding)
   - `Dataset.Read.All` (only needed for the Execute Queries fallback)
   Grant admin consent if your tenant requires it.
5. Copy the **Directory (tenant) ID** and **Application (client) ID** into `.env` as `TENANT_ID` and `CLIENT_ID`.

The app requests the scope `https://analysis.windows.net/powerbi/api/.default`, which resolves to the consented permissions. The authority is `https://login.microsoftonline.com/<TENANT_ID>`.

### Service principal (optional)
- Create a client secret. A certificate is preferred, per Microsoft's guidance. Put the secret only in `.env` or your secret store as `CLIENT_SECRET`, never in source control.
- Microsoft recommends **not** adding any API permissions to a service-principal app. They are never used and can cause errors.
- Tenant admin: enable **Developer settings → Embed content in apps** and **Allow service principals to use Power BI APIs**. Scope both to a security group that contains the app.
- Add the service principal (or its group) to **both workspaces** as **Member or Admin**. That is the documented minimum for service-principal embedding. "My Workspace" is not supported.
- Limitation: service principals cannot be used with RLS or SSO semantic models for Execute Queries or XMLA. This app never sends an effective identity, so an embed token for an RLS model fails, and the failure is reported rather than bypassed.

## 3. Workspace and report permissions (delegated user)
- **Viewer** (or higher) on Workspace A and Workspace B is enough for discovery, embedding and summarized `exportData`.
- **Build permission** on the semantic model is needed only for:
  - Underlying-data export mode, if allowed
  - The Execute Queries fallback (dataset Read + Build)
  - The XMLA fallback
- Licensing: embedding for your organization needs a Pro or PPU license, or the content must be on a capacity. It is not supported on A-SKU capacities.

## 4. Tenant and report settings that affect extraction
| Setting | Where | Effect |
|---------|-------|--------|
| Export data (summarized / underlying) | Admin portal → Export and sharing | If disabled, `exportData` fails and every visual is recorded as FAILED with the error |
| Report-level "Export data" option | Report settings (Desktop/service) | The designer can block or limit export. Admin settings override it |
| Dataset Execute Queries REST API | Admin portal → Integration settings | Needed only for the fallback |
| XMLA endpoint (read) | Capacity / PPU workload settings | Needed only for the XMLA fallback (Premium/PPU/Fabric) |
| Allow service principals to use Power BI APIs / Embed content in apps | Developer settings | Service-principal mode only |

## 5. Country (China) context configuration
- Configure the **table and column** names for each report on the Configuration page. They are never hardcoded, and the original and migrated field names may differ (for example `Geography[CountryName]` and `Geography[Country]`).
- If the exported CSV header differs from the column name, set "export header" so the data-level check can find the column.
- If the original report already has a different filter on the country field, it is **not overwritten** unless you tick "Allow replacing a conflicting country filter". Until then the result is INCONCLUSIVE.

## 6. Live validation checklist (run once credentials are available)
1. `copy .env.example .env` and fill in `TENANT_ID` and `CLIENT_ID` (plus `AUTH_MODE`).
2. `streamlit run app.py`, open **Power BI connection**, sign in, and select both workspaces and reports. Click **Validate both connections**.
3. On **Configuration**, set the country table and column for both reports.
4. On **Extraction**, click **Run extraction**. Check the context status (VALIDATED is expected for the original) and the per-visual export statuses.
5. Review the mappings, then run the comparison.
6. Optionally run the automated live tests: `pytest -m live -s` with the `LIVE_*` variables (see `tests/live/test_live_powerbi.py`).
7. Record the results in `docs/IMPLEMENTATION_STATUS.md` under "Live verification".
