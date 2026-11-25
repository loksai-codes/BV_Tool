"""Workspace discovery — GET /groups (verified: TECHNICAL_VALIDATION.md §7)."""
from __future__ import annotations

from core.contracts import Workspace
from core.security import validate_guid
from powerbi.http_client import ErrorCategory, PowerBIApiError, PowerBIHttpClient


class WorkspaceClient:
    PAGE_SIZE = 1000

    def __init__(self, http: PowerBIHttpClient) -> None:
        self.http = http

    def list_workspaces(self) -> list[Workspace]:
        items = self.http.get_all("/groups", page_size=self.PAGE_SIZE)
        return sorted((self._map(i) for i in items), key=lambda w: w.name.lower())

    def get_workspace(self, workspace_id: str) -> Workspace:
        wid = validate_guid(workspace_id, "workspace id")
        # Documented OData $filter on /groups; avoids relying on an undocumented single-group GET shape.
        items = self.http.get("/groups", params={"$filter": f"id eq '{wid}'"}).get("value", [])
        if not items:
            raise PowerBIApiError(ErrorCategory.NOT_FOUND, 404, "WorkspaceNotFound", f"Workspace {wid} not visible")
        return self._map(items[0])

    @staticmethod
    def _map(i: dict) -> Workspace:
        return Workspace(
            id=i["id"],
            name=i.get("name", ""),
            is_read_only=i.get("isReadOnly"),
            is_on_dedicated_capacity=i.get("isOnDedicatedCapacity"),
            capacity_id=i.get("capacityId"),
        )
