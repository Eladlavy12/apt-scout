import json

import pytest

from apt_scout.__main__ import build_runtime, main


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


class TestMain:
    def test_dry_run_exits_zero_without_credentials(self, repo):
        assert main(["--repo", str(repo), "--dry-run"]) == 0

    def test_creates_the_state_directory(self, repo):
        main(["--repo", str(repo), "--dry-run"])
        assert (repo / "state").is_dir()
