"""JSON-file-backed store for workflow definitions.

Each workflow is stored as one JSON file under ``storage/``, keyed by
workflow id. Mirrors the world/RAG metadata.json pattern but one-file-per
workflow so large graphs don't all pile into a single record file.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class WorkflowStore:
    """Persist and query workflow definitions."""

    def __init__(self, storage_dir: Path | None = None) -> None:
        root = Path(__file__).resolve().parent
        self.storage_dir = storage_dir or Path(
            os.getenv("WORKFLOW_STORAGE_DIR", str(root / "storage"))
        )
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------
    def _path_for(self, workflow_id: str) -> Path:
        return self.storage_dir / f"{workflow_id}.json"

    def _valid_id(self, workflow_id: str) -> bool:
        return bool(_ID_PATTERN.match(workflow_id))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def save(self, workflow: dict[str, Any]) -> dict[str, Any]:
        """Save (create or update) a workflow definition."""

        workflow_id = str(workflow.get("id") or "draft")
        if not self._valid_id(workflow_id):
            raise ValueError(f"工作流 ID 不合法：{workflow_id}")
        if not isinstance(workflow.get("nodes"), list):
            raise ValueError("工作流缺少 nodes 数组。")
        if not isinstance(workflow.get("edges"), list):
            raise ValueError("工作流缺少 edges 数组。")

        record = {
            "id": workflow_id,
            "title": str(workflow.get("title") or "未命名工作流"),
            "nodes": workflow["nodes"],
            "edges": workflow["edges"],
            "updated_at": workflow.get("updatedAt")
            or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "created_at": None,
        }
        with self._lock:
            existing = self.get(workflow_id)
            if existing is not None:
                record["created_at"] = existing.get("created_at")
            if not record["created_at"]:
                record["created_at"] = record["updated_at"]
            self._path_for(workflow_id).write_text(
                json.dumps(record, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return record

    def get(self, workflow_id: str) -> dict[str, Any] | None:
        """Return one workflow, or None if it does not exist."""

        if not self._valid_id(workflow_id):
            return None
        path = self._path_for(workflow_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def list(self) -> list[dict[str, Any]]:
        """Return all workflows, newest first."""

        with self._lock:
            records: list[dict[str, Any]] = []
            for path in self.storage_dir.glob("*.json"):
                try:
                    records.append(json.loads(path.read_text(encoding="utf-8")))
                except (json.JSONDecodeError, OSError):
                    continue
        return sorted(
            records,
            key=lambda record: record.get("updated_at", ""),
            reverse=True,
        )

    def delete(self, workflow_id: str) -> bool:
        """Delete a workflow; returns True if it existed."""

        if not self._valid_id(workflow_id):
            return False
        path = self._path_for(workflow_id)
        if not path.exists():
            return False
        with self._lock:
            path.unlink(missing_ok=True)
        return True
