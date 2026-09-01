from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..filters import Filters
from ..state import StateStore

OFFSET = "telegram_offset"

USAGE = (
    "פקודות זמינות:\n"
    "/price <מינימום> <מקסימום>\n"
    "/radius <דקות נסיעה>\n"
    "/km <ק\"מ>\n"
    "/rooms <מינימום חדרים>\n"
    "/size <מינימום מ\"ר>\n"
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


def _describe(filters: Filters) -> str:
    state = "מושהה" if filters.paused else "פעיל"
    return (
        f"סטטוס: {state}\n"
        f"מחיר: {filters.min_price:,}–{filters.max_price:,} ₪\n"
        f"נסיעה: עד {filters.max_drive_minutes:g} דק'\n"
        f'מרחק: עד {filters.max_distance_km:g} ק"מ\n'
        f"חדרים: מ-{filters.min_rooms:g}\n"
        f'שטח: מ-{filters.min_size_sqm:g} מ"ר'
    )


def _numbers(args: list[str], count: int) -> list[float] | None:
    if len(args) != count:
        return None
    try:
        return [float(a) for a in args]
    except ValueError:
        return None


def apply_command(
    filters: Filters, command: str, args: list[str]
) -> tuple[Filters, str]:
    """Apply one command, returning the new filters and a reply.

    Invalid input never changes configuration; it returns the original filters
    with a usage message, so a typo cannot silently widen the alert criteria.
    """
    if command == "status":
        return filters, _describe(filters)

    if command == "pause":
        updated = replace(filters, paused=True)
        return updated, "התראות הושהו. /resume כדי לחדש."

    if command == "resume":
        updated = replace(filters, paused=False)
        return updated, "התראות חודשו.\n" + _describe(updated)

    if command == "price":
        values = _numbers(args, 2)
        if values is None or values[0] > values[1]:
            return filters, "שימוש: /price 4000 5500"
        updated = replace(filters, min_price=int(values[0]), max_price=int(values[1]))
        return updated, _describe(updated)

    if command == "radius":
        values = _numbers(args, 1)
        if values is None:
            return filters, "שימוש: /radius 15"
        updated = replace(filters, max_drive_minutes=values[0])
        return updated, _describe(updated)

    if command == "km":
        values = _numbers(args, 1)
        if values is None:
            return filters, "שימוש: /km 5"
        updated = replace(filters, max_distance_km=values[0])
        return updated, _describe(updated)

    if command == "rooms":
        values = _numbers(args, 1)
        if values is None:
            return filters, "שימוש: /rooms 2"
        updated = replace(filters, min_rooms=values[0])
        return updated, _describe(updated)

    if command == "size":
        values = _numbers(args, 1)
        if values is None:
            return filters, 'שימוש: /size 50'
        updated = replace(filters, min_size_sqm=values[0])
        return updated, _describe(updated)

    return filters, USAGE


def process_commands(
    notifier: Any,
    store: StateStore,
    filters: Filters,
    filters_path: Path,
    chat_id: str,
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
        filters, reply = apply_command(filters, command, args)
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
