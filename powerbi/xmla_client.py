"""XMLA read-only endpoint helper (docs/TECHNICAL_VALIDATION.md §8.2).

Requirements (verified): Premium / PPU / Embedded / Fabric capacity; read-only XMLA
enabled (default); Build permission on the semantic model; service principals do not
work with RLS/OLS. Connection string: powerbi://api.powerbi.com/v1.0/<tenant>/<URI-encoded workspace>.

There is no supported pure-Python ADOMD client. Querying requires the third-party
``pyadomd`` package plus Microsoft's ADOMD.NET client library installed on the host.
STATUS: connection-string building is unit-tested; ``query`` is NOT tested in this
environment (no ADOMD.NET available) and is reported as unavailable unless pyadomd imports.
Like the Execute Queries fallback, any result must be labelled FALLBACK_QUERY.
"""
from __future__ import annotations

from urllib.parse import quote


class XmlaUnavailableError(RuntimeError):
    pass


SETUP_HELP = (
    "XMLA fallback unavailable: install Microsoft ADOMD.NET client library and `pip install pyadomd`, "
    "ensure the workspace is on Premium/PPU/Embedded/Fabric capacity with XMLA read enabled and that the "
    "identity has Build permission on the semantic model."
)


def build_connection_string(workspace_name: str, dataset_name: str, tenant: str = "myorg") -> str:
    if not workspace_name.strip() or not dataset_name.strip():
        raise ValueError("workspace and dataset names are required")
    ws = quote(workspace_name.strip(), safe="")
    src = f"powerbi://api.powerbi.com/v1.0/{quote(tenant, safe='')}/{ws}"
    cat = dataset_name.replace(";", "").strip()
    return f"Provider=MSOLAP;Data Source={src};Initial Catalog={cat};"


def is_available() -> bool:
    try:
        import pyadomd  # type: ignore  # noqa: F401
    except Exception:
        return False
    return True


def query(connection_string: str, dax: str, access_token: str) -> tuple[list[str], list[tuple]]:  # pragma: no cover - untested
    """UNTESTED: requires pyadomd + ADOMD.NET. Token passed as Password per MSOLAP AAD token usage."""
    if not is_available():
        raise XmlaUnavailableError(SETUP_HELP)
    from pyadomd import Pyadomd  # type: ignore

    conn = connection_string + f"Password={access_token};"
    with Pyadomd(conn) as c:
        with c.cursor().execute(dax) as cur:
            cols = [d.name for d in cur.description]
            return cols, cur.fetchall()
