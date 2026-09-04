from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from ..enrich.city import CANONICAL_CITIES
from ..normalise.text import normalise_text

REPUTATIONS = ("sought_after", "solid", "mixed", "weak")
TAGS = frozenset(
    {
        "quiet", "nightlife", "family", "young", "beach", "green", "light_rail",
        "renewal", "old_buildings", "noisy", "parking_hard", "expensive", "value",
        "religious", "industrial_edge",
    }
)
REQUIRED_FIELDS = ("names", "city", "reputation", "summary", "pros", "cons", "tags")
MAX_TAGS = 5
_ID = re.compile(r"[a-z0-9_]+")
_ALIAS_NOISE = re.compile(r"[\s\-–'\"׳״]+")


def _alias_key(text: str) -> str:
    return _ALIAS_NOISE.sub(" ", normalise_text(text)).strip().lower()


@dataclass(frozen=True)
class Neighborhood:
    id: str
    names: tuple[str, ...]
    city: str
    reputation: str
    summary: str
    pros: tuple[str, ...]
    cons: tuple[str, ...]
    tags: tuple[str, ...]
    sources: tuple[str, ...]
    notes: str = ""

    @property
    def display_name(self) -> str:
        return self.names[0]

    def public(self) -> dict:
        return {
            "names": list(self.names),
            "city": self.city,
            "reputation": self.reputation,
            "summary": self.summary,
            "pros": list(self.pros),
            "cons": list(self.cons),
            "tags": list(self.tags),
        }


def _strings(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) and v.strip() for v in value)


def _problems(nid: str, raw: object) -> list[str]:
    issues: list[str] = []
    if not _ID.fullmatch(nid):
        issues.append(f"{nid}: id must match [a-z0-9_]+")
    if not isinstance(raw, dict):
        return issues + [f"{nid}: entry must be an object"]
    for field in REQUIRED_FIELDS:
        if field not in raw:
            issues.append(f"{nid}: missing '{field}'")
    if issues:
        return issues
    if not _strings(raw["names"]) or not raw["names"]:
        issues.append(f"{nid}: names must be a non-empty list of strings")
    if raw["city"] not in CANONICAL_CITIES:
        issues.append(f"{nid}: city must be one of {list(CANONICAL_CITIES)}")
    if raw["reputation"] not in REPUTATIONS:
        issues.append(f"{nid}: reputation must be one of {list(REPUTATIONS)}")
    if not isinstance(raw["summary"], str) or not raw["summary"].strip():
        issues.append(f"{nid}: summary must be a non-empty string")
    for field in ("pros", "cons"):
        if not _strings(raw[field]) or len(raw[field]) < 2:
            issues.append(f"{nid}: {field} needs at least two strings")
    tags = raw["tags"]
    if not _strings(tags):
        issues.append(f"{nid}: tags must be a list of strings")
    else:
        unknown = sorted(set(tags) - TAGS)
        if unknown:
            issues.append(f"{nid}: unknown tags {unknown}")
        if len(tags) != len(set(tags)):
            issues.append(f"{nid}: duplicate tags")
        if len(tags) > MAX_TAGS:
            issues.append(f"{nid}: at most {MAX_TAGS} tags")
    if not _strings(raw.get("sources", [])) or not raw.get("sources"):
        issues.append(f"{nid}: sources must be a non-empty list of strings")
    if not isinstance(raw.get("notes", ""), str):
        issues.append(f"{nid}: notes must be a string")
    return issues


class KnowledgeBase:
    """Curated neighborhood profiles keyed by id (see data/neighborhoods.json)."""

    def __init__(self, entries: dict[str, Neighborhood]) -> None:
        self._entries = entries
        self._by_alias: dict[str, list[Neighborhood]] = {}
        for item in entries.values():
            for name in item.names:
                key = _alias_key(name)
                if key:
                    self._by_alias.setdefault(key, []).append(item)

    @classmethod
    def from_dict(cls, raw: dict) -> "KnowledgeBase":
        issues: list[str] = []
        entries: dict[str, Neighborhood] = {}
        for nid, value in raw.items():
            found = _problems(nid, value)
            if found:
                issues.extend(found)
                continue
            entries[nid] = Neighborhood(
                id=nid,
                names=tuple(value["names"]),
                city=value["city"],
                reputation=value["reputation"],
                summary=value["summary"],
                pros=tuple(value["pros"]),
                cons=tuple(value["cons"]),
                tags=tuple(value["tags"]),
                sources=tuple(value["sources"]),
                notes=value.get("notes", ""),
            )
        if issues:
            raise ValueError("invalid neighborhoods knowledge base:\n" + "\n".join(issues))
        return cls(entries)

    @classmethod
    def load(cls, path: Path) -> "KnowledgeBase":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def get(self, nid: str) -> Neighborhood | None:
        return self._entries.get(nid)

    def __contains__(self, nid: object) -> bool:
        return nid in self._entries

    def ids(self) -> list[str]:
        return list(self._entries)

    def entries(self) -> list[Neighborhood]:
        return list(self._entries.values())

    def find_by_name(self, text: str) -> list[Neighborhood]:
        return list(self._by_alias.get(_alias_key(text), []))

    def match_in_text(self, text: str | None, city: str | None) -> str | None:
        """Longest alias appearing as a whole word in text; None if ambiguous.

        Punctuation is treated as a word break, and a single attached Hebrew
        prefix letter ב/ל/ו/ה ("בפלורנטין", "לבבלי") is allowed before the
        alias. מ and ש are deliberately not allowed: "מאורות" must not read
        as the Orot neighborhood.
        """
        if not text:
            return None
        haystack = re.sub(r"[^\w\s]", " ", _alias_key(text))
        best: tuple[int, set[str]] = (0, set())
        for alias, items in self._by_alias.items():
            pattern = r"(?<!\S)[בלוה]?" + re.escape(alias) + r"(?!\S)"
            if not re.search(pattern, haystack):
                continue
            ids = {item.id for item in items if city is None or item.city == city}
            if not ids:
                continue
            if len(alias) > best[0]:
                best = (len(alias), ids)
            elif len(alias) == best[0]:
                best[1].update(ids)
        return next(iter(best[1])) if len(best[1]) == 1 else None

    def public_dict(self) -> dict:
        return {nid: item.public() for nid, item in self._entries.items()}
