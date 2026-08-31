import json
from datetime import datetime, timezone
from pathlib import Path

from apt_scout.filters import Filters
from apt_scout.models import Listing, Occupancy
from apt_scout.portal.builder import build_portal

ASSETS = Path("src/apt_scout/portal/assets")
NOW = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)


class TestVendoredLeaflet:
    def test_leaflet_is_vendored_not_loaded_from_a_cdn(self):
        html = (ASSETS / "index.html").read_text(encoding="utf-8")
        assert "vendor/leaflet.js" in html
        assert "vendor/leaflet.css" in html
        assert "unpkg.com" not in html
        assert "cdn." not in html

    def test_vendored_files_are_present_and_real(self):
        js = ASSETS / "vendor" / "leaflet.js"
        assert js.exists(), "run the curl step first"
        assert js.stat().st_size > 100_000, "leaflet.js looks truncated"


class TestMapMarkup:
    def test_html_has_a_map_container(self):
        html = (ASSETS / "index.html").read_text(encoding="utf-8")
        assert 'id="map"' in html

    def test_css_gives_the_map_a_height(self):
        # A Leaflet container with no height renders as an invisible zero-pixel
        # strip, which looks exactly like a broken map.
        css = (ASSETS / "style.css").read_text(encoding="utf-8")
        assert "#map" in css
        assert "height" in css


class TestMapBehaviour:
    def test_uses_openstreetmap_tiles(self):
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        assert "tile.openstreetmap.org" in js
        assert "attribution" in js, "OSM tile usage requires attribution"

    def test_uses_circle_markers_so_no_images_are_needed(self):
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        assert "circleMarker" in js

    def test_map_updates_with_the_filters(self):
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        assert "renderMap" in js

    def test_skips_listings_without_coordinates(self):
        js = (ASSETS / "app.js").read_text(encoding="utf-8")
        assert "lat === null" in js or "lat == null" in js


class TestAssetCopying:
    def test_build_copies_the_vendor_directory(self, tmp_path):
        listing = Listing(
            source="yad2",
            source_id="1",
            url="https://y/1",
            lat=32.07,
            lon=34.79,
            occupancy=Occupancy.WHOLE,
        )
        build_portal(tmp_path, [listing], {}, Filters(), NOW)
        assert (tmp_path / "vendor" / "leaflet.js").exists()
        assert (tmp_path / "vendor" / "leaflet.css").exists()

    def test_coordinates_are_published_for_the_map(self, tmp_path):
        listing = Listing(
            source="yad2", source_id="1", url="https://y/1", lat=32.07, lon=34.79
        )
        build_portal(tmp_path, [listing], {}, Filters(), NOW)
        data = json.loads((tmp_path / "data" / "listings.json").read_text("utf-8"))
        assert data["listings"][0]["lat"] == 32.07
        assert data["listings"][0]["lon"] == 34.79
