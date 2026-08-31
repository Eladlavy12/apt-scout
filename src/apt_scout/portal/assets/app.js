"use strict";

const STORAGE_KEY = "apt-scout-filters";
const CONTROLS = ["max-drive", "min-price", "max-price", "min-rooms", "min-size"];
const TOGGLES = ["include-no-price", "include-unsure"];

let listings = [];
let defaults = {};

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

  const badgeSource = document.createElement("span");
  badgeSource.className = "badge source";
  badgeSource.textContent = item.source;
  body.appendChild(badgeSource);

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

function render() {
  const state = readControls();
  applyControls(state);
  saveState(state);

  const visible = listings.filter((item) => matches(item, state));
  const results = document.getElementById("results");
  results.replaceChildren(...visible.map(card));

  document.getElementById("summary").textContent =
    visible.length + " מתוך " + listings.length + " מודעות";
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
    span.textContent = source + (broken ? " ✕" : " ✓");
    nodes.push(span);
  });
  document.getElementById("health").replaceChildren(...nodes);
}

function wire() {
  CONTROLS.concat(TOGGLES).forEach((id) => {
    document.getElementById(id).addEventListener("input", render);
  });
  document.getElementById("reset").addEventListener("click", () => {
    applyControls({
      "max-drive": defaults.max_drive_minutes,
      "min-price": defaults.min_price,
      "max-price": defaults.max_price,
      "min-rooms": defaults.min_rooms,
      "min-size": defaults.min_size_sqm,
      "include-no-price": defaults.include_price_missing,
      "include-unsure": defaults.include_unsure_occupancy,
    });
    render();
  });
}

fetch("data/listings.json")
  .then((response) => response.json())
  .then((data) => {
    listings = data.listings || [];
    defaults = data.defaults || {};

    const saved = loadState();
    applyControls({
      "max-drive": defaults.max_drive_minutes,
      "min-price": defaults.min_price,
      "max-price": defaults.max_price,
      "min-rooms": defaults.min_rooms,
      "min-size": defaults.min_size_sqm,
      "include-no-price": defaults.include_price_missing,
      "include-unsure": defaults.include_unsure_occupancy,
      ...saved,
    });

    wire();
    render();
    renderHealth(data.health, data.generated_at);
  })
  .catch(() => {
    document.getElementById("summary").textContent = "שגיאה בטעינת הנתונים";
  });
