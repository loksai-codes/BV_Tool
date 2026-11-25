# Technical Validation — Power BI Visual Data Comparator

**Date verified:** 2026-11-25
**Method:** Official Microsoft Learn pages were read on this date. JavaScript SDK claims were also checked against the TypeScript declarations in the published npm packages `powerbi-client@2.25.0` (latest at verification time) and `powerbi-models@2.2.0`.

**Rule (Phase 1 gate):** Anything marked **VERIFIED** below has a source we read. Anything marked **ASSUMPTION** or **UNVERIFIED** must not be relied on until it is live-tested. No live Power BI tenant was available during development, so **no live behaviour has been observed**.

---

## 1. Sources

| # | Source | Page date (updated) |
|---|--------|---------------------|
| S1 | https://learn.microsoft.com/en-us/javascript/api/overview/powerbi/export-data | 2025-10-29 |
| S2 | https://learn.microsoft.com/en-us/power-bi/visuals/power-bi-visualization-export-data | 2026-08-20 |
| S3 | https://learn.microsoft.com/en-us/javascript/api/overview/powerbi/control-report-filters | read 2026-11-25 |
| S4 | https://learn.microsoft.com/en-us/javascript/api/overview/powerbi/get-visuals | read 2026-11-25 |
| S5 | https://learn.microsoft.com/en-us/javascript/api/overview/powerbi/page-navigation | read 2026-11-25 |
| S6 | https://learn.microsoft.com/en-us/javascript/api/overview/powerbi/control-report-slicers | read 2026-11-25 |
| S7 | https://learn.microsoft.com/en-us/javascript/api/overview/powerbi/handle-events | read 2026-11-25 |
| S8 | https://learn.microsoft.com/en-us/rest/api/power-bi/groups/get-groups | read 2026-11-25 |
| S9 | https://learn.microsoft.com/en-us/rest/api/power-bi/reports/get-reports-in-group | read 2026-11-25 |
| S10 | https://learn.microsoft.com/en-us/rest/api/power-bi/reports/get-report-in-group | read 2026-11-25 |
| S11 | https://learn.microsoft.com/en-us/rest/api/power-bi/reports/get-pages-in-group | read 2026-11-25 |
| S12 | https://learn.microsoft.com/en-us/rest/api/power-bi/datasets/execute-queries-in-group | read 2026-11-25 |
| S13 | https://learn.microsoft.com/en-us/rest/api/power-bi/embed-token/generate-token | read 2026-11-25 |
| S14 | https://learn.microsoft.com/en-us/power-bi/developer/embedded/embed-service-principal | 2026-11-20 |
| S15 | https://learn.microsoft.com/en-us/power-bi/developer/embedded/embed-organization-app | 2026-11-20 |
| S16 | https://learn.microsoft.com/en-us/power-bi/developer/embedded/export-to | 2026-11-20 |
| S17 | https://learn.microsoft.com/en-us/fabric/enterprise/powerbi/service-premium-connect-tools (XMLA) | 2026-09-29 |
| S18 | https://learn.microsoft.com/en-us/rest/api/power-bi/ (overview, scopes) | 2025-02-19 |
| S19 | Microsoft sample: github.com/microsoft/PowerBI-Developer-Samples — `Python/Embed for your customers/AppOwnsData/config.py`, `services/aadservice.py` | master, read 2026-11-25 |
| S20 | npm `powerbi-client@2.25.0` `dist/powerbi-client.d.ts`; npm `powerbi-models@2.2.0` `dist/models.d.ts` | published packages |

---

## 2. Visual data export — `visual.exportData()` (VERIFIED)

**Signature (S1, S20):**
```ts
exportData(exportDataType?: ExportDataType, rows?: number): Promise<IExportDataResult>
interface IExportDataResult { data: string; }          // CSV text
enum ExportDataType { Summarized = 0, Underlying = 1 }  // default Summarized
```

**Documented limits and behaviour:**
- "The maximum number of rows you can export is 30,000." (S1). This is the only API row limit documented. The service UI limits for Excel exports (150,000 / 500,000 rows) are in S2, but they are for the UI and S1 does not apply them to the API.
- The result is a CSV **string** (S1). The service CSV export "doesn't contain any subtotal or total rows" (S2). **ASSUMPTION:** the API CSV also omits totals. The code therefore never treats a missing total row as a data mismatch, and it computes totals from exported rows only as derived evidence.
- "If filters are applied to the visualization, the exported data will also be filtered." (S1)
- "Power BI only supports export on visuals that use basic aggregates. Export is not available on visuals using model or report measures." (S1). **Note:** this sentence is surprising, because most real reports use model measures. It must be live-tested against the user's reports. The extractor records the exact error for each visual, so we can see what happens instead of assuming it.
- "Custom and R visuals, aren't supported." (S1, S2). Python visuals are not mentioned. The extractor treats them as unsupported-likely and records any error.
- "Power BI admins can disable the export data feature." (S1). Report designers can also turn off export, or allow summarized only (S2). Admin settings override report settings (S2).
- "Concurrent export data requests from the same session aren't supported. Multiple requests should be run synchronously." (S1). **Design decision:** the JS extractor exports visuals strictly one at a time.
- Underlying export fails if "Show items with no data" is enabled, or if the source is an AS live connection older than 2016 with no unique key (S1). "You might need build permissions to see more data than the visual currently displays (underlying data)." (S2)
- DirectQuery: the maximum export is 16 MB (S1).
- RLS: "If RLS is applied, you can only export data you're authorized to see." (S2). Export respects RLS, and the app never tries to bypass it.
- Embed for your customers: export fails for (a) composite models with DirectQuery to another semantic model when embedding with a service principal, and (b) SSO data sources when the embed token contains `datasourceIdentity` (S1, S2).

**Design consequences:**
1. **Truncation detection:** we request `rows = 30000`. If a visual returns ≥ 30,000 data rows, it is marked `POSSIBLY_TRUNCATED` and its completeness is **not established**. It can never contribute to PASS.
2. The raw CSV string is stored unchanged, with its SHA-256 hash. All parsing and normalization work on derived copies.
3. Every visual gets a recorded outcome: `SUCCESS`, `FAILED`, `UNSUPPORTED`, `SKIPPED_NON_DATA` (shapes, text boxes, images, buttons, slicers recorded as such) or `POSSIBLY_TRUNCATED`. Nothing is dropped silently.

## 3. Pages, visuals and events (VERIFIED)

From S4, S5, S7, S20:
- `report.getPages(): Promise<Page[]>`; `report.getActivePage(): Promise<Page>`; `page.setActive()`.
- `Page` has `name`, `displayName`, `isActive`, `visibility`, `defaultSize`. `page.getVisuals(): Promise<VisualDescriptor[]>`.
- `VisualDescriptor` has `name`, `title`, `type`, `layout: IVisualLayout` (x, y, z, width, height, displayState), `page`.
- "The report must be loaded in order to use the getPages or getVisuals functions." The `loaded` event fires when the report initializes. `rendered` fires when it is fully rendered, including after interactions. `visualRendered` needs `settings.visualRenderedEvents: true`.
- REST: `GET /groups/{groupId}/reports/{reportId}/pages` returns `name`, `displayName`, `order` (S11). This is used for discovery before embedding.

**Design decision:** the extractor waits for `loaded`, then `rendered`, after report load and after each page activation, with a configurable timeout. If the timeout passes, it records `render_timeout` evidence and **continues**, because exports may still work. The evidence goes to the completeness record.

## 4. Filters and context (VERIFIED with gaps)

From S3, S6, S20:
- `getFilters(): Promise<IFilter[]>` and `updateFilters(operation, filters?)` exist on **report, page and visual**. There is **no `setFilters`** in the current SDK. The prompt's reference to `report.setFilters()` is outdated, and `updateFilters` is used instead.
- `FiltersOperations { RemoveAll=0, ReplaceAll=1, Add=2, Replace=3 }`. `Replace` "replaces an existing filter with a given filter only if both filters apply to the same data field", otherwise it adds.
- `FilterType { Advanced=0, Basic=1, Unknown=2, IncludeExclude=3, RelativeDate=4, TopN=5, Tuple=6, RelativeTime=7, Identity=8, Hierarchy=9, HierarchyIdentity=10 }`. **Doc discrepancy:** S3 has an example using `models.FilterType.BasicFilter`, which does **not** exist in `powerbi-models@2.2.0`. The code uses the numeric value `1` (Basic).
- Basic filter shape: `{ $schema: "http://powerbi.com/product/schema#basic", target: {table, column}, operator: "In"|"NotIn"|"All", values: [...], filterType: 1 }`.
- "Filters on different level are independent, and updating filters on one level, will not change another." (S3)
- Slicers: `visual.getSlicerState()` / `setSlicerState()`. "List Slicers visual type are not yet supported via getSlicerState or setSlicerState APIs." Sync-slicer configuration is recognized (S6).
- Bookmarks: `report.bookmarksManager.capture()` exists (S20). It is used **only** to capture state as evidence and is never applied.
- **Gap:** the docs do not say whether `report.getFilters()` reflects slicer selections, or whether it exposes every effective filter (for example, hidden filters set in Desktop, cross-filtering from visual interactions, or RLS). **We cannot guarantee perfect context equivalence**, and the UI and reports say so.

**Design decision: China context algorithm**
1. Capture report, page and visual filters and slicer states before any change (evidence).
2. Look for an existing report-level filter on the configured `(table, column)`:
   - If there is none, add a Basic `In [China]` filter with `FiltersOperations.Add`. Unrelated filters are preserved.
   - If one exists with `In` that already equals `[China]`, there is nothing to do.
   - If one exists with a different value, or is non-Basic, this is a **conflict**. By default the app does not overwrite it. The conflict is recorded and the context becomes `INCONCLUSIVE`. The user can explicitly allow the app to replace that one filter with `FiltersOperations.Replace`, which only touches the same field.
3. Re-read the filters and check that exactly the expected Basic filter is present. Check page-level filters and slicers on the same field for contradicting values. Any contradiction makes the context `INVALID`.
4. **Data-level validation:** if an exported visual contains the country column, every non-blank value must equal the configured country. Otherwise that visual is `INCONCLUSIVE`.
5. The migrated report is **not filtered by default** (it is China-only by design). Its filters are captured, and an optional verification filter can be applied the same way.
6. All filter changes happen only inside the embedded session in the browser. `updateFilters` in view mode does **not** save the report. The app never calls `report.save()`, never opens edit mode, and the JS extractor refuses to run if `viewMode` is not View.

## 5. Authentication (VERIFIED)

- **Scope:** `https://analysis.windows.net/powerbi/api/.default`. **Authority:** `https://login.microsoftonline.com/organizations`, or `https://login.microsoftonline.com/{tenantId}` for a service principal (S19, Microsoft's official Python sample). The Learn pages S14, S15 and S18 do not print these strings. They come from S19.
- Service principal: `msal.ConfidentialClientApplication(...).acquire_token_for_client(scopes=[.default])` (S19). Tenant settings "Embed content in apps" and "Allow service principals to use Power BI APIs" must be on. The SP must be a workspace **Member or Admin** (S14). That is more than read-only access, but it is the documented requirement. "My Workspace" is not supported. Microsoft recommends **not** adding API permissions to the SP app registration (S14).
- Delegated (user) auth: `msal.PublicClientApplication` with interactive or device-code flows. The sample uses the username/password (ROPC) flow, which **we deliberately do not implement** because it is insecure and incompatible with MFA. Delegated scopes are added in Entra under "Power BI Service" → Delegated permissions (S18). The least-privilege set for this app is `Workspace.Read.All`, `Report.Read.All`, `Dataset.Read.All` (the scopes listed on S8, S9, S12).
- Token storage: the MSAL cache is in memory by default. Optional persistence is encrypted (Fernet) with a key held in the OS keyring. Tokens are never written to the database or logs.

## 6. Embedding (VERIFIED)

| Mode | Token | Identity / RLS | Licensing | Used for |
|------|-------|----------------|-----------|----------|
| **Embed for your organization** (user owns data) — **default** | `TokenType.Aad` (0) with the user's Entra token | Signed-in user; RLS applies naturally | Pro or PPU per S15; not on A SKUs | Live extraction under the user's own permissions |
| Embed for your customers (app owns data) | `TokenType.Embed` (1) from `POST /GenerateToken` | SP; RLS requires `identities[]` | Capacity needed for production (S14) | Optional; see risks below |

- `POST https://api.powerbi.com/v1.0/myorg/GenerateToken` is "only relevant to the embed for your customers scenario" (S13). The app only requests `reports:[{id, allowEdit:false}]` and `datasets:[{id, xmlaPermissions:"Off"}]`, and never `targetWorkspaces` (which needs Content.Create).
- **Risk:** with a service principal, any RLS model needs an effective identity, which would mean choosing whose data the SP sees. To avoid impersonation, the app **does not set `identities[]`**. If the model requires an identity, token generation fails, and we report that rather than impersonating anyone. User-owns-data is the recommended mode.

## 7. REST discovery endpoints (VERIFIED)

| Purpose | Request | Scope |
|---------|---------|-------|
| Workspaces | `GET /v1.0/myorg/groups?$top&$skip&$filter` → `id, name, isReadOnly, isOnDedicatedCapacity, capacityId` | Workspace.Read.All |
| Reports | `GET /groups/{groupId}/reports` → `id, name, datasetId, webUrl, embedUrl, reportType, format` | Report.Read.All |
| One report | `GET /groups/{groupId}/reports/{reportId}` | Report.Read.All |
| Pages | `GET /groups/{groupId}/reports/{reportId}/pages` → `name, displayName, order` | Report.Read.All |

- `datasetWorkspaceId` is **not** documented on the report object (S9). The dataset workspace is therefore not assumed, and the report and dataset IDs are stored separately.
- Throttling: no Retry-After guidance appears on these pages. The client honours a `Retry-After` header on 429 or 503 if present (standard HTTP), otherwise it uses exponential backoff, and it only retries idempotent GETs plus the read-only executeQueries call.
- "User permissions for workspaces take time to get updated" (S8). This is surfaced in error messages.

## 8. Fallback extraction

### 8.1 Execute Queries REST API (VERIFIED)
- `POST /groups/{groupId}/datasets/{datasetId}/executeQueries`, body `{"queries":[{"query":"<DAX>"}],"serializerSettings":{"includeNulls":true}}`.
- Needs the tenant setting "Dataset Execute Queries REST API", plus dataset Read **and Build** permission. Scope `Dataset.Read.All`.
- Limits: one query per call; one table per query; 100,000 rows or 1,000,000 values; 15 MB (rows past that are silently dropped); 120 requests per minute per user.
- Not supported: AAS-hosted or AAS live-connection datasets. **Service principals are not supported for RLS or SSO datasets.** Only DAX is supported (no MDX, DMV or INFO).
- **Design:** the fallback only runs a user-supplied, visual-equivalent DAX query, or one built from user-declared columns with a `TREATAS` country filter. Results are labelled `source_method = FALLBACK_QUERY`. Because equivalence to the visual cannot be proven automatically, a fallback-based comparison is capped at **PARTIAL** unless the user explicitly marks the query as equivalent, and even then the evidence is labelled as reconstructed. `impersonatedUserName` is **never sent**, because sending it would be impersonation.
- **Caveat:** the original report uses a live connection. Its dataset may sit in another workspace. Execute Queries targets the dataset's own workspace, which the user must supply if it differs.

### 8.2 XMLA read-only (VERIFIED requirements, NOT implemented as a live client)
- Needs Premium, PPU, Embedded or Fabric capacity. Read-only is on by default. Build permission is required. Connection string format: `powerbi://api.powerbi.com/v1.0/myorg/<URI-encoded workspace name>`. Service principals do not work with RLS or OLS (S17).
- There is no supported pure-Python ADOMD client. The common route (`pyadomd`) needs the .NET ADOMD.NET client library to be installed. The app builds and validates the connection string, and reports `XMLA_UNAVAILABLE` with setup instructions. It does not ship an unverified client.

### 8.3 Export to file (VERIFIED, evidence only)
- REST exportToFile produces PDF, PPTX or PNG. It needs Premium, Embedded or Fabric capacity (not PPU). The limits are 500 concurrent requests per capacity, 5 pages processed concurrently, 250 MB per file, and links valid for 24 hours. This produces rendered images, **not data**. It is documented as an evidence option and is not used for reconciliation. Screenshots come from Playwright instead.

## 9. Licensing and tenant requirements (summary)

- The user needs a Power BI Pro or PPU license (embed for org), or the content must be on capacity. Free software in this app does not remove any Microsoft licensing requirement.
- Tenant settings that may be needed: "Export data" settings in the tenant and in each report; "Embed content in apps" (SP); "Allow service principals to use Power BI APIs" (SP); "Dataset Execute Queries REST API" (fallback); XMLA settings (fallback).
- Workspace role: Viewer or above for the user (read-only usage). Build permission on the dataset is only needed for underlying-data export or fallback queries.

## 10. Unsupported or unverifiable scenarios

- Custom (AppSource) visuals, R visuals and (likely) Python visuals cannot be exported through the API. They are recorded as `UNSUPPORTED` with the reason.
- Visuals that use model measures may fail to export, per S1. **Unverified in practice.**
- Effective filter context from cross-highlighting, hidden Desktop filters and RLS is not fully observable through the API.
- The 30,000-row limit means large table visuals cannot be confirmed complete.
- CSV exports may omit totals and subtotals, so grand totals are compared only when the visual itself exports them (cards, or explicit total rows).
- Matrix "current layout" export is a UI feature (S2) and is not available through `exportData`.

## 11. Assumptions to verify live

1. Running the embed host on `http://127.0.0.1:<port>` with a user Entra token loads the report (embed for org). The JS SDK communicates by postMessage, and no origin allow-listing is documented for AAD-token embedding.
2. The export CSV format (header row, number formatting, culture) for the target reports.
3. Whether `exportData` succeeds on the target visuals, given that they use model measures (see §2 note).
4. Whether `report.getFilters()` returns the pre-existing country filter, if the original report already has one.
