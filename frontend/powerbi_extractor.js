/*
 * Power BI Visual Data Extractor — browser-side primitives.
 *
 * Exposes window.pbiExtractor with small, single-purpose async functions that
 * the Python Playwright orchestrator calls one at a time (page.evaluate).
 * Decision logic (filter planning, status classification, truncation) lives in
 * Python where it is unit-tested; this file only talks to the Power BI JS SDK.
 *
 * Verified SDK surface (powerbi-client 2.25.0, see docs/TECHNICAL_VALIDATION.md):
 *   powerbi.embed(el, config) -> Report; report.on('loaded'|'rendered'|'error')
 *   report.getPages(), page.setActive(), page.getVisuals(), page.getFilters()
 *   report.getFilters(), report.updateFilters(op, filters)
 *   visual.exportData(exportDataType, rows) -> {data: csvString}
 *   visual.getFilters(), visual.getSlicerState(), report.bookmarksManager.capture()
 *
 * READ-ONLY GUARANTEES:
 *   - viewMode is forced to View; permissions to Read; edit/save never called.
 *   - updateFilters only allows Add / Replace (never RemoveAll / ReplaceAll),
 *     so unrelated filters cannot be wiped. Filter changes affect only this
 *     in-browser session and are not saved to the report.
 *   - exports run strictly sequentially (concurrent exports are unsupported).
 */
(function () {
  "use strict";

  const state = { report: null, pages: {}, visuals: {}, events: [], busy: false };

  function sdk() {
    const ns = window["powerbi-client"] || {};
    const service = window.powerbi;
    const models = ns.models || window.__pbiModels;
    if (!service || !models) throw new Error("Power BI JavaScript SDK not loaded");
    return { service, models };
  }

  function errInfo(e) {
    if (e === undefined || e === null) return { message: "Unknown error" };
    if (typeof e === "string") return { message: e };
    const out = {
      message: e.message || e.detailedMessage || String(e),
      detailedMessage: e.detailedMessage || null,
      errorCode: e.errorCode || (e.body && e.body.errorCode) || null,
      level: e.level || null,
    };
    if (e.body && typeof e.body === "object") {
      out.message = out.message === "[object Object]" ? (e.body.message || "Error") : out.message;
      out.detailedMessage = out.detailedMessage || e.body.detailedMessage || null;
    }
    return out;
  }

  function log(msg) {
    state.events.push(new Date().toISOString() + " " + msg);
  }

  function waitForEvent(name, timeoutMs) {
    return new Promise((resolve) => {
      let done = false;
      const timer = setTimeout(() => {
        if (!done) { done = true; resolve({ fired: false }); }
      }, timeoutMs);
      state.report.on(name, (ev) => {
        if (!done) { done = true; clearTimeout(timer); resolve({ fired: true, detail: ev && ev.detail }); }
      });
    });
  }

  function cleanFilter(f) {
    try { return JSON.parse(JSON.stringify(f)); } catch (e) { return { unserializable: true }; }
  }

  async function loadReport(cfg) {
    const { service, models } = sdk();
    const container = document.getElementById("reportContainer");
    if (state.report) { try { service.reset(container); } catch (e) { /* ignore */ } }
    state.pages = {}; state.visuals = {}; state.events = [];
    const tokenType = cfg.tokenType === "Embed" ? models.TokenType.Embed : models.TokenType.Aad;
    const embedConfig = {
      type: "report",
      id: cfg.reportId,
      embedUrl: cfg.embedUrl,
      accessToken: cfg.accessToken,
      tokenType: tokenType,
      permissions: models.Permissions.Read,
      viewMode: models.ViewMode.View,
      settings: {
        panes: { filters: { visible: false }, pageNavigation: { visible: false } },
        visualRenderedEvents: false,
      },
    };
    let embedError = null;
    state.report = service.embed(container, embedConfig);
    state.report.on("error", (ev) => {
      embedError = errInfo(ev && ev.detail);
      log("SDK error event: " + embedError.message);
    });
    const loaded = await waitForEvent("loaded", cfg.renderTimeoutMs || 90000);
    if (!loaded.fired) {
      return { ok: false, error: embedError || { message: "Report did not raise 'loaded' within timeout", errorCode: "load_timeout" }, log: state.events };
    }
    const rendered = await waitForEvent("rendered", cfg.renderTimeoutMs || 90000);
    log("Report loaded; rendered=" + rendered.fired);
    return { ok: true, rendered: rendered.fired, error: embedError, log: state.events };
  }

  async function getPages() {
    const pages = await state.report.getPages();
    state.pages = {};
    return pages.map((p) => {
      state.pages[p.name] = p;
      return { name: p.name, displayName: p.displayName, isActive: !!p.isActive, visibility: p.visibility === undefined ? null : p.visibility };
    });
  }

  async function activatePage(pageName, renderTimeoutMs) {
    const page = state.pages[pageName];
    if (!page) return { ok: false, error: { message: "Unknown page " + pageName } };
    try {
      const wait = waitForEvent("rendered", renderTimeoutMs || 90000);
      if (!page.isActive) { await page.setActive(); }
      const activeNow = await state.report.getActivePage();
      // If the page was already active no new 'rendered' necessarily fires; don't wait full timeout.
      const r = page.isActive && activeNow && activeNow.name === pageName
        ? await Promise.race([wait, new Promise((res) => setTimeout(() => res({ fired: false, alreadyActive: true }), 3000))])
        : await wait;
      return { ok: true, rendered: !!r.fired, alreadyActive: !!r.alreadyActive };
    } catch (e) {
      return { ok: false, error: errInfo(e) };
    }
  }

  async function listVisuals(pageName) {
    const page = state.pages[pageName];
    if (!page) throw new Error("Unknown page " + pageName);
    const visuals = await page.getVisuals();
    return visuals.map((v) => {
      state.visuals[pageName + "/" + v.name] = v;
      return { name: v.name, type: v.type, title: v.title || null, layout: v.layout ? cleanFilter(v.layout) : {} };
    });
  }

  async function captureReportFilters() {
    try { return { ok: true, filters: (await state.report.getFilters()).map(cleanFilter) }; }
    catch (e) { return { ok: false, filters: [], error: errInfo(e) }; }
  }

  async function capturePageFilters(pageName) {
    const page = state.pages[pageName];
    try { return { ok: true, filters: (await page.getFilters()).map(cleanFilter) }; }
    catch (e) { return { ok: false, filters: [], error: errInfo(e) }; }
  }

  async function captureBookmarkState() {
    try {
      if (!state.report.bookmarksManager) return { captured: false, error: { message: "bookmarksManager unavailable" } };
      const b = await state.report.bookmarksManager.capture();
      return { captured: !!(b && b.state), length: b && b.state ? b.state.length : 0 };
    } catch (e) {
      return { captured: false, error: errInfo(e) };
    }
  }

  async function updateReportFilters(operationName, filters) {
    const { models } = sdk();
    if (operationName !== "Add" && operationName !== "Replace") {
      return { ok: false, error: { message: "Operation " + operationName + " refused: only Add/Replace allowed (preserves unrelated filters)" } };
    }
    try {
      await state.report.updateFilters(models.FiltersOperations[operationName], filters);
      const wait = await waitForEvent("rendered", 30000);
      return { ok: true, rendered: wait.fired };
    } catch (e) {
      return { ok: false, error: errInfo(e) };
    }
  }

  async function captureVisualContext(pageName, visualName, isSlicer) {
    const v = state.visuals[pageName + "/" + visualName];
    const out = { filters: [], slicerState: null, errors: [] };
    if (!v) { out.errors.push({ message: "Unknown visual" }); return out; }
    try { out.filters = (await v.getFilters()).map(cleanFilter); }
    catch (e) { out.errors.push(errInfo(e)); }
    if (isSlicer) {
      try { out.slicerState = cleanFilter(await v.getSlicerState()); }
      catch (e) { out.errors.push(errInfo(e)); }
    }
    return out;
  }

  async function exportVisual(pageName, visualName, mode, rows) {
    const { models } = sdk();
    const v = state.visuals[pageName + "/" + visualName];
    if (!v) return { ok: false, error: { message: "Unknown visual" } };
    if (state.busy) return { ok: false, error: { message: "Concurrent export refused (unsupported by Power BI)" } };
    state.busy = true;
    const started = Date.now();
    try {
      const type = mode === "UNDERLYING" ? models.ExportDataType.Underlying : models.ExportDataType.Summarized;
      const result = await v.exportData(type, rows);
      const data = result && typeof result.data === "string" ? result.data : null;
      if (data === null) return { ok: false, error: { message: "exportData returned no CSV string", errorCode: "empty_result" } };
      return { ok: true, data: data, elapsedMs: Date.now() - started };
    } catch (e) {
      return { ok: false, error: errInfo(e), elapsedMs: Date.now() - started };
    } finally {
      state.busy = false;
    }
  }

  function getLog() { return state.events.slice(); }

  window.pbiExtractor = {
    loadReport, getPages, activatePage, listVisuals, captureReportFilters, capturePageFilters,
    captureBookmarkState, updateReportFilters, captureVisualContext, exportVisual, getLog,
    version: "1.0.0",
  };
})();
