import json

import pytest

from apt_scout.__main__ import (
    build_runtime,
    main,
    should_build_portal,
    warn_about_failing_sources,
)
from apt_scout.health import HealthTracker
from apt_scout.pipeline import RunReport
from apt_scout.state import StateStore


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "filters.json").write_text(
        json.dumps({"min_price": 4000, "max_price": 5500}), encoding="utf-8"
    )
    (tmp_path / "config" / "sources.json").write_text(
        json.dumps({"yad2": {"enabled": False, "follows_filters": True}}),
        encoding="utf-8",
    )
    return tmp_path


class TestRuntimeConstruction:
    def test_loads_config_from_the_repo(self, repo):
        runtime = build_runtime(
            repo, {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"}
        )
        assert runtime.filters.min_price == 4000
        assert runtime.sources_config["yad2"]["enabled"] is False

    def test_missing_telegram_credentials_is_a_clear_error(self, repo):
        with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
            build_runtime(repo, {})

    def test_dry_run_uses_a_notifier_that_does_not_send(self, repo):
        runtime = build_runtime(repo, {}, dry_run=True)
        assert runtime.notifier.send_listing(None) is True
        assert runtime.notifier.sent == [None]


class TestRepoRootInjection:
    def test_every_source_config_gets_the_repo_root(self, repo):
        (repo / "config" / "sources.json").write_text(
            json.dumps(
                {
                    "yad2": {"enabled": True},
                    "homeless": {"enabled": True},
                }
            ),
            encoding="utf-8",
        )
        runtime = build_runtime(repo, {}, dry_run=True)
        assert runtime.sources_config["yad2"]["repo_root"] == str(repo)
        assert runtime.sources_config["homeless"]["repo_root"] == str(repo)


class TestFetchWindowFollowsFilters:
    def test_yad2_window_is_derived_from_the_filters_with_a_margin(self, repo):
        (repo / "config" / "filters.json").write_text(
            json.dumps({"min_price": 5000, "max_price": 7000, "min_rooms": 3}),
            encoding="utf-8",
        )
        runtime = build_runtime(repo, {}, dry_run=True)
        assert runtime.sources_config["yad2"]["price_min"] == 4500
        assert runtime.sources_config["yad2"]["price_max"] == 7500
        assert runtime.sources_config["yad2"]["rooms_min"] == 3

    def test_the_price_floor_never_goes_negative(self, repo):
        (repo / "config" / "filters.json").write_text(
            json.dumps({"min_price": 300, "max_price": 7000}), encoding="utf-8"
        )
        runtime = build_runtime(repo, {}, dry_run=True)
        assert runtime.sources_config["yad2"]["price_min"] == 0

    def test_every_follows_filters_source_gets_the_price_window(self, repo):
        (repo / "config" / "filters.json").write_text(
            json.dumps({"min_price": 5000, "max_price": 7000, "min_rooms": 3}),
            encoding="utf-8",
        )
        (repo / "config" / "sources.json").write_text(
            json.dumps(
                {
                    "yad2": {"enabled": True, "follows_filters": True},
                    "onmap": {"enabled": True, "follows_filters": True},
                    "komo": {"enabled": True, "follows_filters": True},
                    "homeless": {"enabled": True},
                    "prog": {"enabled": True},
                }
            ),
            encoding="utf-8",
        )
        runtime = build_runtime(repo, {}, dry_run=True)
        for name in ("yad2", "onmap", "komo"):
            config = runtime.sources_config[name]
            assert config["price_min"] == 4500
            assert config["price_max"] == 7500
            assert config["rooms_min"] == 3
        assert "price_min" not in runtime.sources_config["homeless"]
        assert "price_min" not in runtime.sources_config["prog"]


class TestProgSkipIds:
    def test_prog_receives_bare_ids_seen_so_far(self, repo):
        (repo / "config" / "sources.json").write_text(
            json.dumps({"prog": {"enabled": True}}), encoding="utf-8"
        )
        store = StateStore(repo / "state")
        store.record_seen(
            {"prog:123": "", "prog:456": "", "yad2:999": "", "onmap:1": ""}
        )
        runtime = build_runtime(repo, {}, dry_run=True)
        assert sorted(runtime.sources_config["prog"]["skip_ids"]) == ["123", "456"]

    def test_no_prog_config_means_nothing_to_do(self, repo):
        (repo / "config" / "sources.json").write_text(
            json.dumps({"yad2": {"enabled": True}}), encoding="utf-8"
        )
        # Must not raise when the source isn't configured at all.
        build_runtime(repo, {}, dry_run=True)


class TestFbMarketplaceToken:
    def test_apify_token_env_var_is_injected_into_source_config(self, repo):
        (repo / "config" / "sources.json").write_text(
            json.dumps({"fb_marketplace": {"enabled": True}}), encoding="utf-8"
        )
        runtime = build_runtime(repo, {"APIFY_TOKEN": "secret-token"}, dry_run=True)
        assert runtime.sources_config["fb_marketplace"]["token"] == "secret-token"

    def test_missing_apify_token_env_var_becomes_none_not_a_crash(self, repo):
        (repo / "config" / "sources.json").write_text(
            json.dumps({"fb_marketplace": {"enabled": True}}), encoding="utf-8"
        )
        runtime = build_runtime(repo, {}, dry_run=True)
        assert runtime.sources_config["fb_marketplace"]["token"] is None

    def test_no_fb_marketplace_config_means_nothing_to_do(self, repo):
        (repo / "config" / "sources.json").write_text(
            json.dumps({"yad2": {"enabled": True}}), encoding="utf-8"
        )
        build_runtime(repo, {}, dry_run=True)


class TestAdapterRegistration:
    def test_all_six_adapters_are_registered(self, repo):
        runtime = build_runtime(repo, {}, dry_run=True)
        assert {adapter.name for adapter in runtime.adapters} == {
            "yad2",
            "onmap",
            "komo",
            "homeless",
            "prog",
            "fb_marketplace",
        }


class TestPortalDecision:
    def test_builds_when_anything_was_fetched(self):
        report = RunReport(fetched=3, errors={"yad2": "blocked"})
        assert should_build_portal(report, {"yad2": {"enabled": True}}) is True

    def test_skips_when_every_enabled_source_failed(self):
        report = RunReport(
            fetched=0,
            errors={"yad2": "blocked", "madlan": "down"},
            attempted=["yad2", "madlan"],
        )
        sources = {"yad2": {"enabled": True}, "madlan": {"enabled": True}}
        assert should_build_portal(report, sources) is False

    def test_builds_when_one_enabled_source_was_merely_quiet(self):
        # One source erroring while the other genuinely found nothing is a
        # quiet market, not an outage.
        report = RunReport(
            fetched=0, errors={"yad2": "blocked"}, attempted=["yad2", "madlan"]
        )
        sources = {"yad2": {"enabled": True}, "madlan": {"enabled": True}}
        assert should_build_portal(report, sources) is True

    def test_disabled_sources_do_not_count(self):
        report = RunReport(
            fetched=0, errors={"yad2": "blocked"}, attempted=["yad2"]
        )
        sources = {"yad2": {"enabled": True}, "madlan": {"enabled": False}}
        assert should_build_portal(report, sources) is False

    def test_skips_when_no_enabled_source_attempted_a_fetch(self):
        # A workflow_dispatch inside every source's cadence window gates ALL
        # sources: nothing errored, but nothing ran either. The live portal
        # must not be replaced by an empty page.
        report = RunReport(fetched=0, errors={}, attempted=[])
        sources = {"yad2": {"enabled": True}, "madlan": {"enabled": True}}
        assert should_build_portal(report, sources) is False

    def test_main_skips_the_portal_on_total_source_failure(
        self, repo, monkeypatch, capsys
    ):
        class Exploding:
            name = "yad2"

            def fetch(self, fetcher, config, since):
                raise RuntimeError("blocked")

        runtime = build_runtime(repo, {}, dry_run=True)
        runtime.sources_config = {"yad2": {"enabled": True}}
        runtime.adapters = [Exploding()]
        monkeypatch.setattr(
            "apt_scout.__main__.build_runtime", lambda *a, **k: runtime
        )

        assert main(["--repo", str(repo), "--dry-run", "--build-portal"]) == 0

        assert not (repo / "site" / "index.html").exists()
        assert "keeping the previous portal" in capsys.readouterr().err


class TestHealthWarnings:
    class RecordingNotifier:
        def __init__(self):
            self.texts = []

        def send_text(self, text):
            self.texts.append(text)
            return True

    def fail(self, store, source="yad2", times=3):
        tracker = HealthTracker(store)
        for _ in range(times):
            tracker.record(source, ok=False, error="blocked")

    def test_warns_once_when_a_source_reaches_the_threshold(self, tmp_path):
        store = StateStore(tmp_path)
        self.fail(store)
        notifier = self.RecordingNotifier()

        warn_about_failing_sources(store, notifier)
        warn_about_failing_sources(store, notifier)

        assert notifier.texts == ["⚠️ מקור yad2 נכשל 3 פעמים ברצף"]

    def test_below_the_threshold_stays_silent(self, tmp_path):
        store = StateStore(tmp_path)
        self.fail(store, times=2)
        notifier = self.RecordingNotifier()
        warn_about_failing_sources(store, notifier)
        assert notifier.texts == []

    def test_recovery_clears_the_flag_so_a_relapse_warns_again(self, tmp_path):
        store = StateStore(tmp_path)
        notifier = self.RecordingNotifier()

        self.fail(store)
        warn_about_failing_sources(store, notifier)
        HealthTracker(store).record("yad2", ok=True)
        warn_about_failing_sources(store, notifier)
        self.fail(store)
        warn_about_failing_sources(store, notifier)

        assert len(notifier.texts) == 2


class TestSaltWarning:
    ENV = {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_CHAT_ID": "c"}

    def test_missing_salt_warns_on_stderr(self, repo, capsys):
        build_runtime(repo, dict(self.ENV))
        assert "PHONE_HASH_SALT" in capsys.readouterr().err

    def test_no_warning_when_the_salt_is_set(self, repo, capsys):
        build_runtime(repo, {**self.ENV, "PHONE_HASH_SALT": "pepper"})
        assert capsys.readouterr().err == ""

    def test_dry_run_does_not_warn(self, repo, capsys):
        build_runtime(repo, {}, dry_run=True)
        assert capsys.readouterr().err == ""


class TestMain:
    def test_dry_run_exits_zero_without_credentials(self, repo):
        assert main(["--repo", str(repo), "--dry-run"]) == 0

    def test_creates_the_state_directory(self, repo):
        main(["--repo", str(repo), "--dry-run"])
        assert (repo / "state").is_dir()
