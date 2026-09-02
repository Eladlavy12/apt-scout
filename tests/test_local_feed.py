import json
from dataclasses import dataclass, field
from typing import Any

import pytest

import apt_scout.local_feed as local_feed
from apt_scout.adapters.base import AdapterResult
from apt_scout.models import Listing, Occupancy


def make_listing(source_id="1") -> Listing:
    return Listing(
        source="yad2",
        source_id=source_id,
        url=f"https://y/{source_id}",
        price=5000,
        rooms=3.0,
        occupancy=Occupancy.WHOLE,
    )


class StubAdapter:
    def __init__(self, name, result: AdapterResult):
        self.name = name
        self._result = result
        self.calls: list[dict] = []

    def fetch(self, fetcher, config, since):
        self.calls.append(config)
        return self._result


@dataclass
class StubRuntime:
    sources_config: dict
    adapters: list
    fetcher: Any = None
    filters: Any = None
    store: Any = None
    notifier: Any = None
    enrichers: list = field(default_factory=list)
    cluster_salt: str = ""
    chat_id: str | None = None


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "config").mkdir()
    return tmp_path


class TestFetchFeed:
    def test_success_returns_listings_and_no_error(self, repo, monkeypatch):
        adapter = StubAdapter("yad2", AdapterResult(source="yad2", listings=[make_listing()]))
        runtime = StubRuntime(
            sources_config={"yad2": {"feed_file": "state/feeds/yad2.json", "url_template": "x"}},
            adapters=[adapter],
        )
        monkeypatch.setattr(local_feed, "build_runtime", lambda *a, **k: runtime)

        listings, error = local_feed.fetch_feed(repo, {}, "yad2")

        assert error is None
        assert len(listings) == 1

    def test_feed_file_is_stripped_so_the_adapter_hits_the_network(self, repo, monkeypatch):
        adapter = StubAdapter("yad2", AdapterResult(source="yad2", listings=[]))
        runtime = StubRuntime(
            sources_config={"yad2": {"feed_file": "state/feeds/yad2.json"}},
            adapters=[adapter],
        )
        monkeypatch.setattr(local_feed, "build_runtime", lambda *a, **k: runtime)

        local_feed.fetch_feed(repo, {}, "yad2")

        assert "feed_file" not in adapter.calls[0]

    def test_error_result_is_reported(self, repo, monkeypatch):
        adapter = StubAdapter("yad2", AdapterResult(source="yad2", error="blocked"))
        runtime = StubRuntime(sources_config={"yad2": {}}, adapters=[adapter])
        monkeypatch.setattr(local_feed, "build_runtime", lambda *a, **k: runtime)

        listings, error = local_feed.fetch_feed(repo, {}, "yad2")

        assert listings == []
        assert error == "blocked"

    def test_unknown_source_is_an_error(self, repo, monkeypatch):
        runtime = StubRuntime(sources_config={}, adapters=[])
        monkeypatch.setattr(local_feed, "build_runtime", lambda *a, **k: runtime)

        listings, error = local_feed.fetch_feed(repo, {}, "yad2")

        assert listings == []
        assert error is not None


class TestWriteFeed:
    def test_writes_the_expected_shape(self, tmp_path):
        from datetime import datetime, timezone

        out_path = tmp_path / "state" / "feeds" / "yad2.json"
        fetched_at = datetime(2026, 9, 2, 18, 45, tzinfo=timezone.utc)
        local_feed.write_feed(out_path, "yad2", [make_listing()], fetched_at)

        data = json.loads(out_path.read_text(encoding="utf-8"))
        assert data["source"] == "yad2"
        assert data["fetched_at"] == fetched_at.isoformat()
        assert len(data["listings"]) == 1
        assert data["listings"][0]["source_id"] == "1"


class TestMain:
    def test_success_writes_the_feed_and_exits_zero(self, repo, monkeypatch):
        adapter = StubAdapter("yad2", AdapterResult(source="yad2", listings=[make_listing()]))
        runtime = StubRuntime(sources_config={"yad2": {}}, adapters=[adapter])
        monkeypatch.setattr(local_feed, "build_runtime", lambda *a, **k: runtime)

        code = local_feed.main(["--repo", str(repo)])

        assert code == 0
        out = repo / "state" / "feeds" / "yad2.json"
        assert out.exists()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert len(data["listings"]) == 1

    def test_error_keeps_the_existing_feed_and_exits_one(self, repo, monkeypatch, capsys):
        out = repo / "state" / "feeds" / "yad2.json"
        out.parent.mkdir(parents=True)
        out.write_text('{"source": "yad2", "fetched_at": "x", "listings": []}', encoding="utf-8")

        adapter = StubAdapter("yad2", AdapterResult(source="yad2", error="blocked"))
        runtime = StubRuntime(sources_config={"yad2": {}}, adapters=[adapter])
        monkeypatch.setattr(local_feed, "build_runtime", lambda *a, **k: runtime)

        code = local_feed.main(["--repo", str(repo)])

        assert code == 1
        assert "blocked" in capsys.readouterr().err
        assert out.read_text(encoding="utf-8") == (
            '{"source": "yad2", "fetched_at": "x", "listings": []}'
        )

    def test_error_when_no_existing_feed_still_exits_one_without_creating_one(
        self, repo, monkeypatch
    ):
        adapter = StubAdapter("yad2", AdapterResult(source="yad2", error="blocked"))
        runtime = StubRuntime(sources_config={"yad2": {}}, adapters=[adapter])
        monkeypatch.setattr(local_feed, "build_runtime", lambda *a, **k: runtime)

        code = local_feed.main(["--repo", str(repo)])

        assert code == 1
        assert not (repo / "state" / "feeds" / "yad2.json").exists()

    def test_custom_source_and_out(self, repo, monkeypatch):
        adapter = StubAdapter("onmap", AdapterResult(source="onmap", listings=[]))
        runtime = StubRuntime(sources_config={"onmap": {}}, adapters=[adapter])
        monkeypatch.setattr(local_feed, "build_runtime", lambda *a, **k: runtime)

        code = local_feed.main(
            ["--repo", str(repo), "--source", "onmap", "--out", "state/feeds/onmap.json"]
        )

        assert code == 0
        assert (repo / "state" / "feeds" / "onmap.json").exists()

    def test_prints_a_one_line_summary_on_success(self, repo, monkeypatch, capsys):
        adapter = StubAdapter("yad2", AdapterResult(source="yad2", listings=[make_listing()]))
        runtime = StubRuntime(sources_config={"yad2": {}}, adapters=[adapter])
        monkeypatch.setattr(local_feed, "build_runtime", lambda *a, **k: runtime)

        local_feed.main(["--repo", str(repo)])

        out = capsys.readouterr().out
        assert len(out.strip().splitlines()) == 1
        assert "1" in out
