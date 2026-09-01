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

    def test_never_uses_innerhtml_with_scraped_data(self):
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        assert "innerHTML" not in js, "scraped data must be DOM-built, not string-injected"
        assert "safeHttpUrl" in js, "URLs from scraped data must be scheme-validated"


class TestSortAndSources:
    def test_has_sort_select_with_expected_options(self):
        html = (ASSETS / "index.html").read_text(encoding="utf-8")
        assert 'id="sort"' in html
        for value in ("newest", "cheapest", "nearest", "preference"):
            assert f'value="{value}"' in html, f"missing sort option {value}"

    def test_has_source_toggles_container(self):
        html = (ASSETS / "index.html").read_text(encoding="utf-8")
        assert 'id="source-toggles"' in html

    def test_references_sources_field(self):
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        assert "sources" in js

    def test_sorts_by_expected_fields(self):
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        for field in ("drive_minutes", "price", "first_seen_at"):
            assert field in js, f"sort logic missing {field}"

    def test_has_city_ranking_table(self):
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        for city in ("תל אביב", "גבעתיים", "רמת גן"):
            assert city in js, f"preference ranking missing {city}"

    def test_still_never_uses_innerhtml(self):
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        assert "innerHTML" not in js
