"""Page registry (populated by app.py) so pages can link to each other."""
from __future__ import annotations

from typing import Any

PAGES: dict[str, Any] = {}


def page(key: str):
    return PAGES.get(key)
