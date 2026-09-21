"""Manual check: visit ONE group anonymously and print the records (ids,
times, text lengths only). Never run on CI. Usage:
    .venv\\Scripts\\python.exe scripts\\fb_groups_smoke.py ApartmentsTelAviv
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from apt_scout.fb_groups.browser import visit_group  # noqa: E402

group = sys.argv[1] if len(sys.argv) > 1 else "ApartmentsTelAviv"
result = visit_group(group, datetime.now(timezone.utc))
print("outcome:", result.outcome, "| error:", result.error, "| title:", ascii(result.title))
for post in result.posts:
    print(post["post_id"], post["posted_at"], len(post["text"]), "chars", len(post["photos"]), "photos")
