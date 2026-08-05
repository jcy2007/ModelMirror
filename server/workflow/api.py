"""REST API for workflow persistence.

Endpoints:
  POST /api/workflow/save     save (create/update) a workflow
  GET  /api/workflow/:id      load a workflow
  GET  /api/workflow/list     list all workflows
  DELETE /api/workflow/:id    delete a workflow
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from .store import WorkflowStore

router = APIRouter(prefix="/api/workflow", tags=["workflow"])

_store = WorkflowStore()


class WorkflowApiError(Exception):
    """Base error for the workflow store API."""


@router.post("/save")
async def save_workflow(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return _store.save(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/list")
async def list_workflows() -> list[dict[str, Any]]:
    return _store.list()


@router.get("/{workflow_id}")
async def get_workflow(workflow_id: str) -> dict[str, Any]:
    record = _store.get(workflow_id)
    if record is None:
        raise HTTPException(status_code=404, detail="工作流不存在。")
    return record


@router.delete("/{workflow_id}")
async def delete_workflow(workflow_id: str) -> dict[str, bool]:
    existed = _store.delete(workflow_id)
    if not existed:
        raise HTTPException(status_code=404, detail="工作流不存在。")
    return {"ok": True}
