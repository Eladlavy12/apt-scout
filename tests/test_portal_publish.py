import json

import pytest

from apt_scout.__main__ import main
from apt_scout.adapters.base import AdapterResult
from apt_scout.filters import Filters
from apt_scout.models import Listing, Occupancy
from apt_scout.pipeline import run_pipeline
from apt_scout.state import StateStore


class StubAdapter:
    name = "yad2"

    def fetch(self, fetcher, config, since):
        return AdapterResult(
            source="yad2",
            listings=[
                Listing(
                    source="yad2",
                    source_id="1",
                    url="https://y/1",
                    price=4800,
                    rooms=3.0,
                    size_sqm=70.0,
                    occupancy=Occupancy.WHOLE,
                )
            ],
        )


class SilentNotifier:
    def send_listing(self, listing):
        return True


class TestReportCarriesListings:
    def test_report_exposes_enriched_listings_for_the_portal(self, tmp_path):
        # The portal shows everything recent, not only what passed the alert
        # filter, so the report must carry all of them.
        report = run_pipeline(
            adapters=[StubAdapter()],
            fetcher=None,
            sources_config={"yad2": {"enabled": True}},
            filters=Filters(),
            store=StateStore(tmp_path),
            notifier=SilentNotifier(),
        )
        assert len(report.listings) == 1
        assert report.listings[0].source_id == "1"


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "filters.json").write_text(
        json.dumps({"min_price": 4000, "max_price": 5500}), encoding="utf-8"
    )
    (tmp_path / "config" / "sources.json").write_text(
        json.dumps({"yad2": {"enabled": False}}), encoding="utf-8"
    )
    return tmp_path


class TestCli:
    def test_build_portal_flag_writes_the_site(self, repo):
        exit_code = main(
            ["--repo", str(repo), "--dry-run", "--build-portal", "--portal-dir", "site"]
        )
        assert exit_code == 0
        assert (repo / "site" / "index.html").exists()
        assert (repo / "site" / "data" / "listings.json").exists()

    def test_no_portal_is_written_without_the_flag(self, repo):
        main(["--repo", str(repo), "--dry-run"])
        assert not (repo / "site").exists()
