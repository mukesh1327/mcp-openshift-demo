"""Strip fields that bloat an LLM's context with no analytical value.

`managedFields` is often 40-60% of a Kubernetes object's JSON and is never
useful to a model; the same goes for a handful of tool-written annotations.
Removing them keeps tool results (which are re-sent on every subsequent turn)
small. `sanitize` mutates and returns the dict it is given.
"""

from __future__ import annotations

from typing import Any

NOISE_ANNOTATIONS = (
    "kubectl.kubernetes.io/last-applied-configuration",
    "kapp.k14s.io/original",
    "kapp.k14s.io/original-diff-md5",
)


def _clean_object(obj: dict[str, Any]) -> None:
    meta = obj.get("metadata")
    if isinstance(meta, dict):
        meta.pop("managedFields", None)
        annotations = meta.get("annotations")
        if isinstance(annotations, dict):
            for key in NOISE_ANNOTATIONS:
                annotations.pop(key, None)
            if not annotations:
                meta.pop("annotations", None)


def sanitize(payload: Any) -> Any:
    """Remove noise fields from a single object or a `*List` (via `.items`)."""
    if not isinstance(payload, dict):
        return payload
    _clean_object(payload)
    items = payload.get("items")
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                _clean_object(item)
    return payload
