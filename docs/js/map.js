const ZONES = [
  { code: "A", name: "مواقف البوابة الرئيسية", count: 16, lat: 27.67555, lng: 41.71035 },
  { code: "B", name: "مواقف الكليات العلمية", count: 16, lat: 27.67385, lng: 41.71355 },
  { code: "C", name: "مواقف الكليات الصحية", count: 12, lat: 27.67195, lng: 41.71055 },
  { code: "D", name: "مواقف أعضاء هيئة التدريس", count: 12, lat: 27.67415, lng: 41.70875 }
];
const SHOWCASE = new Set(["A15", "B15", "C10", "D08"]);
const DEMO_POINT = { lat: 27.6744, lng: 41.7109 };
const STATUS = { available: "متاح", occupied: "مشغول", reserved: "محجوز" };

const zones = ZONES.map((zone) => {
  const spots = [];
  for (let n = 1; n <= zone.count; n += 1) {
    const code = zone.code + String(n).padStart(2, "0");
    const col = (n - 1) % 4;
    const row = Math.floor((n - 1) / 4);
    spots.push({
      code,
      zone: zone.name,
      status: SHOWCASE.has(code) || n % 3 === 0 ? "available" : "occupied",
      lat: zone.lat + row * 0.00018,
      lng: zone.lng + (col - 1.5) * 0.00022
    });
  }
  return { ...zone, spots };
});

let selected = null;
let locationPoint = null;
const reserved = new Set(JSON.parse(sessionStorage.getItem("unipark-reserved") || "[]"));
for (const code of reserved) {
  const spot = findSpot(code);
  if (spot) spot.status = "reserved";
}

const who = document.getElementById("who-name");
if (who) who.textContent = sessionStorage.getItem("unipark-name") || "زائر العرض";

function findSpot(code) {
  for (const zone of zones) {
    const spot = zone.spots.find((item) => item.code === code);
    if (spot) return spot;
  }
  return null;
}

function haversine(aLat, aLng, bLat, bLng) {
  const r = 6371000;
  const dLat = (bLat - aLat) * Math.PI / 180;
  const dLng = (bLng - aLng) * Math.PI / 180;
  const h = Math.sin(dLat / 2) ** 2
    + Math.cos(aLat * Math.PI / 180) * Math.cos(bLat * Math.PI / 180) * Math.sin(dLng / 2) ** 2;
  return 2 * r * Math.asin(Math.sqrt(h));
}

function meters(value) {
  return Math.round(value) + " م";
}

function renderLots() {
  const root = document.getElementById("lots");
  root.innerHTML = "";
  for (const zone of zones) {
    const free = zone.spots.filter((spot) => spot.status === "available").length;
    const held = zone.spots.filter((spot) => spot.status === "reserved").length;
    const busy = zone.spots.filter((spot) => spot.status === "occupied").length;
    const section = document.createElement("section");
    section.className = "panel-card lot";
    section.innerHTML = `
      <div class="lot-head">
        <div>
          <h2>${zone.name}</h2>
          <span class="distance">المنطقة ${zone.code}</span>
        </div>
        <div class="counter"><b>${free}</b><span>متاح من ${zone.spots.length}</span></div>
      </div>
      <div class="meter">
        <i class="free" style="width:${(free / zone.spots.length) * 100}%"></i>
        <i class="held" style="width:${(held / zone.spots.length) * 100}%"></i>
        <i class="busy" style="width:${(busy / zone.spots.length) * 100}%"></i>
      </div>`;
    const half = Math.ceil(zone.spots.length / 2);
    section.append(row(zone.spots.slice(0, half)));
    const lane = document.createElement("div");
    lane.className = "lane";
    section.append(lane);
    section.append(row(zone.spots.slice(half)));
    root.append(section);
  }
  const box = document.getElementById("my-res");
  const mine = [...reserved][0];
  if (mine) {
    box.hidden = false;
    box.innerHTML = `حجز العرض على <bdi>${mine}</bdi>`;
  } else {
    box.hidden = true;
    box.innerHTML = "";
  }
}

function row(spots) {
  const wrap = document.createElement("div");
  wrap.className = "bay-grid";
  for (const spot of spots) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `spot ${spot.status}${selected === spot.code ? " selected" : ""}`;
    button.textContent = spot.code;
    button.addEventListener("click", () => selectSpot(spot.code));
    wrap.append(button);
  }
  return wrap;
}

function selectSpot(code) {
  selected = code;
  renderLots();
  renderPanel();
}

function renderPanel() {
  const panel = document.getElementById("panel");
  const spot = selected ? findSpot(selected) : null;
  if (!spot) {
    panel.innerHTML = "<h2>الموقف المختار</h2><p>اختر موقفاً من المخطط أو من الخريطة.</p>";
    return;
  }
  const distance = locationPoint
    ? ` · يبعد ${meters(haversine(locationPoint.lat, locationPoint.lng, spot.lat, spot.lng))}`
    : "";
  panel.innerHTML = `
    <p class="eyebrow">${spot.zone}</p>
    <h2><bdi>${spot.code}</bdi></h2>
    <p>${STATUS[spot.status]}${distance}</p>
    <p class="coords">${spot.lat.toFixed(6)} , ${spot.lng.toFixed(6)}</p>`;
  const actions = document.createElement("div");
  actions.className = "row-actions";
  if (spot.status === "available") {
    const reserve = document.createElement("button");
    reserve.type = "button";
    reserve.textContent = "احجز الموقف";
    reserve.addEventListener("click", () => reserveSpot(spot.code));
    actions.append(reserve);
  }
  const maps = document.createElement("button");
  maps.type = "button";
  maps.className = "secondary";
  maps.textContent = "التوجيه في خرائط Google";
  maps.addEventListener("click", () => {
    window.open(
      `https://www.google.com/maps/dir/?api=1&destination=${spot.lat},${spot.lng}&travelmode=driving`,
      "_blank",
      "noopener"
    );
  });
  actions.append(maps);
  panel.append(actions);
}

function reserveSpot(code) {
  for (const old of reserved) {
    const previous = findSpot(old);
    if (previous) previous.status = "available";
  }
  reserved.clear();
  reserved.add(code);
  findSpot(code).status = "reserved";
  sessionStorage.setItem("unipark-reserved", JSON.stringify([...reserved]));
  renderLots();
  renderPanel();
}

function renderNearest() {
  const root = document.getElementById("nearest");
  if (!locationPoint) {
    root.innerHTML = "";
    return;
  }
  let best = null;
  let bestDistance = Infinity;
  for (const zone of zones) {
    for (const spot of zone.spots) {
      if (spot.status !== "available") continue;
      const distance = haversine(locationPoint.lat, locationPoint.lng, spot.lat, spot.lng);
      if (distance < bestDistance) {
        best = spot;
        bestDistance = distance;
      }
    }
  }
  if (!best) {
    root.innerHTML = "";
    return;
  }
  root.innerHTML = `<section class="panel-card"><h2>أقرب موقف متاح</h2><p><bdi>${best.code}</bdi> على بعد ${meters(bestDistance)}.</p><button type="button" id="pick-nearest">اختيار هذا الموقف</button></section>`;
  document.getElementById("pick-nearest").addEventListener("click", () => selectSpot(best.code));
  document.getElementById("loc-text").textContent = `موقعك داخل الحرم. أقرب موقف متاح هو ${best.code} على بعد ${meters(bestDistance)}.`;
}

document.getElementById("loc-demo").addEventListener("click", () => {
  locationPoint = DEMO_POINT;
  if (window.map) window.map.setView([DEMO_POINT.lat, DEMO_POINT.lng], 17);
  renderNearest();
});

const map = L.map("map", { zoomControl: true }).setView([27.6738, 41.7113], 16);
window.map = map;
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: "&copy; OpenStreetMap"
}).addTo(map);
for (const zone of zones) {
  L.marker([zone.lat, zone.lng]).addTo(map).bindPopup(zone.name);
}

renderLots();
renderPanel();
