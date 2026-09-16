"""CLI entrypoint: python -m app.cli <command>."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from uuid import UUID

import click

from app import __version__
from app.config import get_settings
from app.db.connection import connection
from app.db.migrate import apply_migrations, list_migration_files, migration_status
from app.gemini.service import analyze_giveaways
from app.logging_config import setup_logging
from app.pipeline import run_pipeline
from app.scraping.runner import crawl_all
from app.scraping.seed import seed_sources

logger = logging.getLogger(__name__)


def _parse_uuid(value: str | None, label: str) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError as exc:
        raise click.BadParameter(f"Invalid {label} UUID: {value}") from exc


@click.group()
@click.version_option(version=__version__, prog_name="collector")
@click.option(
    "--log-level",
    envvar="LOG_LEVEL",
    default="INFO",
    show_default=True,
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], case_sensitive=False),
    help="Logging level (overrides LOG_LEVEL when set on the CLI).",
)
@click.pass_context
def main(ctx: click.Context, log_level: str) -> None:
    """Giveaway collector — crawl, analyze, and store discoveries in Neon."""
    setup_logging(log_level.upper())
    ctx.ensure_object(dict)
    ctx.obj["log_level"] = log_level.upper()


@main.command("db-init")
def db_init() -> None:
    """Apply pending SQL migrations (additive only; never drops data)."""
    settings = get_settings()
    files = list_migration_files()
    if not files:
        click.echo("No migration files found.", err=True)
        sys.exit(1)

    with connection(settings) as conn:
        before = migration_status(conn)
        applied = apply_migrations(conn)
        after = migration_status(conn)

    if applied:
        click.echo(f"Applied {len(applied)} migration(s):")
        for name in applied:
            click.echo(f"  + {name}")
    else:
        click.echo("Database schema is up to date.")

    pending = [name for name, ok in after.items() if not ok]
    if pending:
        click.echo(f"Pending: {', '.join(pending)}", err=True)
        sys.exit(1)

    skipped = [name for name, ok in before.items() if ok]
    if skipped and not applied:
        for name in skipped:
            click.echo(f"  = {name} (already applied)")

    logger.info("db-init complete applied=%s", applied)


@main.command("seed-sources")
@click.argument(
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=Path("config/sources.example.json"),
)
def seed_sources_cmd(config_path: Path) -> None:
    """Upsert crawl sources from a JSON config file into Neon."""
    settings = get_settings()
    with connection(settings) as conn:
        apply_migrations(conn)
        seeded = seed_sources(conn, config_path)
    click.echo(f"Seeded {len(seeded)} source(s) from {config_path}:")
    for source in seeded:
        click.echo(f"  {source.id}  enabled={source.enabled}  {source.name}  {source.base_url}")


@main.command("seed")
@click.option(
    "--examples",
    is_flag=True,
    default=False,
    help="Seed config/sources.example.json (dev fixtures) instead of real aggregators.",
)
def seed_cmd(examples: bool) -> None:
    """Seed real French giveaway aggregators (or examples with --examples)."""
    path = (
        Path("config/sources.example.json")
        if examples
        else Path("config/sources.real.json")
    )
    if not path.is_file():
        click.echo(f"Missing sources file: {path}", err=True)
        sys.exit(1)
    settings = get_settings()
    with connection(settings) as conn:
        apply_migrations(conn)
        seeded = seed_sources(conn, path)
    click.echo(f"Seeded {len(seeded)} source(s) from {path}:")
    for source in seeded:
        profile = (source.crawl_config or {}).get("profile", "example")
        click.echo(
            f"  {source.id}  profile={profile}  enabled={source.enabled}  "
            f"{source.name}  {source.base_url}"
        )


@main.command("crawl")
@click.option(
    "--source",
    "source_id",
    default=None,
    help="Crawl a single source UUID (skips due-schedule filter).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Discover and print candidates without writing giveaways.",
)
@click.option(
    "--all-enabled",
    is_flag=True,
    default=False,
    help="Crawl every enabled source, not only those due.",
)
@click.option(
    "--real-test",
    is_flag=True,
    default=False,
    help=(
        "Conservative first live experiment: max 10 pages/source, depth 1, "
        "concurrency 2/1, real-profile sources only, diagnostics, no Gemini."
    ),
)
def crawl(
    source_id: str | None,
    dry_run: bool,
    all_enabled: bool,
    real_test: bool,
) -> None:
    """Crawl configured sources and save giveaway candidates (no Gemini)."""
    from app.scraping.diagnostics import (
        build_candidate_diagnostics,
        count_would_analyze,
        summarize_source_candidates,
    )

    settings = get_settings()
    parsed_id = _parse_uuid(source_id, "source")

    # real-test never calls Gemini (crawl path has no Gemini). Force diagnostics.
    show_diagnostics = dry_run or real_test
    only_due = not all_enabled and parsed_id is None and not real_test
    real_profile_only = real_test and parsed_id is None

    with connection(settings) as conn:
        apply_migrations(conn)
        results = crawl_all(
            conn,
            settings,
            source_id=parsed_id,
            dry_run=dry_run,
            only_due=only_due,
            real_test=real_test,
            real_profile_only=real_profile_only,
        )

    if not results:
        click.echo(
            "No sources to crawl. Run `python -m app.cli seed` then retry, "
            "or pass --source / --all-enabled."
        )
        return

    total_pages = 0
    total_candidates = 0
    total_would = 0
    total_errors = 0

    for result in results:
        threshold = result.candidate_threshold
        would = count_would_analyze(result.candidates, threshold=threshold)
        total_pages += result.pages_fetched
        total_candidates += result.candidates_found
        total_would += would
        total_errors += result.errors_count

        click.echo("")
        click.echo(result.source_name)
        click.echo(f"Pages fetched: {result.pages_fetched}")
        click.echo(f"Candidates: {result.candidates_found}")
        if show_diagnostics:
            summary = summarize_source_candidates(
                source_name=result.source_name,
                pages_fetched=result.pages_fetched,
                candidates=result.candidates,
                threshold=threshold,
            )
            click.echo(f"Worldwide/France: {summary.france_eligible}")
            click.echo(f"France ineligible: {summary.france_ineligible}")
            click.echo(f"France unknown: {summary.france_unknown}")
            click.echo(f"Wanted prizes: {summary.wanted}")
            click.echo(f"Unwanted: {summary.unwanted}")
            click.echo(f"Dead: {summary.dead_urls}")
            click.echo(f"Duplicates: {summary.duplicates}")
            click.echo(f"Would keep: {summary.would_keep}")
            click.echo(f"Would analyze: {would}")
        else:
            click.echo(
                f"Created: {result.giveaways_created}  Updated: {result.giveaways_updated}"
            )
        click.echo(f"Errors: {result.errors_count}")
        if result.error_summary:
            click.echo(f"  note: {result.error_summary}", err=True)

        if show_diagnostics:
            for item in result.candidates:
                diag = build_candidate_diagnostics(
                    item,
                    source_name=result.source_name,
                    threshold=threshold,
                )
                click.echo("")
                for line in diag.format_lines():
                    click.echo(line)

    click.echo("")
    click.echo("TOTAL")
    click.echo(f"Pages fetched: {total_pages}")
    click.echo(f"Candidates: {total_candidates}")
    if show_diagnostics:
        click.echo(f"Would analyze: {total_would}")
    click.echo(f"Errors: {total_errors}")
    if dry_run:
        click.echo("(dry-run, nothing written; Gemini not invoked)")
    elif real_test:
        click.echo("(real-test crawl complete; Gemini not invoked)")


@main.command("analyze")
@click.option(
    "--limit",
    default=50,
    show_default=True,
    type=int,
    help="Max giveaways to consider (ignored with --all).",
)
@click.option(
    "--all",
    "analyze_all",
    is_flag=True,
    default=False,
    help="Process the entire pending queue until empty (mutually exclusive with --limit).",
)
@click.option("--giveaway", "giveaway_id", default=None, help="Analyze a single giveaway UUID.")
@click.option(
    "--reanalyze",
    is_flag=True,
    default=False,
    help="Include rows already analyzed (forces Gemini again unless other skips apply).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="List what would be analyzed without calling Gemini or writing.",
)
@click.pass_context
def analyze(
    ctx: click.Context,
    limit: int,
    analyze_all: bool,
    giveaway_id: str | None,
    reanalyze: bool,
    dry_run: bool,
) -> None:
    """Run Gemini structured analysis on giveaway candidates."""
    from app.gemini.service import analyze_all_pending

    if analyze_all and giveaway_id:
        raise click.UsageError("--all and --giveaway are mutually exclusive")
    if analyze_all and ctx.get_parameter_source("limit") is not click.core.ParameterSource.DEFAULT:
        raise click.UsageError("--all and --limit are mutually exclusive")

    settings = get_settings()
    parsed_id = _parse_uuid(giveaway_id, "giveaway")

    with connection(settings) as conn:
        apply_migrations(conn)
        if analyze_all:

            def _progress(event: dict) -> None:
                kind = event.get("event")
                if kind == "start":
                    click.echo(f"Pending at start: {event['pending']}")
                    click.echo("")
                elif kind == "batch":
                    click.echo(f"Batch {event['batch']}: {event['analyzed']} analyzed")
                    click.echo(f"Remaining: {event['remaining']}")
                    click.echo("")
                elif kind == "done":
                    click.echo("Analyze complete")

            all_result = analyze_all_pending(
                conn,
                settings,
                reanalyze=reanalyze,
                dry_run=dry_run,
                on_progress=_progress,
            )
            batch = all_result.result
        else:
            batch = analyze_giveaways(
                conn,
                settings,
                limit=limit,
                giveaway_id=parsed_id,
                reanalyze=reanalyze,
                dry_run=dry_run,
            )

    click.echo(
        "Analyze\n"
        f"giveaways_processed={batch.processed}\n"
        f"api_requests={batch.api_requests}\n"
        f"analyzed={batch.analyzed}\n"
        f"pending={batch.pending}\n"
        f"skipped={batch.skipped}\n"
        f"active={batch.confirmed}\n"
        f"expired={batch.expired}\n"
        f"rejected={batch.rejected}\n"
        f"uncertain={batch.uncertain}\n"
        f"errors={batch.errors}"
        + ("\n(dry-run)" if dry_run else "")
    )
    if not analyze_all:
        for item in batch.items:
            if item.error:
                click.echo(f"  ERROR {item.giveaway_id} {item.error}", err=True)
            elif item.skipped:
                click.echo(f"  skip {item.skip_reason} {item.canonical_url}")
            elif dry_run:
                click.echo(f"  would-analyze {item.canonical_url}")
            else:
                click.echo(
                    f"  {item.status} conf={item.confidence!s} "
                    f"is_giveaway={item.is_giveaway} {item.canonical_url}"
                )


@main.command("pipeline")
@click.option("--source", "source_id", default=None, help="Limit crawl to one source UUID.")
@click.option("--limit", default=100, show_default=True, type=int, help="Max Gemini analyses.")
@click.option(
    "--all-enabled",
    is_flag=True,
    default=False,
    help="Crawl every enabled source, not only those due.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Crawl+queue preview without writing giveaways or calling Gemini.",
)
def pipeline(source_id: str | None, limit: int, all_enabled: bool, dry_run: bool) -> None:
    """Crawl → identify candidates → analyze new/changed → print summary."""
    settings = get_settings()
    parsed_id = _parse_uuid(source_id, "source")

    with connection(settings) as conn:
        apply_migrations(conn)
        summary = run_pipeline(
            conn,
            settings,
            source_id=parsed_id,
            analyze_limit=limit,
            only_due=not all_enabled and parsed_id is None,
            dry_run=dry_run,
        )

    click.echo(summary.format())
    if dry_run:
        click.echo("(dry-run: no giveaway writes, no Gemini calls)")


@main.command("stats")
def stats_cmd() -> None:
    """Query Neon and print collector counters."""
    from app.db.stats import fetch_collector_stats

    settings = get_settings()
    with connection(settings) as conn:
        apply_migrations(conn)
        stats = fetch_collector_stats(conn)
    for line in stats.as_lines():
        click.echo(line)


@main.command("health")
@click.option(
    "--max-heartbeat-age",
    default=600,
    show_default=True,
    type=int,
    help="When a heartbeat file exists, fail if older than this many seconds.",
)
def health_cmd(max_heartbeat_age: int) -> None:
    """Exit 0 if DB is reachable (and heartbeat is fresh when present)."""
    import time
    from pathlib import Path

    from psycopg import Error as PsycopgError

    settings = get_settings()
    try:
        with connection(settings) as conn:
            conn.execute("SELECT 1")
    except (OSError, PsycopgError):
        # Do not echo driver messages — they can embed connection details.
        click.echo("unhealthy: database", err=True)
        sys.exit(1)

    heartbeat = Path(settings.worker_heartbeat_path)
    if heartbeat.is_file():
        age = time.time() - heartbeat.stat().st_mtime
        if age > max_heartbeat_age:
            click.echo(f"unhealthy: heartbeat stale age={age:.0f}s", err=True)
            sys.exit(1)

    click.echo("ok")


@main.command("purge-giveaways")
@click.option(
    "--yes",
    is_flag=True,
    default=False,
    help="Skip interactive confirmation (required for non-interactive runs).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show how many rows would be deleted without deleting.",
)
def purge_giveaways_cmd(yes: bool, dry_run: bool) -> None:
    """DELETE giveaway discovery data; preserve sources/schema/migrations."""
    from app.db.purge import plan_purge_giveaways, purge_giveaways

    settings = get_settings()
    with connection(settings) as conn:
        apply_migrations(conn)
        plan = plan_purge_giveaways(conn)
        click.echo(
            f"Would delete giveaways={plan.giveaways} crawl_runs={plan.crawl_runs} "
            f"(total={plan.total})"
        )
        if dry_run:
            click.echo("(dry-run, nothing deleted; sources preserved)")
            return
        if not yes:
            click.confirm(
                "Permanently delete all giveaways and crawl_runs?",
                abort=True,
            )
        deleted = purge_giveaways(conn)
        conn.commit()
    click.echo(
        f"Deleted giveaways={deleted.giveaways} crawl_runs={deleted.crawl_runs}. "
        "Sources/schema/migrations preserved."
    )


@main.command("validate-links")
@click.option(
    "--limit",
    default=50,
    show_default=True,
    type=int,
    help="Max giveaways to check per run (ignored with --all).",
)
@click.option(
    "--all",
    "all_pending",
    is_flag=True,
    default=False,
    help="Keep validating in bounded batches until the queue is empty.",
)
def validate_links_cmd(limit: int, all_pending: bool) -> None:
    """Validate entry URLs via Scrapling HTTP (bounded batches)."""
    from app.validation.links import validate_giveaway_links

    settings = get_settings()
    with connection(settings) as conn:
        apply_migrations(conn)
        result = validate_giveaway_links(
            conn,
            settings,
            limit=limit,
            all_pending=all_pending,
        )
        conn.commit()
    click.echo(
        "Validate links\n"
        f"checked={result.checked}\n"
        f"live={result.live}\n"
        f"gone={result.gone}\n"
        f"temporary_error={result.temporary_error}\n"
        f"blocked={result.blocked}\n"
        f"unknown={result.unknown}\n"
        f"rejected={result.rejected}\n"
        f"errors={result.errors}"
    )


@main.command("reprioritize-entry")
@click.option(
    "--limit",
    default=500,
    show_default=True,
    type=int,
    help="Max rows to re-evaluate per run.",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Re-evaluate even when entry_acceptable is already set.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Compute classifications without writing.",
)
def reprioritize_entry_cmd(limit: int, force: bool, dry_run: bool) -> None:
    """Backfill public-social entry gate from stored text (no re-crawl)."""
    from app.extraction.entry_acceptability_backfill import backfill_entry_acceptability

    settings = get_settings()
    with connection(settings) as conn:
        apply_migrations(conn)
        summary = backfill_entry_acceptability(
            conn,
            limit=limit,
            force=force,
            dry_run=dry_run,
        )
        if not dry_run:
            conn.commit()
    click.echo(
        "Reprioritize entry acceptability\n"
        f"scanned={summary.scanned}\n"
        f"updated={summary.updated}\n"
        f"rejected={summary.rejected}\n"
        f"acceptable={summary.acceptable}\n"
        f"unknown={summary.unknown}\n"
        f"unchanged={summary.unchanged}\n"
        f"dry_run={dry_run}"
    )


@main.command("reset-crawl-schedule")
def reset_crawl_schedule_cmd() -> None:
    """Make all enabled sources due for crawl immediately."""
    from app.db.purge import reset_crawl_schedule

    settings = get_settings()
    with connection(settings) as conn:
        apply_migrations(conn)
        n = reset_crawl_schedule(conn)
        conn.commit()
    click.echo(f"Reset crawl schedule for {n} enabled source(s).")


@main.command("worker")
def worker_cmd() -> None:
    """Run the continuous scheduler (crawl due sources → analyze → sleep)."""
    from app.worker import run_worker

    settings = get_settings()
    # Apply schema once before entering the loop.
    with connection(settings) as conn:
        apply_migrations(conn)
    run_worker(settings)


if __name__ == "__main__":
    main()
