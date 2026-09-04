from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .adapters.fb_marketplace import FbMarketplaceAdapter
from .adapters.homeless import HomelessAdapter
from .adapters.komo import KomoAdapter
from .adapters.onmap import OnmapAdapter
from .adapters.prog import ProgAdapter
from .adapters.yad2 import Yad2Adapter
from .budget import BudgetGuard
from .enrich.neighborhood import NeighborhoodEnricher, load_neighborhood_data
from .enrich.pipeline_enrichers import build_enrichers
from .fetch import CurlTransport, Fetcher, HttpTransport
from .filters import Filters
from .health import HealthTracker
from .notify.commands import process_commands
from .notify.telegram import TelegramNotifier
from .pipeline import RunReport, run_pipeline
from .portal.builder import build_portal
from .scheduler import CadenceGate
from .state import StateStore

PROG_SEEN_PREFIX = "prog:"


class DryRunNotifier:
    """Records what would have been sent, so runs can be rehearsed safely."""

    def __init__(self) -> None:
        self.sent: list[Any] = []

    def send_listing(self, listing: Any) -> bool:
        self.sent.append(listing)
        return True

    def send_text(self, text: str) -> bool:
        self.sent.append(text)
        return True


@dataclass
class Runtime:
    filters: Filters
    sources_config: dict
    store: StateStore
    notifier: Any
    fetcher: Fetcher
    adapters: list
    enrichers: list
    cluster_salt: str
    chat_id: str | None = None
    knowledge: Any = None


def build_runtime(repo_root: Path, env: dict, dry_run: bool = False) -> Runtime:
    repo_root = Path(repo_root)
    filters = Filters.load(repo_root / "config" / "filters.json")
    sources_config = json.loads(
        (repo_root / "config" / "sources.json").read_text(encoding="utf-8")
    )
    store = StateStore(repo_root / "state")

    # Some adapters (yad2's local feed) need to resolve a repo-relative path
    # themselves, so every source config carries the repo root.
    for config in sources_config.values():
        config["repo_root"] = str(repo_root)

    # The fetch window follows the alert filters (with a margin), so a
    # threshold changed over Telegram widens what is fetched on the next run
    # instead of being clipped by a stale sources.json. Applies to every
    # source that declares "follows_filters": true (yad2, onmap, komo);
    # sources with no such price/rooms params (homeless, prog) don't.
    for config in sources_config.values():
        if config.get("follows_filters"):
            config["price_min"] = max(0, filters.min_price - 500)
            config["price_max"] = filters.max_price + 500
            config["rooms_min"] = filters.min_rooms

    # prog has no query params to narrow its board by price/rooms, so
    # instead it skips re-fetching detail pages for listings we've already
    # recorded (bare ids, without the "source:" prefix state uses).
    prog = sources_config.get("prog")
    if prog is not None:
        prog["skip_ids"] = sorted(
            seen_id[len(PROG_SEEN_PREFIX) :]
            for seen_id in store.seen_ids()
            if seen_id.startswith(PROG_SEEN_PREFIX)
        )

    # fb_marketplace is a paid Apify source; the token is a secret and must
    # come from the environment, never from the committed sources.json.
    fb_marketplace = sources_config.get("fb_marketplace")
    if fb_marketplace is not None:
        fb_marketplace["token"] = env.get("APIFY_TOKEN")

    index, knowledge = load_neighborhood_data(repo_root / "data")

    if dry_run:
        notifier: Any = DryRunNotifier()
    else:
        token = env.get("TELEGRAM_BOT_TOKEN")
        chat_id = env.get("TELEGRAM_CHAT_ID")
        if not token or not chat_id:
            raise RuntimeError(
                "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set "
                "(or pass --dry-run)"
            )
        notifier = TelegramNotifier(token, chat_id, knowledge=knowledge)

    salt = env.get("PHONE_HASH_SALT")
    if not salt:
        salt = "apt-scout-default-salt"
        if not dry_run:
            print(
                "WARNING: PHONE_HASH_SALT is not set; "
                "phone hashes use the built-in default salt",
                file=sys.stderr,
            )
    fetcher = Fetcher(
        {"http": HttpTransport(), "curl": CurlTransport()},
        ["http", "curl", "browser", "apify"],
    )
    budget = BudgetGuard(store, notifier=notifier)
    return Runtime(
        filters=filters,
        sources_config=sources_config,
        store=store,
        notifier=notifier,
        fetcher=fetcher,
        adapters=[
            Yad2Adapter(),
            OnmapAdapter(),
            KomoAdapter(),
            HomelessAdapter(),
            ProgAdapter(),
            FbMarketplaceAdapter(budget),
        ],
        enrichers=build_enrichers(
            store,
            salt=salt,
            neighborhood=NeighborhoodEnricher(store, index, knowledge),
        ),
        cluster_salt=salt,
        chat_id=env.get("TELEGRAM_CHAT_ID"),
        knowledge=knowledge,
    )


def should_build_portal(report: RunReport, sources_config: dict) -> bool:
    """Whether this run produced something worth publishing.

    A run in which every enabled source failed and nothing was fetched must
    not replace the live portal with an empty page; keeping the previous
    portal online is strictly better than showing a falsely quiet market.

    The same goes for a run in which no enabled source even attempted a
    fetch - e.g. a workflow_dispatch fired inside every source's cadence
    window, gating them all. Nothing ran, so nothing can be newer than the
    live portal; `report.attempted` (not the error map) is what tells that
    apart from "everything ran and found nothing".
    """
    if report.fetched > 0:
        return True
    enabled = [
        name
        for name, config in sources_config.items()
        if config.get("enabled", True)
    ]
    if not enabled:
        return True
    if not report.attempted:
        return False
    return not all(name in report.errors for name in enabled)


HEALTH_WARNED = "health_warned"
FAILURE_WARNING_THRESHOLD = 3


def warn_about_failing_sources(
    store: StateStore, notifier: Any, threshold: int = FAILURE_WARNING_THRESHOLD
) -> list[str]:
    """Send one Telegram warning when a source starts failing repeatedly.

    The already-warned set lives in state, so an hourly schedule does not
    repeat the same warning every run; a recovery clears the flag, so a
    relapse warns again.
    """
    failing = HealthTracker(store).failing_sources(threshold=threshold)
    warned = store.load(HEALTH_WARNED, [])
    newly_failing = [source for source in failing if source not in warned]
    for source in newly_failing:
        notifier.send_text(f"⚠️ מקור {source} נכשל {threshold} פעמים ברצף")
    if sorted(failing) != sorted(warned):
        store.save(HEALTH_WARNED, sorted(failing))
    return newly_failing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="apt-scout")
    parser.add_argument("--repo", default=".", help="Repository root")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the full pipeline without sending notifications",
    )
    parser.add_argument(
        "--build-portal", action="store_true", help="Generate the static portal"
    )
    parser.add_argument(
        "--portal-dir", default="site", help="Where to write the portal"
    )
    args = parser.parse_args(argv)

    runtime = build_runtime(Path(args.repo), dict(os.environ), dry_run=args.dry_run)

    if not args.dry_run:
        runtime.filters = process_commands(
            runtime.notifier,
            runtime.store,
            runtime.filters,
            Path(args.repo) / "config" / "filters.json",
            chat_id=runtime.chat_id or "",
            knowledge=runtime.knowledge,
        )

    report = run_pipeline(
        adapters=runtime.adapters,
        fetcher=runtime.fetcher,
        sources_config=runtime.sources_config,
        filters=runtime.filters,
        store=runtime.store,
        notifier=runtime.notifier,
        enrichers=runtime.enrichers,
        gate=CadenceGate(runtime.store),
        cluster_salt=runtime.cluster_salt,
    )

    if not args.dry_run:
        warn_about_failing_sources(runtime.store, runtime.notifier)

    if args.build_portal:
        if should_build_portal(report, runtime.sources_config):
            build_portal(
                output_dir=Path(args.repo) / args.portal_dir,
                listings=report.listings,
                health=HealthTracker(runtime.store).report(),
                filters=runtime.filters,
                generated_at=datetime.now(timezone.utc),
                knowledge=runtime.knowledge,
            )
        else:
            reason = (
                "no source was due to run (cadence-gated)"
                if not report.attempted
                else "every enabled source failed"
            )
            print(
                f"WARNING: {reason}; "
                "keeping the previous portal instead of publishing an empty one",
                file=sys.stderr,
            )

    print(
        f"fetched={report.fetched} new={report.new} "
        f"matched={report.matched} notified={report.notified}"
    )
    for source, error in report.errors.items():
        print(f"  ERROR {source}: {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
