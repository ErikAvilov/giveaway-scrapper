"""Content hashing for change detection before Gemini re-analysis."""

from __future__ import annotations

import hashlib


def compute_content_hash(*parts: str | None) -> str:
    """
    SHA-256 hex digest of the concatenated textual parts used for analysis.

    Empty/None parts are treated as empty strings so the hash stays stable.
    """
    payload = "\n".join("" if p is None else p for p in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
