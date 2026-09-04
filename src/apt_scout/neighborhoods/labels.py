from __future__ import annotations

# Hebrew display labels. The portal keeps an identical copy in app.js
# (REPUTATION_LABELS / TAG_LABELS); tests/test_portal_assets.py checks they
# stay in sync.
REPUTATION_LABELS = {
    "sought_after": "מבוקשת מאוד",
    "solid": "טובה",
    "mixed": "מעורבת",
    "weak": "פחות מומלצת",
}

TAG_LABELS = {
    "quiet": "שקטה",
    "nightlife": "חיי לילה",
    "family": "משפחתית",
    "young": "צעירה",
    "beach": "קרוב לים",
    "green": "ירוקה",
    "light_rail": "רכבת קלה",
    "renewal": "התחדשות עירונית",
    "old_buildings": "בניינים ישנים",
    "noisy": "רועשת",
    "parking_hard": "חניה קשה",
    "expensive": "יקרה",
    "value": "תמורה למחיר",
    "religious": "אופי דתי",
    "industrial_edge": "צמוד לאזור תעשייה",
}
