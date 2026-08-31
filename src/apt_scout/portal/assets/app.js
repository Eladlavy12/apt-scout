"use strict";

const STORAGE_KEY = "apt-scout-filters";
const CONTROLS = ["max-drive", "min-price", "max-price", "min-rooms", "min-size"];
const TOGGLES = ["include-no-price", "include-unsure"];

let listings = [];
let defaults = {};

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

  const photo = item.photos && item.photos.length
    ? '<img loading="lazy" alt="" src="' + item.photos[0] + '">'
    : "";

  el.innerHTML =
    photo +
    '<div class="body">' +
    (isNew(item) ? '<span class="badge new">חדש</span>' : "") +
    '<span class="badge source">' + item.source + "</span>" +
    "<h2>" + price + "</h2>" +
    "<p>" + facts.join(" · ") + "</p>" +
    "<p class=\"addr\">" + (item.address_text || item.city || "") + "</p>" +
    '<a href="' + item.url + '" target="_blank" rel="noopener noreferrer">למודעה המקורית</a>' +
    "</div>";
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
  const parts = Object.entries(health || {}).map(([source, entry]) => {
    const broken = entry.consecutive_failures >= 3;
    return (
      '<span class="' + (broken ? "bad" : "good") + '">' +
      source + (broken ? " ✕" : " ✓") +
      "</span>"
    );
  });
  document.getElementById("health").innerHTML =
    "עודכן: " + new Date(generatedAt).toLocaleString("he-IL") + " · " + parts.join(" ");
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
