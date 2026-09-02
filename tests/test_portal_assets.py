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
            "max-km",
            "include-no-price",
            "include-unsure",
            "include-sublets",
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
        for field in (
            "drive_minutes",
            "distance_km",
            "price",
            "rooms",
            "size_sqm",
            "occupancy",
            "is_sublet",
        ):
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


class TestDistanceControl:
    def test_html_has_the_max_km_slider(self):
        html = (ASSETS / "index.html").read_text(encoding="utf-8")
        assert 'id="max-km"' in html
        assert 'id="max-km-out"' in html

    def test_js_uses_the_max_km_control(self):
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        assert "max-km" in js

    def test_js_maps_the_default_max_distance(self):
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        assert "max_distance_km" in js

    def test_card_shows_distance_when_known(self):
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        assert "📍" in js


class TestSubletControl:
    def test_html_has_the_include_sublets_toggle(self):
        html = (ASSETS / "index.html").read_text(encoding="utf-8")
        assert 'id="include-sublets"' in html

    def test_js_uses_the_include_sublets_control(self):
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        assert "include-sublets" in js

    def test_js_maps_the_default_exclude_sublets(self):
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        assert "exclude_sublets" in js

    def test_card_shows_a_sublet_badge(self):
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        assert "badge sublet" in js

    def test_still_never_uses_innerhtml(self):
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        assert "innerHTML" not in js


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
