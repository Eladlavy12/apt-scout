from __future__ import annotations

import html
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..enrich.city import CANONICAL_CITIES, normalise_city
from ..filters import Filters
from ..neighborhoods.knowledge import KnowledgeBase
from ..state import StateStore

OFFSET = "telegram_offset"

USAGE = (
    "פקודות זמינות:\n"
    "/price <מינימום> <מקסימום>\n"
    "/radius <דקות נסיעה>\n"
    "/km <ק\"מ>\n"
    "/rooms <מינימום חדרים>\n"
    "/size <מינימום מ\"ר>\n"
    "/sublets on|off\n"
    "/cities <ערים מופרדות בפסיק> | all\n"
    "/exclude <שם שכונה> — הסתרת שכונה\n"
    "/include <שם שכונה> — החזרת שכונה\n"
    "/pause — עצירת התראות\n"
    "/resume — חידוש התראות\n"
    "/status — הצגת ההגדרות"
)


def parse_command(text: str | None) -> tuple[str, list[str]] | None:
    """Split a Telegram message into a command and its arguments."""
    if not text or not text.startswith("/"):
        return None
    parts = text.split()
    # "/status@MyBot" is what Telegram sends in group chats.
    command = parts[0][1:].split("@")[0].lower()
    return command, parts[1:]


def _describe(filters: Filters, knowledge: KnowledgeBase | None = None) -> str:
    state = "מושהה" if filters.paused else "פעיל"
    cities = ", ".join(filters.cities) if filters.cities else "כל הערים"
    if filters.excluded_neighborhoods:
        names = []
        for nid in filters.excluded_neighborhoods:
            profile = knowledge.get(nid) if knowledge else None
            names.append(profile.display_name if profile else nid)
        excluded = ", ".join(names)
    else:
        excluded = "אין"
    return (
        f"סטטוס: {state}\n"
        f"מחיר: {filters.min_price:,}–{filters.max_price:,} ₪\n"
        f"נסיעה: עד {filters.max_drive_minutes:g} דק'\n"
        f'מרחק: עד {filters.max_distance_km:g} ק"מ\n'
        f"חדרים: מ-{filters.min_rooms:g}\n"
        f'שטח: מ-{filters.min_size_sqm:g} מ"ר\n'
        f"סאבלטים: {'מוסתרים' if filters.exclude_sublets else 'מוצגים'}\n"
        f"ערים: {cities}\n"
        f"שכונות מוסתרות: {excluded}"
    )


def _numbers(args: list[str], count: int) -> list[float] | None:
    if len(args) != count:
        return None
    try:
        return [float(a) for a in args]
    except ValueError:
        return None


def _parse_cities(args: list[str]) -> tuple[list[str], list[str]]:
    """Split comma-separated city names; return (canonical, unknown)."""
    joined = " ".join(args)
    canonical: list[str] = []
    unknown: list[str] = []
    for part in joined.split(","):
        part = part.strip()
        if not part:
            continue
        city = normalise_city(part)
        if city is None:
            unknown.append(part)
        elif city not in canonical:
            canonical.append(city)
    return canonical, unknown


def _resolve_neighborhood(args: list[str], knowledge: KnowledgeBase | None) -> tuple[str | None, str]:
    """Resolve a typed neighborhood name to an id; the str is an error reply."""
    if knowledge is None:
        return None, "מאגר השכונות לא נטען; נסה שוב בריצה הבאה."
    name = " ".join(args).strip()
    if not name:
        return None, "שימוש: /exclude פלורנטין"
    matches = knowledge.find_by_name(name)
    if len(matches) == 1:
        return matches[0].id, ""
    safe_name = html.escape(name)
    if not matches:
        return None, f"לא מצאתי שכונה בשם '{safe_name}'."
    # Display names and cities come from the curated knowledge base, not
    # user input, so they are not escaped.
    options = ", ".join(f"{m.display_name} ({m.city})" for m in matches)
    return None, f"'{safe_name}' לא חד-משמעי: {options}. ציין את השם המלא."


def apply_command(
    filters: Filters, command: str, args: list[str], knowledge: KnowledgeBase | None = None
) -> tuple[Filters, str]:
    """Apply one command, returning the new filters and a reply.

    Invalid input never changes configuration; it returns the original filters
    with a usage message, so a typo cannot silently widen the alert criteria.
    """
    if command == "status":
        return filters, _describe(filters, knowledge)

    if command == "pause":
        updated = replace(filters, paused=True)
        return updated, "התראות הושהו. /resume כדי לחדש."

    if command == "resume":
        updated = replace(filters, paused=False)
        return updated, "התראות חודשו.\n" + _describe(updated, knowledge)

    if command == "price":
        values = _numbers(args, 2)
        if values is None or values[0] > values[1]:
            return filters, "שימוש: /price 4000 5500"
        updated = replace(filters, min_price=int(values[0]), max_price=int(values[1]))
        return updated, _describe(updated, knowledge)

    if command == "radius":
        values = _numbers(args, 1)
        if values is None:
            return filters, "שימוש: /radius 15"
        updated = replace(filters, max_drive_minutes=values[0])
        return updated, _describe(updated, knowledge)

    if command == "km":
        values = _numbers(args, 1)
        if values is None:
            return filters, "שימוש: /km 5"
        updated = replace(filters, max_distance_km=values[0])
        return updated, _describe(updated, knowledge)

    if command == "sublets":
        if len(args) != 1 or args[0] not in ("on", "off"):
            return filters, "שימוש: /sublets on|off"
        updated = replace(filters, exclude_sublets=(args[0] == "off"))
        return updated, _describe(updated, knowledge)

    if command == "rooms":
        values = _numbers(args, 1)
        if values is None:
            return filters, "שימוש: /rooms 2"
        updated = replace(filters, min_rooms=values[0])
        return updated, _describe(updated, knowledge)

    if command == "size":
        values = _numbers(args, 1)
        if values is None:
            return filters, 'שימוש: /size 50'
        updated = replace(filters, min_size_sqm=values[0])
        return updated, _describe(updated, knowledge)

    if command == "cities":
        if not args:
            return filters, "שימוש: /cities תל אביב, גבעתיים  או  /cities all"
        if len(args) == 1 and args[0].lower() == "all":
            updated = replace(filters, cities=[])
            return updated, _describe(updated, knowledge)
        canonical, unknown = _parse_cities(args)
        if unknown or not canonical:
            bad = html.escape(", ".join(unknown) or " ".join(args))
            return filters, (
                f"לא מזהה: {bad}. "
                f"ערים אפשריות: {', '.join(CANONICAL_CITIES)}"
            )
        updated = replace(filters, cities=canonical)
        return updated, _describe(updated, knowledge)

    if command in ("exclude", "include"):
        nid, error = _resolve_neighborhood(args, knowledge)
        if nid is None:
            return filters, error
        current = list(filters.excluded_neighborhoods)
        if command == "exclude" and nid not in current:
            current.append(nid)
        if command == "include" and nid in current:
            current.remove(nid)
        updated = replace(filters, excluded_neighborhoods=current)
        return updated, _describe(updated, knowledge)

    return filters, USAGE


def process_commands(
    notifier: Any,
    store: StateStore,
    filters: Filters,
    filters_path: Path,
    chat_id: str,
    knowledge: KnowledgeBase | None = None,
) -> Filters:
    """Poll Telegram, apply any commands, and persist the result.

    Only messages from the configured chat are honoured: anyone can message a
    bot, so a stranger must not be able to reconfigure the alerts. Foreign
    updates are dropped silently — no reply, but the offset still advances so
    they are not re-fetched forever.

    A polling failure is swallowed: the run continues with the existing
    configuration rather than being lost to a Telegram outage.
    """
    offset = store.load(OFFSET, None)
    try:
        updates = notifier.get_updates(offset=offset)
    except Exception:  # noqa: BLE001 - a poll failure must not fail the run
        return filters

    changed = False
    highest: int | None = None

    for item in updates:
        highest = max(highest or 0, item.get("update_id", 0))
        message = item.get("message") or {}
        update_chat_id = (message.get("chat") or {}).get("id")
        if str(update_chat_id) != str(chat_id):
            continue
        text = message.get("text")
        parsed = parse_command(text)
        if parsed is None:
            continue
        command, args = parsed
        before = filters.to_dict()
        filters, reply = apply_command(filters, command, args, knowledge)
        if filters.to_dict() != before:
            changed = True
        notifier.send_text(reply)

    if highest is not None:
        store.save(OFFSET, highest + 1)

    if changed:
        Path(filters_path).write_text(
            json.dumps(filters.to_dict(), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    return filters
