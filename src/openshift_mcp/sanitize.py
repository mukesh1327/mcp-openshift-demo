"""Strip fields that bloat an LLM's context with no analytical value.

`managedFields` is often 40-60% of a Kubernetes object's JSON and is never
useful to a model; the same goes for a handful of tool-written annotations.
Removing them keeps tool results (which are re-sent on every subsequent turn)
small. `sanitize` mutates and returns the dict it is given.
"""

from __future__ import annotations

from typing import Any

# Annotations that tools write and that hold a full serialized copy of the
# object (or a diff of it) - huge, and never useful to a model.
NOISE_ANNOTATIONS = (
    "kubectl.kubernetes.io/last-applied-configuration",  # `kubectl apply` (client-side)
    "kapp.k14s.io/original",  # carvel kapp
    "kapp.k14s.io/original-diff-md5",
)


def _clean_object(obj: dict[str, Any]) -> None:
    """Strip the noise fields from one API object, in place."""
    # All the noise lives under metadata; a non-dict metadata means nothing to do.
    meta = obj.get("metadata")
    if isinstance(meta, dict):
        meta.pop("managedFields", None)  # the biggest offender - server-side-apply bookkeeping
        annotations = meta.get("annotations")
        if isinstance(annotations, dict):
            # Drop only the known full-object-copy annotations; keep the rest.
            for key in NOISE_ANNOTATIONS:
                annotations.pop(key, None)
            if not annotations:  # don't leave an empty "annotations": {} behind
                meta.pop("annotations", None)


def sanitize(payload: Any) -> Any:
    """Clean a single object or a `*List` (each entry in `.items`), in place.

    Returns the same object it was given. Non-dicts (e.g. a plain log string)
    pass straight through.
    """
    if not isinstance(payload, dict):
        return payload  # e.g. a plain pod-log string - nothing to strip
    _clean_object(payload)  # the top-level object (or, for a *List, the List's own metadata)
    # A *List response carries the real objects under .items - clean each of them too.
    items = payload.get("items")
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                _clean_object(item)
    return payload
