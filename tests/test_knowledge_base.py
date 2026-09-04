import json

import pytest

from apt_scout.neighborhoods.knowledge import REPUTATIONS, TAGS, KnowledgeBase


def entry(**overrides) -> dict:
    base = {
        "names": ["פלורנטין", "Florentin"],
        "city": "תל אביב יפו",
        "reputation": "mixed",
        "summary": "שכונה צעירה ורועשת.",
        "pros": ["חיי לילה", "מחירים"],
        "cons": ["רעש", "לכלוך"],
        "tags": ["nightlife", "young", "noisy"],
        "sources": ["homemarket"],
    }
    base.update(overrides)
    return base


def kb(**entries) -> KnowledgeBase:
    return KnowledgeBase.from_dict(entries or {"florentin": entry()})


class TestValidation:
    def test_accepts_a_well_formed_entry(self):
        base = kb()
        assert base.get("florentin").display_name == "פלורנטין"
        assert "florentin" in base
        assert base.ids() == ["florentin"]

    @pytest.mark.parametrize(
        "bad",
        [
            {"reputation": "great"},
            {"tags": ["nightlife", "unknown_tag"]},
            {"tags": ["quiet"] * 2},
            {"tags": ["quiet", "green", "family", "beach", "value", "young"]},
            {"city": "חולון"},
            {"pros": ["only one"]},
            {"cons": []},
            {"names": []},
            {"sources": []},
            {"summary": ""},
        ],
    )
    def test_rejects_malformed_entries(self, bad):
        with pytest.raises(ValueError) as excinfo:
            kb(florentin=entry(**bad))
        assert "florentin" in str(excinfo.value)

    def test_rejects_a_missing_field(self):
        broken = entry()
        del broken["summary"]
        with pytest.raises(ValueError, match="summary"):
            kb(florentin=broken)

    def test_rejects_a_bad_id(self):
        with pytest.raises(ValueError, match="Florentin"):
            kb(Florentin=entry())

    def test_reports_every_problem_at_once(self):
        with pytest.raises(ValueError) as excinfo:
            KnowledgeBase.from_dict({"a": entry(reputation="x"), "b": entry(city="חולון")})
        message = str(excinfo.value)
        assert "a" in message and "b" in message

    def test_vocabularies_are_the_spec_values(self):
        assert REPUTATIONS == ("sought_after", "solid", "mixed", "weak")
        assert TAGS == frozenset(
            {
                "quiet", "nightlife", "family", "young", "beach", "green", "light_rail",
                "renewal", "old_buildings", "noisy", "parking_hard", "expensive", "value",
                "religious", "industrial_edge",
            }
        )


class TestLookup:
    def test_find_by_name_is_alias_and_case_insensitive(self):
        base = kb()
        assert [n.id for n in base.find_by_name("florentin")] == ["florentin"]
        assert [n.id for n in base.find_by_name(" פלורנטין ")] == ["florentin"]
        assert base.find_by_name("nowhere") == []

    def test_match_in_text_prefers_the_longest_alias(self):
        base = kb(
            neve_tzedek=entry(names=["נווה צדק"], city="תל אביב יפו"),
            neve_tzedek_north=entry(names=["נווה צדק צפון"], city="תל אביב יפו"),
        )
        assert base.match_in_text("דירה בנווה צדק צפון, קומה 2", None) == "neve_tzedek_north"
        assert base.match_in_text("דירה בנווה צדק", None) == "neve_tzedek"

    def test_match_in_text_respects_the_city_when_known(self):
        base = kb(
            tlv_hood=entry(names=["הדר"], city="תל אביב יפו"),
            rg_hood=entry(names=["הדר"], city="רמת גן"),
        )
        assert base.match_in_text("רחוב הדר 3", "רמת גן") == "rg_hood"
        assert base.match_in_text("רחוב הדר 3", None) is None  # ambiguous

    def test_match_in_text_needs_whole_words(self):
        base = kb(orot=entry(names=["אורות"], city="תל אביב יפו"))
        assert base.match_in_text("מאורות הכרך", None) is None
        assert base.match_in_text("שכונת אורות", None) == "orot"
        assert base.match_in_text(None, None) is None

    def test_a_punctuation_only_alias_does_not_match_everything(self):
        # An alias made entirely of the noise characters _ALIAS_NOISE strips
        # (hyphens, quotes, Hebrew geresh/gershayim) keys to "" once
        # normalised, and an empty key would match the start of every text.
        base = kb(weird=entry(names=["פלורנטין", "׳"], city="תל אביב יפו"))
        assert base.match_in_text("רחוב הרצל 5, חולון", None) is None


class TestPublicProjection:
    def test_strips_notes_and_sources(self):
        public = kb(florentin=entry(notes="private remark")).public_dict()
        assert set(public) == {"florentin"}
        assert "notes" not in public["florentin"]
        assert "sources" not in public["florentin"]
        assert public["florentin"]["names"] == ["פלורנטין", "Florentin"]
        json.dumps(public, ensure_ascii=False)  # JSON-serialisable


def test_load_reads_a_file(tmp_path):
    path = tmp_path / "kb.json"
    path.write_text(json.dumps({"florentin": entry()}, ensure_ascii=False), encoding="utf-8")
    assert KnowledgeBase.load(path).ids() == ["florentin"]
