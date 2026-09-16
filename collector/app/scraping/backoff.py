"""Compute crawl retry delays after source failures."""

from __future__ import annotations

# failure 1 → 15m, 2 → 30m, 3 → 60m, 4+ → capped at 6h
_BASE_MINUTES = 15
_CAP_MINUTES = 6 * 60


def failure_backoff_minutes(consecutive_failures: int) -> int:
    """
    Return minutes to wait before the next crawl attempt after N failures.

    consecutive_failures must be >= 1 (call after incrementing).
    """
    n = max(1, int(consecutive_failures))
    return min(_BASE_MINUTES * (2 ** (n - 1)), _CAP_MINUTES)
