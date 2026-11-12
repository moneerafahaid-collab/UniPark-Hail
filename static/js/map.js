const campus = JSON.parse(document.getElementById("campus-data").textContent);
const state = {
  layout: null,
  selected: null,
  location: null,
  markers: new Map(),
  zonePins: false,
  map: null,
  userMarker: null,
  prevStatus: new Map(),
  panelKey: "",
  busy: false,
};

const STATUS = { Available: "متاح", Occupied: "مشغول", Reserved: "محجوز" };

function haversine(lat1, lon1, lat2, lon2) {
  const radius = 6371000;
  const p1 = (lat1 * Math.PI) / 180;
  const p2 = (lat2 * Math.PI) / 180;
  const dphi = ((lat2 - lat1) * Math.PI) / 180;
  const dl = ((lon2 - lon1) * Math.PI) / 180;
  const a = Math.sin(dphi / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * radius * Math.asin(Math.sqrt(a));
}

function findSpot(code) {
  if (!state.layout) return null;
  for (const zone of state.layout.zones) {
    const spot = zone.spots.find((item) => item.code === code);
    if (spot) return { ...spot, zone_name: zone.zone_name, zone_code: zone.zone_code };
  }
  return null;
}

function initMap() {
  const holder = document.getElementById("map");
  if (!window.L) {
    holder.textContent = "تعذر تحميل الخريطة الخارجية. مخطط المواقف يعمل، ورابط Google يفتح عند التوجيه.";
    return;
  }
  state.map = L.map(holder, { zoomControl: true }).setView(campus.center, 16);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap",
  }).addTo(state.map);
}

function colorFor(status) {
  if (status === "Available") return "#1b8354";
  if (status === "Reserved") return "#b4872d";
  return "#b42318";
}

function syncMarkers() {
  if (!state.map || !state.layout) return;
  const points = [];
  for (const zone of state.layout.zones) {
    if (!state.zonePins) {
      L.marker([zone.center_latitude, zone.center_longitude], {
        interactive: false,
        icon: L.divIcon({
          className: "zone-pin",
          html: `<span>${escapeHtml(zone.zone_code)}</span>`,
          iconSize: [26, 26],
        }),
      }).addTo(state.map);
    }
    for (const spot of zone.spots) {
      points.push([spot.latitude, spot.longitude]);
      let marker = state.markers.get(spot.code);
      if (!marker) {
        marker = L.circleMarker([spot.latitude, spot.longitude], {
          radius: 7,
          color: "#fff",
          weight: 2,
          fillOpacity: 1,
        }).addTo(state.map);
        marker.on("click", () => selectSpot(spot.code));
        state.markers.set(spot.code, marker);
      }
      marker.setStyle({
        fillColor: colorFor(spot.status),
        radius: state.selected === spot.code ? 10 : 7,
      });
    }
  }
  if (!state.zonePins && points.length) {
    state.map.fitBounds(points, { padding: [24, 24] });
    state.zonePins = true;
  }
}

function renderFeed() {
  const bar = document.getElementById("feed-bar");
  const feed = state.layout.feed || {};
  const when = formatTime(state.layout.last_updated);
  if (feed.running) {
    bar.innerHTML = `<i class="dot"></i><span>المحاكي يعمل ويسجّل الحركة. آخر تحديث للحالة ${escapeHtml(when)}</span>`;
  } else {
    bar.innerHTML = `<i class="dot off"></i><span>المحاكي متوقف، وتبقى آخر حالة مسجّلة. آخر تحديث ${escapeHtml(when)}</span>`;
  }
}

function renderReservation() {
  const box = document.getElementById("my-res");
  const mine = state.layout.my_reservation;
  if (!mine) {
    box.hidden = true;
    box.innerHTML = "";
    return;
  }
  box.hidden = false;
  box.innerHTML = `حجزك الساري على <bdi>${escapeHtml(mine.spot_code)}</bdi> حتى ${escapeHtml(formatTime(mine.expires_at))}`;
}

function renderLots() {
  const root = document.getElementById("lots");
  const signature = state.layout.zones.map((zone) => zone.spots.map((spot) => spot.code).join(",")).join("|");
  if (root.dataset.signature !== signature) {
    root.dataset.signature = signature;
    root.innerHTML = "";
    for (const zone of state.layout.zones) {
      const section = document.createElement("section");
      section.className = "panel-card lot";
      section.dataset.zone = zone.zone_code;
      section.innerHTML = `
        <div class="lot-head">
          <div>
            <h2>${escapeHtml(zone.zone_name)}</h2>
            <span class="distance"></span>
          </div>
          <div class="counter"><b></b><span></span></div>
        </div>
        <div class="meter"><i class="free"></i><i class="held"></i><i class="busy"></i></div>`;
      section.querySelector(".lot-head").addEventListener("click", () => {
        if (state.map) state.map.flyTo([zone.center_latitude, zone.center_longitude], 18);
      });
      const half = Math.ceil(zone.spots.length / 2);
      section.append(spotRow(zone.spots.slice(0, half)));
      const lane = document.createElement("div");
      lane.className = "lane";
      section.append(lane);
      section.append(spotRow(zone.spots.slice(half)));
      root.append(section);
    }
  }
  for (const zone of state.layout.zones) {
    const section = root.querySelector(`[data-zone="${zone.zone_code}"]`);
    const total = zone.total_spots || 1;
    const distance = state.location
      ? formatDistance(haversine(state.location.lat, state.location.lng, zone.center_latitude, zone.center_longitude))
      : "";
    section.querySelector(".distance").textContent = distance ? "تبعد " + distance : "المنطقة " + zone.zone_code;
    section.querySelector(".counter b").textContent = zone.available_spots;
    section.querySelector(".counter span").textContent = "متاح من " + zone.total_spots;
    section.querySelector(".free").style.width = (zone.available_spots / total) * 100 + "%";
    section.querySelector(".held").style.width = (zone.reserved_spots / total) * 100 + "%";
    section.querySelector(".busy").style.width = (zone.occupied_spots / total) * 100 + "%";
    for (const spot of zone.spots) {
      const button = section.querySelector(`button[data-code="${spot.code}"]`);
      if (!button) continue;
      const previous = state.prevStatus.get(spot.code);
      button.className = `spot ${spot.status.toLowerCase()}`;
      if (state.selected === spot.code) button.classList.add("selected");
      if (spot.reserved_by_me) button.classList.add("mine");
      if (previous && previous !== spot.status) button.classList.add("just-changed");
      state.prevStatus.set(spot.code, spot.status);
    }
  }
}

function spotRow(spots) {
  const row = document.createElement("div");
  row.className = "bay-grid";
  for (const spot of spots) {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.code = spot.code;
    button.textContent = spot.code;
    button.addEventListener("click", () => selectSpot(spot.code));
    row.append(button);
  }
  return row;
}

function renderNearest() {
  const root = document.getElementById("nearest");
  root.innerHTML = "";
  if (!state.location || !state.layout) return;
  let best = null;
  let bestDistance = Infinity;
  for (const zone of state.layout.zones) {
    for (const spot of zone.spots) {
      if (spot.status !== "Available") continue;
      const distance = haversine(state.location.lat, state.location.lng, spot.latitude, spot.longitude);
      if (distance < bestDistance) {
        best = spot;
        bestDistance = distance;
      }
    }
  }
  if (!best) {
    root.innerHTML = "";
    state.nearestCode = "";
    return;
  }
  if (state.nearestCode === best.code && root.firstChild) return;
  state.nearestCode = best.code;
  const place = document.getElementById("loc-text");
  if (place && state.location) {
    const where = state.location.inside ? "موقعك داخل الحرم." : "موقعك خارج نطاق الحرم.";
    place.textContent = `${where} أقرب موقف متاح الآن هو ${best.code} على بعد ${formatDistance(bestDistance)}.`;
  }
  const card = document.createElement("section");
  card.className = "panel-card";
  card.innerHTML = `<h2>أقرب موقف متاح</h2><p><bdi>${escapeHtml(best.code)}</bdi> على بعد ${escapeHtml(formatDistance(bestDistance))}.</p>`;
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = "اختيار هذا الموقف";
  button.addEventListener("click", () => selectSpot(best.code));
  card.append(button);
  root.append(card);
}

function renderPanel() {
  const spot = state.selected ? findSpot(state.selected) : null;
  const distance = spot && state.location
    ? formatDistance(haversine(state.location.lat, state.location.lng, spot.latitude, spot.longitude))
    : "";
  const key = spot ? `${spot.code}|${spot.status}|${spot.reserved_until}|${distance}` : "";
  if (key === state.panelKey) return;
  state.panelKey = key;
  const panel = document.getElementById("panel");
  if (!spot) {
    panel.innerHTML = "<h2>الموقف المختار</h2><p>اختر موقفاً من المخطط أو من الخريطة.</p>";
    return;
  }
  panel.innerHTML = `
    <p class="eyebrow">${escapeHtml(spot.zone_name)}</p>
    <h2><bdi>${escapeHtml(spot.code)}</bdi></h2>
    <p>${STATUS[spot.status] || escapeHtml(spot.status)}${distance ? " · يبعد " + escapeHtml(distance) : ""}</p>
    <p class="coords">${Number(spot.latitude).toFixed(6)} , ${Number(spot.longitude).toFixed(6)}</p>`;
  const actions = document.createElement("div");
  actions.className = "row-actions";
  if (spot.status === "Available") {
    const duration = document.createElement("select");
    duration.innerHTML = `<option value="30">30 دقيقة</option><option value="60" selected>60 دقيقة</option><option value="90">90 دقيقة</option>`;
    const reserve = document.createElement("button");
    reserve.type = "button";
    reserve.textContent = "احجز الموقف";
    reserve.addEventListener("click", () => book(spot.code, Number(duration.value)));
    actions.append(duration, reserve, navigateButton(spot.code));
  } else if (spot.reserved_by_me) {
    panel.insertAdjacentHTML("beforeend", `<p>هذا حجزك حتى ${escapeHtml(formatTime(spot.reserved_until))}.</p>`);
    actions.append(navigateButton(spot.code), actionButton("تأكيد الوصول", "secondary", () => arrive()), actionButton("إلغاء الحجز", "danger", () => cancelBooking()));
  } else if (spot.status === "Occupied") {
    panel.insertAdjacentHTML("beforeend", "<p>لا يمكن اختيار موقف مشغول.</p>");
  } else {
    panel.insertAdjacentHTML("beforeend", "<p>هذا الموقف محجوز لمستخدم آخر.</p>");
  }
  panel.append(actions);
}

function navigateButton(code) {
  const form = document.createElement("form");
  form.method = "post";
  form.action = "/navigate";
  form.target = "_blank";
  const csrf = document.createElement("input");
  csrf.type = "hidden";
  csrf.name = "csrf_token";
  csrf.value = csrfToken();
  const spot = document.createElement("input");
  spot.type = "hidden";
  spot.name = "spot_code";
  spot.value = code;
  const button = document.createElement("button");
  button.type = "submit";
  button.className = "secondary";
  button.textContent = "التوجيه في خرائط Google";
  form.append(csrf, spot, button);
  return form;
}

function actionButton(label, kind, handler) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = kind;
  button.textContent = label;
  button.addEventListener("click", handler);
  return button;
}

function selectSpot(code) {
  state.selected = code;
  state.panelKey = "";
  renderLots();
  renderPanel();
  syncMarkers();
  const spot = findSpot(code);
  if (state.map && spot) state.map.panTo([spot.latitude, spot.longitude]);
  if (window.innerWidth < 980) {
    document.getElementById("panel").scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

async function book(code, minutes) {
  if (state.busy) return;
  state.busy = true;
  const body = { spot_code: code, minutes };
  if (state.location) {
    body.latitude = state.location.lat;
    body.longitude = state.location.lng;
  }
  const result = await api("/api/reserve", body);
  state.busy = false;
  toast(result.message);
  if (result.ok) await loadLayout();
}

async function cancelBooking() {
  const mine = state.layout && state.layout.my_reservation;
  if (!mine || state.busy) return;
  state.busy = true;
  const result = await api(`/api/reservations/${mine.id}/cancel`, { ok: true });
  state.busy = false;
  toast(result.message);
  await loadLayout();
}

async function arrive() {
  const mine = state.layout && state.layout.my_reservation;
  if (!mine || state.busy) return;
  state.busy = true;
  const result = await api(`/api/reservations/${mine.id}/arrive`, { ok: true });
  state.busy = false;
  toast(result.message);
  await loadLayout();
}

async function sendLocation(lat, lng) {
  const result = await api("/api/location", { latitude: lat, longitude: lng });
  if (!result.ok) {
    toast(result.message);
    return;
  }
  state.location = { lat, lng, inside: result.inside_campus };
  document.getElementById("loc-text").textContent = result.message;
  if (state.map) {
    if (!state.userMarker) {
      state.userMarker = L.circleMarker([lat, lng], {
        radius: 8,
        color: "#1a2421",
        weight: 2,
        fillColor: "#f0d48a",
        fillOpacity: 1,
      }).addTo(state.map);
    } else {
      state.userMarker.setLatLng([lat, lng]);
    }
    state.map.panTo([lat, lng]);
  }
  toast(result.message);
  if (result.nearest_available) selectSpot(result.nearest_available.code);
  else {
    renderLots();
    renderNearest();
  }
}

let loading = false;
async function loadLayout() {
  if (loading) return;
  loading = true;
  try {
    const data = await api("/api/layout");
    if (!data.ok) return;
    state.layout = data;
    renderFeed();
    renderReservation();
    renderLots();
    renderNearest();
    renderPanel();
    syncMarkers();
  } finally {
    loading = false;
  }
}

document.getElementById("loc-real").addEventListener("click", () => {
  if (!navigator.geolocation) {
    toast("المتصفح لا يدعم تحديد الموقع");
    return;
  }
  navigator.geolocation.getCurrentPosition(
    (position) => sendLocation(position.coords.latitude, position.coords.longitude),
    () => toast("تعذر قراءة الموقع. يمكنك تجربة النقطة داخل الحرم")
  );
});

document.getElementById("loc-demo").addEventListener("click", () => {
  sendLocation(campus.demo_point[0], campus.demo_point[1]);
});

initMap();
loadLayout();
setInterval(loadLayout, 1500);
