/*
 * MOCK Power BI JavaScript SDK — FOR TESTS ONLY. Not Microsoft code, not live.
 * Implements the subset of the powerbi-client surface used by powerbi_extractor.js,
 * driven by window.__MOCK_REPORTS__ = { [reportId]: spec } (see sample_data/mock_reports.py).
 * Enum values mirror powerbi-models@2.2.0 (verified from its models.d.ts).
 */
(function () {
  "use strict";
  const models = {
    TokenType: { Aad: 0, Embed: 1 },
    Permissions: { Read: 0, ReadWrite: 1, Copy: 2, Create: 4, All: 7 },
    ViewMode: { View: 0, Edit: 1 },
    FiltersOperations: { RemoveAll: 0, ReplaceAll: 1, Add: 2, Replace: 3 },
    ExportDataType: { Summarized: 0, Underlying: 1 },
  };
  const clone = (o) => JSON.parse(JSON.stringify(o));
  const targets = (f, t) => f.target && String(f.target.table).toLowerCase() === t.table.toLowerCase()
    && String(f.target.column).toLowerCase() === t.column.toLowerCase();

  function effectiveCountry(filters, target) {
    let sel = null;
    for (const f of filters) {
      if (!targets(f, target)) continue;
      const vals = f.values || [];
      if (String(f.operator).toLowerCase() === "in" && vals.length === 1) {
        if (sel !== null && sel !== String(vals[0])) return "__none__";
        sel = String(vals[0]);
      }
    }
    return sel || "__all__";
  }

  class Emitter {
    constructor() { this.handlers = {}; }
    on(n, fn) { (this.handlers[n] = this.handlers[n] || []).push(fn); }
    off(n) { delete this.handlers[n]; }
    emit(n, detail) { (this.handlers[n] || []).slice().forEach((fn) => fn({ detail })); }
  }

  class MockVisual {
    constructor(report, page, spec) {
      this.report = report; this.pageSpec = page; this.spec = spec;
      this.name = spec.name; this.type = spec.type; this.title = spec.title; this.layout = spec.layout || {};
    }
    async getFilters() { return clone(this.spec.filters || []); }
    async getSlicerState() {
      if (!this.spec.slicerState) throw { message: "Operation works on slicers only" };
      return clone(this.spec.slicerState);
    }
    async exportData(type, rows) {
      if (this.report._exporting) throw { message: "concurrent export" };
      this.report._exporting = true;
      try {
        await new Promise((r) => setTimeout(r, 5));
        if (this.spec.exportError) throw clone(this.spec.exportError);
        if (type === models.ExportDataType.Underlying && this.spec.underlyingError) throw clone(this.spec.underlyingError);
        const csvs = this.spec.csvByCountry || {};
        const filters = this.report._filters.concat(this.pageSpec.filters || [], this.spec.filters || []);
        const key = effectiveCountry(filters, this.report._spec.countryTarget);
        let data = csvs[key];
        if (data === undefined) data = (csvs.__all__ || "\r\n").split("\r\n")[0] + "\r\n";
        const lines = data.split("\r\n");
        if (lines.length - 2 > rows) data = lines.slice(0, rows + 1).join("\r\n") + "\r\n";
        return { data };
      } finally { this.report._exporting = false; }
    }
  }

  class MockPage {
    constructor(report, spec) { this.report = report; this.spec = spec; this.name = spec.name; this.displayName = spec.displayName; this.visibility = spec.visibility || 0; }
    get isActive() { return this.report._active === this.name; }
    async setActive() { this.report._active = this.name; setTimeout(() => this.report.emit("rendered"), 10); }
    async getVisuals() { return (this.report._spec.visuals[this.name] || []).map((v) => new MockVisual(this.report, this.spec, v)); }
    async getFilters() { return clone(this.spec.filters || []); }
  }

  class MockReport extends Emitter {
    constructor(spec, config) {
      super();
      this._spec = spec; this._config = config; this._filters = clone(spec.initialReportFilters || []);
      this._active = spec.pages[0].name; this._exporting = false;
      this.bookmarksManager = { capture: async () => ({ state: "mock-bookmark-state" }) };
      setTimeout(() => {
        if (spec.loadError) { this.emit("error", spec.loadError); return; }
        if (config.viewMode !== models.ViewMode.View) { this.emit("error", { message: "mock: expected View mode" }); return; }
        this.emit("loaded"); setTimeout(() => this.emit("rendered"), 10);
      }, 10);
    }
    async getPages() { return this._spec.pages.map((p) => new MockPage(this, p)); }
    async getActivePage() { return new MockPage(this, this._spec.pages.find((p) => p.name === this._active)); }
    async getFilters() { return clone(this._filters); }
    async updateFilters(op, filters) {
      if (this._spec.updateFiltersError) throw { message: this._spec.updateFiltersError };
      if (op === models.FiltersOperations.Add) this._filters = this._filters.concat(clone(filters));
      else if (op === models.FiltersOperations.Replace) {
        for (const nf of filters) {
          const i = this._filters.findIndex((f) => JSON.stringify(f.target) === JSON.stringify(nf.target));
          if (i < 0) this._filters.push(clone(nf)); else this._filters[i] = clone(nf);
        }
      } else if (op === models.FiltersOperations.RemoveAll) this._filters = [];
      else if (op === models.FiltersOperations.ReplaceAll) this._filters = clone(filters);
      setTimeout(() => this.emit("rendered"), 10);
    }
  }

  window.__pbiModels = models;
  window["powerbi-client"] = { models };
  window.powerbi = {
    embed(el, config) {
      const spec = (window.__MOCK_REPORTS__ || {})[config.id];
      if (!spec) throw new Error("mock: no spec for report " + config.id);
      window.__lastEmbedConfig = { tokenType: config.tokenType, viewMode: config.viewMode, permissions: config.permissions, hasToken: !!config.accessToken };
      return new MockReport(spec, config);
    },
    reset() {},
  };
})();
