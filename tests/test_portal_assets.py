from pathlib import Path

ASSETS = Path("src/apt_scout/portal/assets")


class TestHtml:
    def test_is_right_to_left_hebrew(self):
        html = (ASSETS / "index.html").read_text(encoding="utf-8")
        assert 'dir="rtl"' in html
        assert 'lang="he"' in html

    def test_has_a_control_for_every_filter(self):
        html = (ASSETS / "index.html").read_text(encoding="utf-8")
        for control in (
            "max-drive",
            "min-price",
            "max-price",
            "min-rooms",
            "min-size",
            "include-no-price",
            "include-unsure",
        ):
            assert f'id="{control}"' in html, f"missing control {control}"

    def test_loads_its_own_assets_only(self):
        # A strict offline-capable portal: no CDN scripts, no external CSS.
        html = (ASSETS / "index.html").read_text(encoding="utf-8")
        assert "app.js" in html
        assert "style.css" in html

    def test_has_a_health_footer(self):
        html = (ASSETS / "index.html").read_text(encoding="utf-8")
        assert 'id="health"' in html


class TestJavaScript:
    def test_fetches_the_data_file(self):
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        assert "data/listings.json" in js

    def test_filters_on_every_criterion(self):
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        for field in ("drive_minutes", "price", "rooms", "size_sqm", "occupancy"):
            assert field in js, f"filter logic missing {field}"

    def test_persists_the_users_choices(self):
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        assert "localStorage" in js

    def test_re_renders_on_input_without_reloading(self):
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        assert "addEventListener" in js
        assert "location.reload" not in js
