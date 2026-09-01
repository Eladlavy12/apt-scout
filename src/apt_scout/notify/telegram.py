from __future__ import annotations

import html

from ..models import Listing

API_BASE = "https://api.telegram.org/bot{token}/{method}"


def format_listing(listing: Listing) -> str:
    """Build the Telegram message body for one listing.

    Telegram is private to the user, so full detail is safe here — unlike the
    public portal, which must never carry contact information.
    """
    price = f"{listing.price:,} ₪" if listing.price is not None else "מחיר לא צוין"
    lines = [f"<b>{price}</b>"]

    facts = []
    if listing.rooms is not None:
        facts.append(f"{listing.rooms:g} חד'")
    if listing.size_sqm is not None:
        facts.append(f'{listing.size_sqm:g} מ"ר')
    if listing.floor is not None:
        facts.append(f"קומה {listing.floor}")
    if facts:
        lines.append(" · ".join(facts))

    if listing.address_text:
        lines.append(html.escape(listing.address_text))
    elif listing.city:
        lines.append(html.escape(listing.city))

    if listing.drive_minutes is not None:
        lines.append(f"🚗 {round(listing.drive_minutes)} דקות נסיעה")
    if listing.distance_km is not None:
        lines.append(f'📍 {listing.distance_km:g} ק"מ')

    lines.append(f"מקור: {listing.source}")
    lines.append(html.escape(listing.url))
    return "\n".join(lines)


class TelegramNotifier:
    """Sends listing alerts to a single Telegram chat."""

    def __init__(
        self, token: str, chat_id: str, client: object | None = None, timeout: float = 15.0
    ) -> None:
        self._token = token
        self._chat_id = chat_id
        if client is None:
            import httpx

            client = httpx.Client(timeout=timeout)
        self._client = client

    def _call(self, method: str, payload: dict) -> bool:
        url = API_BASE.format(token=self._token, method=method)
        try:
            response = self._client.post(url, json=payload)
        except Exception:  # noqa: BLE001 - a failed send is retried next run
            return False
        if response.status_code != 200:
            return False
        try:
            return bool(response.json().get("ok"))
        except Exception:  # noqa: BLE001
            return False

    def send_text(self, text: str) -> bool:
        return self._call(
            "sendMessage",
            {
                "chat_id": self._chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
        )

    def get_updates(self, offset: int | None = None) -> list[dict]:
        """Poll for messages sent to the bot.

        Raises on failure so the caller can leave configuration untouched
        rather than acting on a partial view of the user's instructions.
        """
        url = API_BASE.format(token=self._token, method="getUpdates")
        payload: dict = {"timeout": 0}
        if offset is not None:
            payload["offset"] = offset
        response = self._client.post(url, json=payload)
        return response.json().get("result", [])

    def send_listing(self, listing: Listing) -> bool:
        caption = format_listing(listing)
        if listing.photos:
            sent = self._call(
                "sendPhoto",
                {
                    "chat_id": self._chat_id,
                    "photo": listing.photos[0],
                    "caption": caption,
                    "parse_mode": "HTML",
                },
            )
            if sent:
                return True
            # A dead photo URL must not cost the user the alert itself.
        return self.send_text(caption)
