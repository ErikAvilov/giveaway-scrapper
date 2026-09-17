"""Run Gleam-giveaway-bot against Neon-queued campaigns (desktop only)."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from psycopg import Connection

from app.db.repository import GiveawayRepository
from app.gleam_enter.urls import gleam_entry_url
from app.models.giveaway import Giveaway, ManualStatus

logger = logging.getLogger(__name__)

# Repo root: collector/app/gleam_enter/service.py → parents[3] = giveaway-scrapper/
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BOT_ROOT = _REPO_ROOT / "Gleam-giveaway-bot"


@dataclass(slots=True)
class EnterGleamResult:
    queued: int = 0
    attempted: int = 0
    marked_entered: int = 0
    failed: int = 0
    dry_run: bool = False
    bot_ok: list[dict[str, Any]] = field(default_factory=list)
    bot_failed: list[dict[str, Any]] = field(default_factory=list)
    queued_items: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def format_lines(self) -> list[str]:
        lines = [
            f"queued={self.queued}",
            f"attempted={self.attempted}",
            f"marked_entered={self.marked_entered}",
            f"failed={self.failed}",
            f"dry_run={self.dry_run}",
        ]
        if self.error:
            lines.append(f"error={self.error}")
        for item in self.queued_items[:20]:
            lines.append(
                f"queue id={item.get('id')} url={item.get('url')} title={item.get('title')!r}"
            )
        for item in self.bot_ok[:20]:
            lines.append(f"ok id={item.get('id')} url={item.get('url')}")
        for item in self.bot_failed[:20]:
            lines.append(
                f"fail id={item.get('id')} reason={item.get('reason')} url={item.get('url')}"
            )
        return lines


def resolve_bot_root(explicit: str | Path | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get("GLEAM_BOT_ROOT", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return DEFAULT_BOT_ROOT.resolve()


def enter_gleam_queue(
    conn: Connection,
    *,
    limit: int = 10,
    manual_statuses: list[str] | None = None,
    require_france_eligible: bool = False,
    require_entry_acceptable: bool = True,
    only_ids: list[UUID] | None = None,
    dry_run: bool = False,
    headless: bool = True,
    skip_history: bool = True,
    mark_entered: bool = True,
    bot_root: str | Path | None = None,
    python_executable: str | None = None,
) -> EnterGleamResult:
    """
    Select Gleam rows from Neon and complete them via Gleam-giveaway-bot.

    Requires a prior `python login.py` in the bot directory (cookies.pkl).
    Never runs Chromium on the Pi worker path — call this from a desktop host.
    """
    repo = GiveawayRepository(conn)
    rows = repo.list_for_gleam_enter(
        limit=limit,
        manual_statuses=manual_statuses,
        require_france_eligible=require_france_eligible,
        require_entry_acceptable=require_entry_acceptable,
        only_ids=only_ids,
    )

    result = EnterGleamResult(dry_run=dry_run)
    jobs: list[tuple[Giveaway, str]] = []
    for g in rows:
        url = gleam_entry_url(g)
        if not url:
            continue
        jobs.append((g, url))
        result.queued_items.append(
            {
                "id": str(g.id),
                "url": url,
                "title": g.title,
                "manual_status": g.manual_status.value,
                "platform_campaign_id": g.platform_campaign_id,
            }
        )
    result.queued = len(jobs)

    if dry_run or not jobs:
        return result

    root = resolve_bot_root(bot_root)
    runner = root / "run_urls.py"
    cookies = root / "data" / "cookies.pkl"
    config = root / "config.json"
    if not runner.is_file():
        result.error = f"Bot runner missing: {runner}"
        return result
    if not cookies.is_file():
        result.error = (
            f"Missing cookies at {cookies} — run `python login.py` in {root}"
        )
        return result
    if not config.is_file():
        result.error = (
            f"Missing config.json in {root} — copy config.json.example first"
        )
        return result

    py = python_executable or sys.executable
    cmd = [py, str(runner), "--json-summary"]
    if skip_history:
        cmd.append("--skip-history")
    cmd.append("--headless" if headless else "--no-headless")
    for _g, url in jobs:
        cmd.extend(["--url", url])

    logger.info("Launching Gleam bot (%d urls, cwd=%s)", len(jobs), root)
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
            timeout=max(120, 90 * max(1, len(jobs))),
        )
    except subprocess.TimeoutExpired:
        result.error = "Bot timed out"
        return result
    except OSError as exc:
        result.error = f"Failed to launch bot: {exc}"
        return result

    if proc.stderr:
        logger.info("Gleam bot stderr:\n%s", proc.stderr[-4000:])

    summary = _parse_bot_summary(proc.stdout)
    if summary is None:
        result.error = (
            f"Bot exited {proc.returncode} without JSON summary. "
            f"stderr={_trim(proc.stderr)}"
        )
        return result

    result.attempted = int(summary.get("attempted") or 0)
    result.bot_ok = list(summary.get("ok") or [])
    result.bot_failed = list(summary.get("failed") or [])
    result.failed = len(result.bot_failed)

    if mark_entered and result.bot_ok:
        for g, url in jobs:
            if g.id is None:
                continue
            if _job_matched(g, url, result.bot_ok):
                repo.update_manual_status(g.id, ManualStatus.ENTERED)
                result.marked_entered += 1

    if proc.returncode not in (0, 2) and not result.error:
        result.error = f"Bot exited with code {proc.returncode}"
    return result


def _job_matched(giveaway: Giveaway, url: str, ok_items: list[dict[str, Any]]) -> bool:
    cid = (giveaway.platform_campaign_id or "").strip()
    for item in ok_items:
        item_id = str(item.get("id") or "")
        item_url = str(item.get("url") or "")
        if cid and item_id and cid == item_id:
            return True
        if item_id and item_id in url:
            return True
        if item_url and (item_url.rstrip("/") in url or url.rstrip("/") in item_url):
            return True
    return False


def _parse_bot_summary(stdout: str) -> dict[str, Any] | None:
    """Last JSON object line from bot stdout."""
    for line in reversed((stdout or "").splitlines()):
        text = line.strip()
        if not text.startswith("{"):
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and "ok" in data and "failed" in data:
            return data
    return None


def _trim(text: str | None, limit: int = 800) -> str:
    raw = (text or "").strip()
    if len(raw) <= limit:
        return raw
    return raw[-limit:]
