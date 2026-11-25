"""Application service layer: the only module the UI/API talk to.

Keeps the UI decoupled from Power BI clients and reconciliation internals.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from pydantic import SecretStr

from comparison.reconciliation import run_comparison
from comparison.visual_matcher import MatchSettings, suggest_page_mappings, suggest_visual_mappings
from config.settings import Settings
from core.contracts import ComparisonConfig, ComparisonRunResult, ReportExtraction, ReportInfo, VisualMapping
from core.security import get_logger
from database.repository import Repository
from powerbi.embed_manager import EmbedConfig, EmbedManager
from powerbi.mock_driver import MockDriver
from powerbi.visual_extractor import VisualExtractor

log = get_logger("services.comparison")
Progress = Callable[[str, str, dict], None]


def extract_mock(config: ComparisonConfig, original_spec: dict | None = None, migrated_spec: dict | None = None,
                 progress: Progress | None = None) -> tuple[ReportExtraction, ReportExtraction]:
    """MOCK extraction from fixtures. Results are flagged is_mock=True everywhere."""
    from sample_data import mock_reports as mr

    out = []
    for role, spec in (("original", original_spec or mr.original_spec()), ("migrated", migrated_spec or mr.migrated_spec())):
        info = mr.mock_report_info(role)
        info = info.model_copy(update={"id": spec["reportId"]})
        embed = EmbedConfig(info.id, info.embed_url or "", SecretStr("mock-token"), "Aad", ["MOCK embed (no Power BI)."])
        ex = VisualExtractor(MockDriver(spec), progress=progress)
        out.append(ex.extract(role, info, embed, config.country,
                              apply_context=(role == "original") or config.country.apply_to_migrated,
                              mode=config.extraction_mode))
    return out[0], out[1]


def extract_live(settings: Settings, embed_manager: EmbedManager, original: ReportInfo, migrated: ReportInfo,
                 config: ComparisonConfig, progress: Progress | None = None,
                 capture_screenshots: bool = True) -> tuple[ReportExtraction, ReportExtraction]:
    """LIVE extraction via Playwright + official powerbi-client. Requires a signed-in identity with
    access to both reports and network access to Power BI. Never run by the automated test suite."""
    from powerbi.embed_host_server import EmbedHostServer
    from powerbi.visual_extractor import PlaywrightDriver

    settings.ensure_dirs()
    results = []
    with EmbedHostServer() as server:
        driver = PlaywrightDriver(server.base_url, headless=settings.headless_browser)
        try:
            for role, info in (("original", original), ("migrated", migrated)):
                embed = embed_manager.build(info)
                ex = VisualExtractor(driver, render_timeout_ms=settings.embed_render_timeout_ms,
                                     screenshot_dir=Path(settings.screenshot_dir) if capture_screenshots else None,
                                     progress=progress)
                results.append(ex.extract(role, info, embed, config.country,
                                          apply_context=(role == "original") or config.country.apply_to_migrated,
                                          mode=config.extraction_mode))
        finally:
            driver.close()
    return results[0], results[1]


def auto_map(original: ReportExtraction, migrated: ReportExtraction, config: ComparisonConfig) -> ComparisonConfig:
    """Suggest page/visual mappings; manual (user) mappings are kept and win."""
    manual = [vm for vm in config.visual_mappings if vm.provenance == "manual"]
    settings = MatchSettings(auto_approve_threshold=config.auto_approve_threshold)
    visual = suggest_visual_mappings(original, migrated, settings, manual=manual, page_mappings=config.page_mappings)
    pages = config.page_mappings or suggest_page_mappings(original, migrated, visual)
    return config.model_copy(update={"visual_mappings": visual, "page_mappings": pages})


def apply_profile(config: ComparisonConfig, profile: dict) -> ComparisonConfig:
    """Apply a saved, previously-approved mapping profile (as manual mappings)."""
    vms = [VisualMapping.model_validate({**v, "provenance": "manual", "approved": True}) for v in profile.get("visual_mappings", [])]
    return config.model_copy(update={"visual_mappings": vms})


def compare_and_save(original: ReportExtraction, migrated: ReportExtraction, config: ComparisonConfig,
                     repo: Repository | None, actor_ref_id: int | None = None) -> ComparisonRunResult:
    run = run_comparison(original, migrated, config)
    if repo is not None:
        run.run_id = repo.save_run(run, actor_ref_id)
    log.info("Comparison '%s' -> %s (mock=%s, run_id=%s)", run.name, run.overall_status.value, run.is_mock, run.run_id)
    return run


def demo_config() -> ComparisonConfig:
    from sample_data import mock_reports as mr

    cfg = ComparisonConfig(name="DEMO (mock data) — China reconciliation", country=mr.demo_country_config())
    cfg.normalization.decimal_places = 2
    return cfg


def run_demo(repo: Repository | None = None, approve_all_suggestions: bool = False,
             progress: Progress | None = None) -> ComparisonRunResult:
    """End-to-end MOCK pipeline. ``approve_all_suggestions`` simulates a user approving every suggestion."""
    cfg = demo_config()
    o, m = extract_mock(cfg, progress=progress)
    cfg = auto_map(o, m, cfg)
    if approve_all_suggestions:
        cfg.visual_mappings = [vm.model_copy(update={"approved": True}) for vm in cfg.visual_mappings]
    return compare_and_save(o, m, cfg, repo)
