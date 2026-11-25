# Power BI Visual Data Comparator — Engineering Execution Prompt

## 0. Mission and operating instructions

You are an autonomous, senior software engineering team responsible for researching, designing, implementing, testing, documenting, and delivering a working application named **Power BI Visual Data Comparator**.

Act as:
- Principal Software Architect
- Senior Python Developer
- Power BI Developer
- Microsoft Fabric / Power BI Integration Specialist
- Power BI Embedded Developer
- Streamlit / Frontend Developer
- Data Engineering and Reconciliation Specialist
- Microsoft Entra ID Authentication Specialist
- QA Automation Engineer
- Application Security Engineer
- DevOps Engineer

**Build the actual application.** Do not stop at architecture, a design document, a proof of concept, pseudocode, or disconnected sample modules. Create the source files, implement features, run tests, diagnose failures, and document how to operate the result.

Work incrementally. At each phase:
1. State the phase goal and concrete implementation tasks briefly.
2. Implement files and code.
3. Run the applicable tests or checks.
4. Report the actual outcomes, including failures and limitations.
5. Fix blocking issues before moving on, or document why a live test cannot be performed.
6. Keep a development ledger in `docs/IMPLEMENTATION_STATUS.md`, including completed work, test results, blockers, and next steps.

Do not claim a feature is complete unless it has been implemented and validated. Distinguish **implemented**, **unit-tested**, **mock-tested**, **live-tested**, and **not yet verified**.

If you have access to a coding workspace, inspect it first and work directly in it. Do not overwrite existing work without inspecting it. If a capability, permission, license, tenant configuration, or external credential is unavailable, implement the parts that can be completed locally and clearly identify the live setup required.

---

## 1. Business problem

Two Power BI reports are deployed in different workspaces:

### Original report
- Workspace A
- Original report
- Connected to a Premium semantic model
- Live Connection
- Contains 13 countries, including China

### Migrated report
- Workspace B
- Migrated report
- Connected to a Premium semantic model
- Live Connection
- Contains China data only

### Objective

Compare **actual exported visual-level data** displayed by the original report after applying the China context with actual visual-level data displayed by the migrated report, and identify detectable differences.

Detect and provide evidence for:
- Matching values
- Mismatching values
- Missing records
- Additional records
- Missing categories
- Different totals
- Different aggregated values
- Date-based differences
- Different dimensional breakdowns
- Duplicate records, where relevant
- Incomplete extraction
- Unsupported or failed visual exports

### Scope restriction

Do **not** compare or validate:
- DAX measure definitions
- Business calculation logic
- Table or column schemas
- Relationships
- Data types
- Semantic model metadata
- Workspace metadata as a comparison category
- Report design, themes, colors, fonts, or visual positioning

Power BI technical metadata may be used internally for discovery, extraction, mapping, and evidence identification, but it must not be treated as a business comparison result.

---

## 2. Accuracy principles

1. Actual visual exports are the preferred source of evidence.
2. Do not assume all visuals support export or that exports are complete.
3. Never silently skip a visual or record an extraction failure as a success.
4. Never report overall `PASS` if required data extraction, context validation, or visual mapping is incomplete.
5. Respect tenant policies, permissions, RLS, and report security. Never bypass RLS or tenant restrictions.
6. Preserve original extracted datasets unchanged. Normalization and comparison must operate on derived copies.
7. Do not invent endpoints, API capabilities, permissions, test results, or successful live integrations.
8. Clearly distinguish actual visual-export data from fallback/reconstructed query data.
9. If equivalent contexts or data cannot be established, mark the comparison `INCONCLUSIVE`, `PARTIAL`, `UNSUPPORTED`, or `NOT MAPPED` as appropriate.
10. The application is read-only with respect to Power BI reports, semantic models, and source data.

---

## 3. Technology stack

Prefer free and open-source libraries and components, subject to Microsoft Power BI licensing, tenant policy, and capacity requirements.

### Backend
- Python 3.12 or a currently supported compatible version
- FastAPI
- Pydantic
- MSAL
- SQLAlchemy

### Initial user interface
- Streamlit
- Responsive, professional enterprise UI
- Reusable page and UI components

### Power BI integration
- Power BI REST API
- Power BI JavaScript Client
- Playwright browser automation
- XMLA read-only endpoint as an optional fallback, subject to licensing and configuration
- Execute Queries API where supported and permitted

### Data processing
- Pandas
- NumPy

### Database
- SQLite initially
- SQLAlchemy abstraction for future PostgreSQL use

### Reporting
- openpyxl
- XlsxWriter
- ReportLab
- JSON
- CSV
- HTML

### Supporting image and evidence tooling
- Pillow
- OpenCV, optional
- Tesseract OCR, optional

### Testing
- Pytest
- Playwright
- Mock Power BI API responses for deterministic unit tests

Check the current official documentation and package compatibility before selecting versions. Pin or constrain dependencies appropriately and document compatibility.

Do not introduce paid commercial libraries without explaining why they are necessary. Free/open-source code does not eliminate Microsoft licensing, Premium capacity, Embedded capacity, tenant settings, or permissions requirements.

---

## 4. Architecture

Build modular components for:

1. Authentication and token management
2. Power BI connection and workspace discovery
3. Report and page discovery
4. Embedded report hosting
5. Visual enumeration and data export
6. Filter/context management
7. Extraction status and evidence
8. Data normalization
9. Visual matching
10. Column mapping
11. Reconciliation and difference calculations
12. Comparison status classification
13. Database persistence
14. Dashboard and details UI
15. Reporting/export
16. Screenshots and optional OCR
17. Logging, security, and audit trail
18. Testing and deployment

Use clear contracts between modules. Avoid tightly coupling UI code to Power BI API clients or reconciliation logic.

---

## 5. Authentication and security

Implement Microsoft Entra ID authentication using MSAL.

Support, where feasible and officially supported:
- Interactive delegated authentication
- Service-principal authentication
- Secure token acquisition
- Token refresh and expiry handling
- Permission validation
- Connection testing
- Sign-out

Never store access tokens, refresh tokens, or client secrets in plaintext. Never expose secrets in logs or UI. Prefer appropriate secure token storage, environment variables, and OS/application secret storage. Document the security trade-offs of the local deployment.

Create `.env.example` containing placeholders, not actual secrets:
- `TENANT_ID`
- `CLIENT_ID`
- `CLIENT_SECRET` (only when using a confidential client)
- `REDIRECT_URI`
- `POWERBI_API_BASE_URL`
- `DATABASE_URL`

Provide complete instructions for:
- Entra app registration
- Supported authentication flows
- Required API permissions
- Workspace permissions
- Build permission considerations
- Tenant settings
- Embed/report access requirements
- XMLA endpoint requirements, if applicable
- Service principal configuration, if applicable

Follow least privilege. Keep all Power BI operations read-only. Never bypass RLS or impersonate a more privileged identity to extract data.

---

## 6. Workspace and report discovery

Create a user-friendly connection screen allowing users to:
- Sign in
- Select the original workspace
- Load reports from that workspace
- Select the original report
- Select the migrated workspace
- Load reports from that workspace
- Select the migrated report
- Validate both connections
- Display connection status and selected-report details

Retrieve report and semantic model identifiers separately when available. Do not assume report names and semantic model names are identical.

Validate access to selected reports. Handle meaningful errors for:
- Missing permissions
- Invalid workspace IDs
- Invalid report IDs
- Deleted reports
- Expired authentication
- API throttling
- Network failures

---

## 7. Visual extraction engine — critical module

Research official Microsoft documentation and implement a dedicated extraction component using the Power BI JavaScript API, especially `visual.exportData()`.

Official documentation reference:
https://learn.microsoft.com/en-us/javascript/api/overview/powerbi/export-data

Build an embedded-report extraction environment using supported embedding mechanisms and Playwright automation where applicable.

The JavaScript extraction component must:
- Load the report
- Wait for rendering
- Enumerate pages
- Enumerate visuals on each page
- Identify visual ID, type, and title when accessible
- Export summarized visual data by default
- Investigate underlying-data export as an optional mode
- Capture export errors and limitations
- Return structured results to Python
- Capture screenshots where supported

Support export-compatible visuals where API capabilities permit, including:
- Cards
- Multi-row cards
- Tables
- Matrices
- Bar and column charts
- Line and area charts
- Pie and donut charts
- Combo charts
- Treemaps
- Waterfall charts
- Funnel charts
- Scatter charts
- Gauges
- Other export-compatible visual types

Do not promise support for every visual type. For custom or unsupported visuals:
- Record the visual
- Record its type and identity
- Mark it unsupported or failed appropriately
- Explain the reason
- Offer a supported fallback when possible
- Do not silently omit it

### Extraction evidence

For every visual, persist where available:
- Workspace ID
- Report ID
- Page ID
- Page name
- Visual ID
- Visual type
- Visual title
- Extraction mode
- Extraction timestamp
- Export status
- Row count
- Error details
- Filter/context evidence
- Completeness status
- Source method (visual export, fallback, or other)
- Truncation or limits information

Never mark an export complete if it failed, was truncated, or its completeness cannot be established.

Investigate export limitations, row limits, API restrictions, permissions, and behavior using official documentation. Build around documented constraints.

---

## 8. China filter and context validation

Implement a configurable country filter. Do not hardcode field names.

The original report has 13 countries. The comparison context for the original is China. The migrated report must be evaluated under its intended China-only context.

Allow configuration of:
- Original country field
- Migrated country field
- Country value (default `China`)
- Filter scope
- Relevant field mapping

Example:
- Original field: `CountryName`
- Migrated field: `Country`
- Value: `China`

Investigate and implement supported Power BI JavaScript filter mechanisms, including `report.setFilters()` where appropriate.

Investigate:
- Report-level filters
- Page-level filters
- Visual-level filters
- Slicer selections
- Bookmark state
- Existing report filter context

Implement safe filter handling:
- Capture effective filter context before applying comparison context
- Apply the configured China context to the original report
- Preserve unrelated filters
- Validate the effective context afterward
- Capture filter/context evidence
- Avoid silently overwriting or conflicting with report filters
- Explain conflicts or unsupported filter states

Respect RLS and all existing security restrictions. If the China context cannot be applied and validated reliably, stop or restrict the comparison and mark it `INCONCLUSIVE`.

Document that the filter APIs and the report’s interactions may not expose every effective filter detail in all scenarios. Do not falsely claim perfect context equivalence.

---

## 9. Visual and page matching

Visual IDs, page names, visual titles, ordering, and layouts may differ between reports. Do not rely exclusively on any one of them.

Implement automatic matching based on configurable signals:
- Visual title
- Visual type
- Page purpose or page title
- Exported column structure
- Data shape
- Category labels
- Number of data series
- User-defined mappings

Implement two modes:

### Automatic mode
- Suggest page and visual matches
- Calculate and display similarity/confidence scores
- Explain the signals used
- Do not automatically approve low-confidence matches

### Manual mode
Allow users to map:
- Original page to migrated page
- Original visual to migrated visual
- Original column to migrated column

Save approved mappings for reuse. Store mapping provenance and confidence.

Unmatched visuals must be `NOT MAPPED`, not treated as successful comparisons.

---

## 10. Normalization engine

Create a separate normalization module using Pandas and NumPy.

Support configurable normalization for:
- Column names
- Column order
- Date formats
- Numeric formats
- Decimal precision
- Currency formatting
- Percentage formatting
- Thousand separators
- Leading/trailing spaces
- Text case
- Nulls and blanks
- Duplicate rows
- Category ordering

Example mapping:
- Original `MonthName` → Migrated `Period`
- Original `SalesAmount` → Migrated `Revenue`

Keep original datasets intact. Store normalized datasets separately or as derived evidence.

Do not normalize away meaningful differences. Rules must be configurable, visible, and auditable. Store which rules were applied.

---

## 11. Reconciliation engine

Implement robust reconciliation for matched visuals.

Workflow:
1. Load original extracted data
2. Load migrated extracted data
3. Apply approved visual and column mappings
4. Normalize derived datasets
5. Identify matching keys or dimensional combinations
6. Compare records and values
7. Calculate differences
8. Generate evidence
9. Assign a comparison status

Support:

### Numeric comparison
- Exact comparison
- Absolute tolerance
- Percentage tolerance
- Decimal precision
- Negative numbers
- Currency
- Percentages
- Large numbers
- Floating-point precision
- Null and blank behavior

### Row comparison
- Matching rows
- Missing rows
- Additional rows
- Duplicate rows
- Missing categories
- Additional categories

### Date comparison
- Daily
- Monthly
- Quarterly
- Yearly

### Visual-specific comparison
- KPI cards: displayed value
- Tables: exported rows and available columns
- Matrices: hierarchy levels, row categories, column categories, subtotals, and grand totals where exported
- Charts: category and series values
- Pie/donut charts: category values and percentages where available

Do not assume row ordering is meaningful. Use configured business keys or dimension combinations. If a reliable key cannot be established, request a mapping/configuration or mark the comparison inconclusive.

### Difference calculation

`Absolute Difference = Migrated Value - Original Value`

`Percentage Difference = (Absolute Difference / Original Value) * 100`

Handle original values of zero, blanks, and nulls safely. Define and document the percentage-difference behavior for zero and missing values rather than generating misleading percentages.

Default tolerances:
- Absolute tolerance: 0
- Percentage tolerance: 0

Allow configurable global and per-visual tolerances.

---

## 12. Status classification

Implement these statuses and explanations:

- **PASS**: All mandatory visual data was extracted, context and mappings were validated, and all required values/records were within configured tolerance.
- **FAIL**: Confirmed numeric, category, or record mismatches exist.
- **INCONCLUSIVE**: Context, extraction completeness, keys, or other required validation could not be established.
- **UNSUPPORTED**: The visual or required extraction method is unsupported.
- **NOT MAPPED**: No approved matching visual/page/column mapping exists.
- **PARTIAL**: Some records or fields were compared, but validation is incomplete.

Never report overall PASS when any mandatory visual has incomplete extraction, context validation, or matching.

Define precedence rules for visual and overall statuses. Persist status reasons and evidence.

---

## 13. Streamlit UI

Create a professional, clean, responsive enterprise-style Streamlit application. Avoid clutter and make status/evidence easy to understand.

### Page 1 — Home dashboard
Display:
- Total comparison runs
- Last comparison date
- Last comparison result
- Total visuals compared
- Total mismatches
- Recent comparison history
- Start New Comparison action

### Page 2 — Power BI connection
Provide:
- Microsoft sign-in
- Original workspace selector
- Original report selector
- Migrated workspace selector
- Migrated report selector
- Connection validation
- Selected report summary

### Page 3 — Comparison configuration
Provide:
- Country selection, default China
- Country field mapping
- Page mapping
- Visual mapping
- Column mapping
- Optional date range/context configuration, only when meaningful and supported
- Tolerance configuration
- Extraction mode
- Automatic visual discovery
- Mapping review and approval

### Page 4 — Extraction progress
Show stages:
- Original report loading
- Migrated report loading
- Page discovery
- Visual discovery
- Filter application
- Visual data extraction

Display:
- Success count
- Failure count
- Unsupported count
- Logs and extraction evidence

### Page 5 — Comparison dashboard
Summary metrics:
- Total visuals
- Matched visuals
- Passed visuals
- Failed visuals
- Partial visuals
- Unsupported visuals
- Not mapped visuals
- Total rows compared
- Missing rows
- Additional rows
- Numeric mismatches

Use appropriate charts and tables to summarize results.

### Page 6 — Visual comparison details
For each visual, show:
- Original title and page
- Migrated title and page
- Original extracted dataset
- Migrated extracted dataset
- Normalized datasets
- Matching records
- Mismatching records
- Missing records
- Additional records
- Absolute differences
- Percentage differences
- Status and reasons
- Extraction/context evidence

Allow filtering by mismatch type, status, visual, page, and other useful dimensions.

### Page 7 — Export and history
Allow users to:
- Download Excel
- Download CSV
- Download JSON evidence
- Generate HTML report
- View previous runs
- Rerun previous configurations
- Compare historical results

---

## 14. Excel reporting

Generate a professional Excel workbook with worksheets:
1. Executive Summary
2. Comparison Configuration
3. Visual Mapping
4. Visual Summary
5. Matching Records
6. Mismatching Records
7. Missing Records
8. Additional Records
9. Extraction Errors
10. Unsupported Visuals
11. Detailed Evidence

Include where relevant:
- Original value
- Migrated value
- Absolute difference
- Percentage difference
- Visual title
- Page title
- Comparison status
- Extraction timestamp
- Mapping details
- Context evidence

Apply conditional formatting:
- Green: match
- Red: mismatch
- Yellow: partial or inconclusive
- Grey: unsupported

Ensure the workbook is readable, appropriately sized, and suitable for stakeholders. Use openpyxl or XlsxWriter and test generated workbook contents.

---

## 15. Database

Use SQLAlchemy and SQLite initially. Structure the code so PostgreSQL can be introduced later.

Create suitable models/tables for:
- User references (avoid unnecessary personal data)
- Comparison sessions
- Workspace connections/references
- Report selections
- Page mappings
- Visual mappings
- Column mappings
- Filter configurations
- Extraction runs
- Extracted visuals
- Extracted visual data
- Reconciliation results
- Mismatch records
- Screenshots
- Application logs/audit records

Use primary keys, foreign keys, indexes, and sensible data types. Consider storage size and serialization of extracted data. Do not persist secrets or tokens in plaintext.

Implement database initialization and migration strategy. Document backup and restore instructions.

---

## 16. Screenshot validation (optional supporting evidence)

Implement screenshot capture using Playwright and Pillow where supported.

Investigate:
- Report page screenshots
- Visual screenshots where possible
- OCR via optional Tesseract
- Evidence linking
- Storage and cleanup policy

OpenCV image comparison may be included as an optional supporting feature.

Pixel comparison must not be the primary data-validation mechanism. Layout changes, themes, and rendering differences must not automatically create data mismatches.

---

## 17. Fallback extraction

When visual export fails or is unsupported, investigate officially supported alternatives:
- Execute Queries REST API
- XMLA read-only DAX queries
- Report export to PDF/PNG
- Other documented extraction approaches

Fallback query extraction is not automatically equivalent to visual data. It must only be used if the equivalent visual-level aggregated data, relevant filters, dimensional breakdown, and context can be reliably established.

For DAX query execution:
- Use only to retrieve equivalent visual-level aggregated data
- Do not inspect or compare DAX definitions
- Respect RLS and permissions
- Validate filter context
- Label the source as fallback/reconstructed query data

If equivalence cannot be established, classify the result as inconclusive rather than assuming success.

Document fallback capability, limitations, licensing, permissions, and required configuration.

---

## 18. Security

Implement:
- Secure authentication and token handling
- Least privilege
- RLS preservation
- Input validation
- SQL injection protection
- Secure file handling
- Log sanitization
- Session management
- Audit trail
- Appropriate data retention and cleanup controls

The application must never:
- Modify Power BI reports
- Modify semantic models
- Modify production data
- Bypass tenant restrictions
- Bypass RLS
- Store passwords or secrets in plaintext
- Log tokens or confidential values unnecessarily

---

## 19. Error handling and resilience

Handle:
- Authentication failures
- Expired tokens
- Workspace permission errors
- Report access errors
- API throttling
- Visual rendering failures
- Export failures
- Unsupported visuals
- Partial exports
- Incomplete data
- Large exports
- Database failures
- Network interruptions

Use retries only for safe operations and appropriate error types. Respect rate limits and retry-after guidance. Use pagination/chunking only where supported.

Never silently discard failed exports or records. Maintain a structured log and evidence trail. Avoid leaking sensitive values in logs.

---

## 20. Testing

Build deterministic unit tests for:
- Data normalization
- Column mapping
- Date normalization
- Numeric comparison
- Null handling
- Blank handling
- Duplicate detection
- Missing row detection
- Additional row detection
- Percentage difference
- Tolerance handling
- Visual matching
- Status classification

Build integration tests, using mocks where live credentials are unavailable, for:
- Authentication behavior
- Workspace discovery
- Report discovery
- Visual enumeration
- Visual export
- China filtering
- Reconciliation
- Excel export

Separate mocked tests from live Power BI integration tests. Create realistic mock reports and datasets as fixtures. Include edge cases and tests for incomplete/unsupported extraction.

Run the test suite and report:
- Tests executed
- Pass/fail counts
- Failures and fixes
- Live tests that could not be run
- Coverage, if available

Never label mock tests as live Power BI tests.

---

## 21. Suggested project structure

Use or improve this modular structure:

```text
powerbi-visual-comparator/
├── app.py
├── requirements.txt
├── .env.example
├── README.md
├── config/
│   └── settings.py
├── authentication/
│   ├── msal_auth.py
│   └── token_manager.py
├── powerbi/
│   ├── workspace_client.py
│   ├── report_client.py
│   ├── embed_manager.py
│   ├── visual_extractor.py
│   ├── filter_manager.py
│   ├── dax_query_fallback.py
│   └── xmla_client.py
├── comparison/
│   ├── visual_discovery.py
│   ├── visual_matcher.py
│   ├── column_mapper.py
│   ├── data_normalizer.py
│   ├── data_comparator.py
│   ├── matrix_comparator.py
│   ├── reconciliation.py
│   └── status_manager.py
├── database/
│   ├── models.py
│   ├── repository.py
│   └── migrations/
├── reporting/
│   ├── excel_export.py
│   ├── csv_export.py
│   ├── json_export.py
│   ├── html_report.py
│   └── screenshot_capture.py
├── ui/
│   ├── home.py
│   ├── connection_page.py
│   ├── configuration_page.py
│   ├── extraction_page.py
│   ├── comparison_page.py
│   ├── details_page.py
│   └── history_page.py
├── frontend/
│   └── powerbi_extractor.js
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── docs/
├── logs/
└── exports/
```

Adapt as needed, but keep separation of concerns and maintainability.

---

## 22. Development phases and gates

### Phase 1 — Research and technical validation
Verify, using official Microsoft documentation:
- Power BI API capabilities
- `visual.exportData()` capabilities and limits
- Authentication and embedding options
- Report embedding and enumeration
- China filter application
- Licensing and capacity requirements
- Tenant restrictions
- Fallback methods
- Unsupported scenarios

Create `docs/TECHNICAL_VALIDATION.md` containing sources, date verified, decisions, limitations, and assumptions.

**Gate:** No speculative API behavior may be treated as verified.

### Phase 2 — Foundation
- Create project structure
- Configure environment and dependencies
- Implement authentication
- Implement workspace discovery
- Implement report discovery
- Implement database

**Gate:** Unit tests and mocked discovery tests pass. Live authentication is documented as tested or untested.

### Phase 3 — Extraction engine
- Create embedding environment
- Implement Playwright orchestration
- Implement JavaScript page/visual enumeration
- Implement `visual.exportData()`
- Return structured data to Python
- Implement extraction logs and completeness evidence

**Gate:** Deterministic mocked extraction tests pass. At least one live export must be attempted when credentials and report access are available. Do not claim live verification otherwise.

### Phase 4 — China filtering
- Implement country-field configuration
- Apply China context
- Validate effective context
- Test original and migrated report context
- Preserve unrelated filters

**Gate:** Context mismatch or inability to validate context must produce an inconclusive result, not a pass.

### Phase 5 — Visual matching
- Implement automatic matching
- Implement manual mappings
- Persist approved mappings
- Handle unmatched visuals

**Gate:** Tests validate matching confidence, ambiguity, and unmapped cases.

### Phase 6 — Reconciliation
- Implement normalization
- Implement row comparison
- Implement numeric comparison
- Implement missing/additional detection
- Implement status classification

**Gate:** Unit tests for edge cases pass.

### Phase 7 — UI
- Build all dashboard pages
- Integrate backend services
- Add progress/status
- Add details and evidence views

**Gate:** UI smoke tests and basic workflow tests pass.

### Phase 8 — Exports
- Excel
- CSV
- JSON
- HTML

**Gate:** Validate output files and workbook sheet contents.

### Phase 9 — Quality assurance
- Run unit tests
- Run integration tests
- Attempt live connectivity
- Test unsupported visuals
- Test incomplete exports
- Test filter-context differences
- Fix critical defects

**Gate:** Publish actual test results and unresolved limitations.

### Phase 10 — Delivery
Deliver the working project, source code, documentation, and sample evidence.

---

## 23. Final deliverables

Deliver:
- Complete source code
- `requirements.txt`
- `.env.example`
- `README.md`
- Entra configuration guide
- Power BI permissions guide
- Installation instructions
- Database setup and backup instructions
- Test execution instructions
- Deployment instructions
- Troubleshooting guide
- Sample comparison fixture and sample output
- Technical validation document
- Known limitations
- Implementation status ledger

Provide reproducible commands for setup, launch, tests, and deployment.

---

## 24. Acceptance criteria

The project is considered delivered only when the implementation status clearly records the state of each criterion:

- [ ] User can authenticate to Power BI (live-tested or explicitly documented as not live-tested)
- [ ] User can select two workspaces
- [ ] User can select two reports
- [ ] Application can discover report pages
- [ ] Application can enumerate supported visuals
- [ ] Application can apply and validate China context on the original report
- [ ] Application can extract actual visual-level summarized data
- [ ] Application can extract corresponding migrated report visual data
- [ ] Application can map corresponding visuals
- [ ] Application can normalize datasets without altering originals
- [ ] Application can compare visual values
- [ ] Application can identify missing records
- [ ] Application can identify additional records
- [ ] Application can identify numeric mismatches
- [ ] Application calculates absolute and percentage differences safely
- [ ] Application displays detailed evidence
- [ ] Application generates Excel output
- [ ] Application retains comparison history
- [ ] Application distinguishes PASS, FAIL, PARTIAL, INCONCLUSIVE, UNSUPPORTED, and NOT MAPPED
- [ ] Application never reports PASS when required extraction or context is incomplete
- [ ] Unit tests pass
- [ ] Mock tests are clearly distinguished from live tests
- [ ] Security and limitations are documented

---

## 25. Mandatory development rules

- Build, do not merely explain.
- Do not substitute pseudocode for executable implementation.
- Do not invent Power BI API endpoints.
- Use official Microsoft documentation for Power BI capabilities.
- Do not assume all visuals support all export modes.
- Do not hardcode workspace IDs, report IDs, or country field names.
- Do not hardcode visual mappings.
- Do not compare semantic-model schemas or DAX definitions.
- Do not silently ignore extraction failures.
- Do not present mocked integrations as live integrations.
- Do not claim testing that was not performed.
- Do not claim that free software eliminates Microsoft licensing requirements.
- Keep modules maintainable, documented, and testable.
- Keep the application read-only.
- Protect production data and credentials.
- Preserve original extraction evidence.
- Ask for clarification only when a genuinely necessary configuration is missing.
- Document technical limitations and implement the best supported fallback.
- Prioritize accuracy, extraction completeness, explainability, security, and maintainability over unnecessary features.

---

## 26. Start now

Begin with Phase 1: technical research and validation of Power BI visual-level extraction and embedding.

Then create the project in the available workspace and implement it phase by phase.

Do not stop after producing the research document. Continue building the application. If external credentials, tenant permissions, or Power BI licensing are unavailable, finish all locally testable modules, create realistic fixtures, run tests, and provide exact steps for the user to complete live validation.

At all times, report the real state of the implementation—not an aspirational one.
