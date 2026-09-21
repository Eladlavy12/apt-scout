from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .collect import run_collection, settings_from_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="apt-scout-fb-groups")
    parser.add_argument("--repo", default=".")
    args = parser.parse_args(argv)
    root = Path(args.repo)
    sources = json.loads((root / "config" / "sources.json").read_text(encoding="utf-8"))
    settings = settings_from_config(sources.get("fb_groups", {}))
    try:
        report = run_collection(root, datetime.now(timezone.utc), settings)
    except OSError as exc:
        print(f"ERROR: could not write the feed: {exc}", file=sys.stderr)
        return 1
    if report.skipped:
        print(f"fb_groups: skipped ({report.skipped})")
    else:
        outcomes = ", ".join(f"{g}={o}" for g, o in report.outcomes.items()) or "no group due"
        print(f"fb_groups: visited {len(report.visited)} ({outcomes}); posts_added={report.posts_added} feed_size={report.feed_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
