"""Workflow persistence package for ModelMirror.

Stores workflow definitions (drawn on the classic canvas) as JSON files so
they survive browser refreshes and can be shared across users. Mirrors the
world/RAG store pattern.
"""

from __future__ import annotations

from .store import WorkflowStore

__all__ = ["WorkflowStore"]
