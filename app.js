"use strict";

const STORAGE_KEY = "apt-scout-filters";
const CONTROLS = ["max-drive", "min-price", "max-price", "min-rooms", "min-size", "max-km"];
const TOGGLES = ["include-no-price", "include-unsure", "include-sublets"];

// Preference sort ranks by city desirability, then falls back to newest-first.
const CITY_RANK = {
  "תל אביב יפו": 0,
  "תל אביב": 0,
  "גבעתיים": 1,
  "רמת גן": 2,
};

// The canonical city set (see enrich.city.CANONICAL_CITIES). Distinct from
// CITY_RANK, which also carries "תל אביב" purely so an un-normalised
// listing still sorts sensibly; chip grouping must not treat that as its
// own city or a stray "תל אביב" chip would appear next to "תל אביב יפו".
const CANONICAL_CITIES = new Set(["תל אביב יפו", "גבעתיים", "רמת גן"]);

let listings = [];
let defaults = {};
let map = null;
let markerLayer = null;
let sourceToggleIds = [];
const CENTRE = [32.056581, 34.804087];

const OTHER_CITY = "other";
const REPUTATION_LABELS = {
  "sought_after": "מבוקשת מאוד",
  "solid": "טובה",
  "mixed": "מעורבת",
  "weak": "פחות מומלצת"
};
const TAG_LABELS = {
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
  "industrial_edge": "צמוד לאזור תעשייה"
};
let profiles = {};
let cityToggleIds = [];
let hoodToggleIds = [];

function itemSources(item) {
  return item.sources && item.sources.length ? item.sources : [item.source];
}

function cityKey(item) {
  return item.city && CANONICAL_CITIES.has(item.city) ? item.city : OTHER_CITY;
}

function profileOf(item) {
  return item.neighborhood ? profiles[item.neighborhood] || null : null;
}

function makeChip(id, text, count) {
  const label = document.createElement("label");
  label.className = "chip";
  const input = document.createElement("input");
  input.type = "checkbox";
  input.id = id;
  input.checked = true;
  label.appendChild(input);
  label.appendChild(document.createTextNode(count === undefined ? text : text + " (" + count + ")"));
  return label;
}

function buildCityToggles(allListings) {
  const counts = new Map();
  allListings.forEach((item) => {
    const key = cityKey(item);
    counts.set(key, (counts.get(key) || 0) + 1);
  });
  const keys = Array.from(counts.keys()).sort((a, b) => {
    const ra = a === OTHER_CITY ? 99 : CITY_RANK[a];
    const rb = b === OTHER_CITY ? 99 : CITY_RANK[b];
    return ra - rb;
  });
  const container = document.getElementById("city-toggles");
  container.replaceChildren();
  cityToggleIds = keys.map((key) => "city-" + key);
  keys.forEach((key) => {
    container.appendChild(makeChip("city-" + key, key === OTHER_CITY ? "אחר" : key, counts.get(key)));
  });
}

function buildNeighborhoodToggles(allListings) {
  const counts = new Map();
  allListings.forEach((item) => {
    if (item.neighborhood && profiles[item.neighborhood]) {
      counts.set(item.neighborhood, (counts.get(item.neighborhood) || 0) + 1);
    }
  });
  const byCity = new Map();
  counts.forEach((count, id) => {
    const city = profiles[id].city;
    if (!byCity.has(city)) byCity.set(city, []);
    byCity.get(city).push(id);
  });
  const container = document.getElementById("neighborhood-toggles");
  container.replaceChildren();
  hoodToggleIds = [];
  Array.from(byCity.keys())
    .sort((a, b) => (CITY_RANK[a] ?? 99) - (CITY_RANK[b] ?? 99))
    .forEach((city) => {
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = city;
      details.appendChild(summary);
      const chips = document.createElement("div");
      chips.className = "chips";
      byCity.get(city)
        .sort((a, b) => counts.get(b) - counts.get(a))
        .forEach((id) => {
          hoodToggleIds.push("hood-" + id);
          chips.appendChild(makeChip("hood-" + id, profiles[id].names[0], counts.get(id)));
        });
      details.appendChild(chips);
      container.appendChild(details);
    });
}

function cityRank(item) {
  const rank = CITY_RANK[item.city];
  return rank === undefined ? 3 : rank;
}

function timestampValue(item) {
  return item.first_seen_at ? Date.parse(item.first_seen_at) : -Infinity;
}

function nullsLast(a, b) {
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  return a - b;
}

const SORT_COMPARATORS = {
  newest: (a, b) => timestampValue(b) - timestampValue(a),
  cheapest: (a, b) => nullsLast(a.price, b.price),
  nearest: (a, b) => nullsLast(a.drive_minutes, b.drive_minutes),
  preference: (a, b) => {
    const rankDiff = cityRank(a) - cityRank(b);
    return rankDiff !== 0 ? rankDiff : timestampValue(b) - timestampValue(a);
  },
};

function safeHttpUrl(value) {
  try {
    const url = new URL(value, window.location.href);
    if (url.protocol === "http:" || url.protocol === "https:") return url.href;
  } catch (err) {
    /* fall through */
  }
  return null;
}

function readControls() {
  const state = {};
  CONTROLS.forEach((id) => {
    state[id] = Number(document.getElementById(id).value);
  });
  TOGGLES.forEach((id) => {
    state[id] = document.getElementById(id).checked;
  });
  state.sort = document.getElementById("sort").value;
  sourceToggleIds.forEach((id) => {
    state[id] = document.getElementById(id).checked;
  });
  cityToggleIds.forEach((id) => {
    state[id] = document.getElementById(id).checked;
  });
  hoodToggleIds.forEach((id) => {
    state[id] = document.getElementById(id).checked;
  });
  return state;
}

function applyControls(state) {
  CONTROLS.forEach((id) => {
    if (state[id] !== undefined) document.getElementById(id).value = state[id];
    document.getElementById(id + "-out").value = document.getElementById(id).value;
  });
  TOGGLES.forEach((id) => {
    if (state[id] !== undefined) document.getElementById(id).checked = state[id];
  });
  if (state.sort !== undefined) document.getElementById("sort").value = state.sort;
  // Any source id absent from saved state (new source, or state predates the
  // toggle) defaults to enabled so nothing is silently hidden.
  sourceToggleIds.forEach((id) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.checked = state[id] !== undefined ? state[id] : true;
  });
  cityToggleIds.forEach((id) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.checked = state[id] !== undefined ? state[id] : true;
  });
  hoodToggleIds.forEach((id) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.checked = state[id] !== undefined ? state[id] : true;
  });
}

function buildSourceToggles(allListings) {
  const distinct = Array.from(new Set(allListings.flatMap(itemSources))).sort();
  const container = document.getElementById("source-toggles");
  container.replaceChildren();
  sourceToggleIds = distinct.map((source) => "source-" + source);

  distinct.forEach((source) => {
    const label = document.createElement("label");
    label.className = "chip";

    const input = document.createElement("input");
    input.type = "checkbox";
    input.id = "source-" + source;
    input.checked = true;
    label.appendChild(input);

    label.appendChild(document.createTextNode(source));
    container.appendChild(label);
  });
}

function saveState(state) {
  // Wrapped because private-mode browsers throw rather than no-op here.
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch (err) {
    /* a portal that cannot remember preferences still works fine */
  }
}

function loadState() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {};
  } catch (err) {
    return {};
  }
}

function matches(item, state) {
  // Unknown values do not disqualify, matching the alert filter's behaviour.
  if (item.occupancy === "roommates") return false;
  if (item.occupancy === "unsure" && !state["include-unsure"]) return false;

  if (item.is_sublet && !state["include-sublets"]) return false;

  if (item.price === null) {
    if (!state["include-no-price"]) return false;
  } else if (item.price < state["min-price"] || item.price > state["max-price"]) {
    return false;
  }

  if (item.rooms !== null && item.rooms < state["min-rooms"]) return false;
  if (item.size_sqm !== null && item.size_sqm < state["min-size"]) return false;
  if (item.drive_minutes !== null && item.drive_minutes > state["max-drive"]) {
    return false;
  }
  if (item.distance_km !== null && item.distance_km > state["max-km"]) {
    return false;
  }

  // A listing survives if at least one of its sources is toggled on. An
  // unrecognised source (toggle removed since the state was saved) defaults
  // to enabled rather than disappearing silently.
  const enabled = itemSources(item).some((source) => state["source-" + source] !== false);
  if (!enabled) return false;

  if (state["city-" + cityKey(item)] === false) return false;
  if (item.neighborhood && state["hood-" + item.neighborhood] === false) return false;

  return true;
}

function isNew(item) {
  if (!item.first_seen_at) return false;
  return Date.now() - Date.parse(item.first_seen_at) < 24 * 60 * 60 * 1000;
}

function card(item) {
  const el = document.createElement("article");
  el.className = "card";

  const price = item.price === null ? "מחיר לא צוין" : item.price.toLocaleString("he-IL") + " ₪";
  const facts = [];
  if (item.rooms !== null) facts.push(item.rooms + " חד'");
  if (item.size_sqm !== null) facts.push(item.size_sqm + ' מ"ר');
  if (item.drive_minutes !== null) facts.push("🚗 " + Math.round(item.drive_minutes) + " דק'");
  if (item.distance_km !== null) facts.push("📍 " + item.distance_km + ' ק"מ');

  if (item.photos && item.photos.length) {
    const photoUrl = safeHttpUrl(item.photos[0]);
    if (photoUrl) {
      const img = document.createElement("img");
      img.loading = "lazy";
      img.alt = "";
      img.src = photoUrl;
      el.appendChild(img);
    }
  }

  const body = document.createElement("div");
  body.className = "body";

  if (isNew(item)) {
    const badgeNew = document.createElement("span");
    badgeNew.className = "badge new";
    badgeNew.textContent = "חדש";
    body.appendChild(badgeNew);
  }

  if (item.is_sublet) {
    const badgeSublet = document.createElement("span");
    badgeSublet.className = "badge sublet";
    badgeSublet.textContent = "סאבלט";
    body.appendChild(badgeSublet);
  }

  const badgeSource = document.createElement("span");
  badgeSource.className = "badge source";
  badgeSource.textContent = item.source;
  body.appendChild(badgeSource);

  const srcs = itemSources(item);
  if (srcs.length > 1) {
    const badgeMulti = document.createElement("span");
    badgeMulti.className = "badge multi";
    badgeMulti.textContent = srcs.length + " מקורות";
    body.appendChild(badgeMulti);
  }

  const h2 = document.createElement("h2");
  h2.textContent = price;
  body.appendChild(h2);

  const factsP = document.createElement("p");
  factsP.textContent = facts.join(" · ");
  body.appendChild(factsP);

  const addrP = document.createElement("p");
  addrP.className = "addr";
  addrP.textContent = item.address_text || item.city || "";
  body.appendChild(addrP);

  const profile = profileOf(item);
  if (profile) {
    const hood = document.createElement("p");
    hood.className = "hood";
    const name = document.createElement("span");
    name.className = "hood-name";
    name.textContent = profile.names[0];
    hood.appendChild(name);
    const pill = document.createElement("span");
    pill.className = "pill rep-" + profile.reputation;
    pill.textContent = REPUTATION_LABELS[profile.reputation] || profile.reputation;
    hood.appendChild(pill);
    profile.tags.slice(0, 3).forEach((tag) => {
      const chip = document.createElement("span");
      chip.className = "tag";
      chip.textContent = TAG_LABELS[tag] || tag;
      hood.appendChild(chip);
    });
    body.appendChild(hood);

    const details = document.createElement("details");
    details.className = "hood-details";
    const summary = document.createElement("summary");
    summary.textContent = "פרטים על השכונה";
    details.appendChild(summary);
    const summaryP = document.createElement("p");
    summaryP.textContent = profile.summary;
    details.appendChild(summaryP);
    [["יתרונות", profile.pros], ["חסרונות", profile.cons]].forEach(([title, items]) => {
      const h = document.createElement("strong");
      h.textContent = title;
      details.appendChild(h);
      const ul = document.createElement("ul");
      items.forEach((text) => {
        const li = document.createElement("li");
        li.textContent = text;
        ul.appendChild(li);
      });
      details.appendChild(ul);
    });
    body.appendChild(details);
  }

  if (item.lat !== null && item.lon !== null) {
    const sv = document.createElement("a");
    sv.className = "streetview";
    sv.textContent = "Street View";
    sv.target = "_blank";
    sv.rel = "noopener noreferrer";
    const svUrl = safeHttpUrl("https://www.google.com/maps?layer=c&cbll=" + item.lat + "," + item.lon);
    if (svUrl) sv.href = svUrl;
    body.appendChild(sv);
    body.appendChild(document.createTextNode(" · "));
  }

  const link = document.createElement("a");
  link.textContent = "למודעה המקורית";
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  const linkUrl = safeHttpUrl(item.url);
  if (linkUrl) {
    link.href = linkUrl;
  }
  body.appendChild(link);

  el.appendChild(body);
  return el;
}

function popupContent(item) {
  const wrap = document.createElement("div");
  const priceEl = document.createElement("b");
  priceEl.textContent = item.price === null ? "מחיר לא צוין" : item.price.toLocaleString("he-IL") + " ₪";
  wrap.appendChild(priceEl);
  wrap.appendChild(document.createElement("br"));
  const profile = profileOf(item);
  if (profile) {
    wrap.appendChild(document.createTextNode(profile.names[0]));
    wrap.appendChild(document.createElement("br"));
  }
  const link = document.createElement("a");
  link.textContent = "למודעה";
  const url = safeHttpUrl(item.url);
  if (url) link.href = url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  wrap.appendChild(link);
  return wrap;
}

function renderMap(visible) {
  if (!map) {
    map = L.map("map").setView(CENTRE, 13);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(map);
    markerLayer = L.layerGroup().addTo(map);

    L.circleMarker(CENTRE, {
      radius: 8,
      color: "#b42318",
      fillColor: "#b42318",
      fillOpacity: 0.9,
    })
      .bindPopup("נקודת הייחוס")
      .addTo(map);
  }

  markerLayer.clearLayers();
  visible.forEach((item) => {
    if (item.lat === null || item.lon === null) return;
    L.circleMarker([item.lat, item.lon], {
      radius: 6,
      color: "#1f6feb",
      fillColor: "#1f6feb",
      fillOpacity: 0.75,
    })
      .bindPopup(popupContent(item))
      .addTo(markerLayer);
  });
}

function render() {
  const state = readControls();
  applyControls(state);
  saveState(state);

  const visible = listings.filter((item) => matches(item, state));
  const comparator = SORT_COMPARATORS[state.sort] || SORT_COMPARATORS.newest;
  visible.sort(comparator);

  const results = document.getElementById("results");
  results.replaceChildren(...visible.map(card));

  document.getElementById("summary").textContent =
    visible.length + " מתוך " + listings.length + " מודעות";

  renderMap(visible);
}

function renderHealth(health, generatedAt) {
  const nodes = [
    document.createTextNode(
      "עודכן: " + new Date(generatedAt).toLocaleString("he-IL") + " · "
    ),
  ];
  Object.entries(health || {}).forEach(([source, entry], index) => {
    const broken = entry.consecutive_failures >= 3;
    if (index > 0) nodes.push(document.createTextNode(" "));
    const span = document.createElement("span");
    span.className = broken ? "bad" : "good";
    span.textContent =
      source + (broken ? " ✕" : " ✓") + (entry.detail ? ` (${entry.detail})` : "");
    nodes.push(span);
  });
  document.getElementById("health").replaceChildren(...nodes);
}

function wire() {
  CONTROLS.concat(TOGGLES).forEach((id) => {
    document.getElementById(id).addEventListener("input", render);
  });
  document.getElementById("sort").addEventListener("input", render);
  sourceToggleIds.forEach((id) => {
    document.getElementById(id).addEventListener("input", render);
  });
  cityToggleIds.forEach((id) => {
    document.getElementById(id).addEventListener("input", render);
  });
  hoodToggleIds.forEach((id) => {
    document.getElementById(id).addEventListener("input", render);
  });
  document.getElementById("reset").addEventListener("click", () => {
    applyControls({
      "max-drive": defaults.max_drive_minutes,
      "min-price": defaults.min_price,
      "max-price": defaults.max_price,
      "min-rooms": defaults.min_rooms,
      "min-size": defaults.min_size_sqm,
      "max-km": defaults.max_distance_km,
      "include-no-price": defaults.include_price_missing,
      "include-unsure": defaults.include_unsure_occupancy,
      "include-sublets": !defaults.exclude_sublets,
      sort: "newest",
    });
    // Reset also re-enables every source, city, and neighborhood chip.
    sourceToggleIds.forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.checked = true;
    });
    cityToggleIds.forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.checked = true;
    });
    hoodToggleIds.forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.checked = true;
    });
    render();
  });
}

Promise.all([
  fetch("data/listings.json").then((response) => response.json()),
  fetch("data/neighborhoods.json").then((response) => (response.ok ? response.json() : {})).catch(() => ({})),
])
  .then(([data, loadedProfiles]) => {
    profiles = loadedProfiles || {};
    listings = data.listings || [];
    defaults = data.defaults || {};
    buildSourceToggles(listings);
    buildCityToggles(listings);
    buildNeighborhoodToggles(listings);

    const saved = loadState();
    applyControls({
      "max-drive": defaults.max_drive_minutes,
      "min-price": defaults.min_price,
      "max-price": defaults.max_price,
      "min-rooms": defaults.min_rooms,
      "min-size": defaults.min_size_sqm,
      "max-km": defaults.max_distance_km,
      "include-no-price": defaults.include_price_missing,
      "include-unsure": defaults.include_unsure_occupancy,
      "include-sublets": !defaults.exclude_sublets,
      sort: "newest",
      ...saved,
    });

    wire();
    render();
    renderHealth(data.health, data.generated_at);
  })
  .catch(() => {
    document.getElementById("summary").textContent = "שגיאה בטעינת הנתונים";
  });
