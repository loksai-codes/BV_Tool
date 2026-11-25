"""Security helpers: log sanitization, input validation, safe file names."""
from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path

_REDACTIONS: list[tuple[re.Pattern[str], str]] = [
    # JWTs (access/id tokens)
    (re.compile(r"eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"), "[REDACTED_JWT]"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-~+/=]{8,}"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(\"?(?:access_token|refresh_token|id_token|client_secret|accessToken|embedToken|token)\"?\s*[:=]\s*\"?)[^\"\s,}]{4,}"), r"\1[REDACTED]"),
]


def sanitize(text: str) -> str:
    if not isinstance(text, str):
        text = str(text)
    for pattern, repl in _REDACTIONS:
        text = pattern.sub(repl, text)
    return text


class SanitizingFilter(logging.Filter):
    """Logging filter that redacts tokens/secrets from every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # pragma: no cover - defensive
            return True
        record.msg = sanitize(msg)
        record.args = ()
        return True


def configure_logging(log_dir: Path, level: int = logging.INFO) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("pbi_comparator")
    if getattr(logger, "_configured", False):
        return logger
    logger.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    fh = logging.FileHandler(log_dir / "app.log", encoding="utf-8")
    fh.setFormatter(fmt)
    fh.addFilter(SanitizingFilter())
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    sh.addFilter(SanitizingFilter())
    logger.addHandler(fh)
    logger.addHandler(sh)
    logger._configured = True  # type: ignore[attr-defined]
    return logger


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(f"pbi_comparator.{name}")
    if not any(isinstance(f, SanitizingFilter) for f in logger.filters):
        logger.addFilter(SanitizingFilter())
    return logger


def validate_guid(value: str, what: str = "id") -> str:
    """Power BI workspace/report/dataset ids are GUIDs; reject anything else (prevents path injection)."""
    try:
        return str(uuid.UUID(str(value).strip()))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError(f"Invalid {what}: expected a GUID") from exc


_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(name: str, max_len: int = 80) -> str:
    cleaned = _SAFE_NAME.sub("_", name).strip("._") or "file"
    return cleaned[:max_len]


def safe_join(base: Path, *parts: str) -> Path:
    """Join paths and ensure the result stays inside ``base``."""
    base = base.resolve()
    target = base.joinpath(*[safe_filename(p) for p in parts]).resolve()
    if base != target and base not in target.parents:
        raise ValueError("Path escapes base directory")
    return target
