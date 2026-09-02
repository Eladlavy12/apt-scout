"""CLI run on the user's PC to build a local yad2 feed file.

yad2 blocks GitHub's servers at every fetch tier, but works fine from a real
Chrome on the user's own machine (see the browser fallback in
`adapters/yad2.py`, gated by APT_SCOUT_BROWSER_HEADED=1). Rather than run the
whole pipeline locally, this script does exactly one thing: fetch yad2 fresh
and commit the raw listings to `state/feeds/yad2.json`. The cloud's hourly
run then treats that file as yad2's input when it's fresh (see
`Yad2Adapter._load_feed`) and does everything else - enrich, cluster, alert,
build the portal. No secrets need to live on the PC, and the local job owns
exactly one file, so there is no state conflict with the cloud run.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .__main__ import build_runtime
from .models import Listing
from .serialise import serialise_listing


def _find_adapter(adapters: list, name: str):
    for adapter in adapters:
        if adapter.name == name:
            return adapter
    return None


def fetch_feed(repo_root: Path, env: dict, source: str) -> tuple[list[Listing], str | None]:
    """Fetch `source` fresh via the normal runtime construction.

    The runtime is built dry-run (no Telegram credentials required). The
    source's own `feed_file` is stripped from its config before the fetch so
    the adapter can't just read back the file this script is about to write
    - it always hits the real network/browser path here.

    Returns (listings, error); error is None on success. Never raises: a
    misbehaving adapter or runtime failure becomes an error string, exactly
    like every other adapter failure in this codebase.
    """
    try:
        runtime = build_runtime(Path(repo_root), env, dry_run=True)
    except Exception as exc:  # noqa: BLE001 - reported, never raised
        return [], f"failed to build runtime: {type(exc).__name__}: {exc}"

    adapter = _find_adapter(runtime.adapters, source)
    if adapter is None:
        return [], f"no adapter registered for source {source!r}"

    config = dict(runtime.sources_config.get(source, {}))
    config.pop("feed_file", None)

    try:
        result = adapter.fetch(runtime.fetcher, config, since=None)
    except Exception as exc:  # noqa: BLE001 - reported, never raised
        return [], f"{type(exc).__name__}: {exc}"

    return result.listings, result.error


def write_feed(
    out_path: Path, source: str, listings: list[Listing], fetched_at: datetime
) -> None:
    """Write the feed file atomically (tmp + os.replace)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    payload = {
        "source": source,
        "fetched_at": fetched_at.isoformat(),
        "listings": [serialise_listing(item) for item in listings],
    }
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(tmp, out_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="apt-scout-local-feed")
    parser.add_argument("--repo", default=".", help="Repository root")
    parser.add_argument("--source", default="yad2", help="Source name to fetch")
    parser.add_argument(
        "--out", default=None, help="Feed output path, repo-relative"
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo)
    out_path = repo_root / (args.out or f"state/feeds/{args.source}.json")

    listings, error = fetch_feed(repo_root, dict(os.environ), args.source)
    if error is not None:
        print(f"ERROR: {args.source} fetch failed: {error}", file=sys.stderr)
        return 1

    fetched_at = datetime.now(timezone.utc)
    write_feed(out_path, args.source, listings, fetched_at)
    print(
        f"wrote {len(listings)} {args.source} listings to {out_path} "
        f"at {fetched_at.isoformat()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
