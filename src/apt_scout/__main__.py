from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .adapters.yad2 import Yad2Adapter
from .enrich.pipeline_enrichers import build_enrichers
from .fetch import Fetcher, HttpTransport
from .filters import Filters
from .health import HealthTracker
from .notify.telegram import TelegramNotifier
from .pipeline import run_pipeline
from .portal.builder import build_portal
from .state import StateStore


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


def build_runtime(repo_root: Path, env: dict, dry_run: bool = False) -> Runtime:
    repo_root = Path(repo_root)
    filters = Filters.load(repo_root / "config" / "filters.json")
    sources_config = json.loads(
        (repo_root / "config" / "sources.json").read_text(encoding="utf-8")
    )
    store = StateStore(repo_root / "state")

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
        notifier = TelegramNotifier(token, chat_id)

    salt = env.get("PHONE_HASH_SALT", "apt-scout-default-salt")
    fetcher = Fetcher({"http": HttpTransport()}, ["http", "browser", "apify"])
    return Runtime(
        filters=filters,
        sources_config=sources_config,
        store=store,
        notifier=notifier,
        fetcher=fetcher,
        adapters=[Yad2Adapter()],
        enrichers=build_enrichers(store, salt=salt),
    )


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
    report = run_pipeline(
        adapters=runtime.adapters,
        fetcher=runtime.fetcher,
        sources_config=runtime.sources_config,
        filters=runtime.filters,
        store=runtime.store,
        notifier=runtime.notifier,
        enrichers=runtime.enrichers,
    )

    if args.build_portal:
        build_portal(
            output_dir=Path(args.repo) / args.portal_dir,
            listings=report.listings,
            health=HealthTracker(runtime.store).report(),
            filters=runtime.filters,
            generated_at=datetime.now(timezone.utc),
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
