const SOURCE = {
  simulator: "المحاكي",
  user: "المستخدم",
  seed: "بيانات أولية",
  test: "اختبار",
};
const EVENT = { arrival: "وصول", departure: "مغادرة" };

function cell(text) {
  const td = document.createElement("td");
  td.textContent = text;
  return td;
}

function fill(body, rows, builder) {
  body.replaceChildren();
  if (!rows.length) {
    const tr = document.createElement("tr");
    const td = cell("لا توجد بيانات");
    td.colSpan = 4;
    tr.append(td);
    body.append(tr);
    return;
  }
  for (const row of rows) body.append(builder(row));
}

async function refresh() {
  const data = await api("/api/admin/overview");
  if (!data.ok) return;
  const cards = document.getElementById("zone-cards");
  cards.innerHTML = "";
  for (const zone of data.zones) {
    const card = document.createElement("article");
    card.className = "panel-card summary-card";
    card.innerHTML = `<h2>${escapeHtml(zone.zone_name)}</h2>
      <b>${zone.free_spots}</b>
      <p>شاغر من ${zone.total_spots}</p>
      <p>مشغول ${zone.occupied_spots} · محجوز ${zone.reserved_spots}</p>`;
    cards.append(card);
  }
  const feed = data.feed || {};
  document.getElementById("feed-state").textContent = feed.running
    ? "المحاكي يعمل ويسجّل وصولاً أو مغادرة كل " + feed.interval_seconds + " ثوانٍ."
    : "المحاكي متوقف. الحالات الأخيرة ما زالت محفوظة.";
  document.getElementById("last-updated").textContent = "آخر تحديث لحالة موقف: " + formatTime(data.last_updated);
  if (feed.last_event_at) {
    document.getElementById("feed-state").textContent += " آخر نبضة " + formatTime(feed.last_event_at) + ".";
  }
  fill(document.getElementById("events-body"), data.events, (row) => {
    const tr = document.createElement("tr");
    tr.append(cell(row.spot_code), cell(EVENT[row.event_type] || row.event_type), cell(SOURCE[row.source] || row.source), cell(formatTime(row.event_time)));
    return tr;
  });
  fill(document.getElementById("nav-body"), data.navigations, (row) => {
    const tr = document.createElement("tr");
    tr.append(
      cell(row.full_name),
      cell(row.spot_code),
      cell(Number(row.latitude).toFixed(5) + ", " + Number(row.longitude).toFixed(5)),
      cell(formatTime(row.requested_at))
    );
    return tr;
  });
  fill(document.getElementById("error-body"), data.errors, (row) => {
    const tr = document.createElement("tr");
    tr.append(cell(row.message), cell(formatTime(row.created_at)));
    return tr;
  });
}

async function command(url) {
  const result = await api(url, { ok: true });
  toast(result.message || "تم التنفيذ");
  refresh();
}

document.getElementById("feed-start").addEventListener("click", () => command("/api/simulator/start"));
document.getElementById("feed-stop").addEventListener("click", () => command("/api/simulator/stop"));
document.getElementById("feed-tick").addEventListener("click", () => command("/api/simulator/tick"));
document.getElementById("feed-bad").addEventListener("click", () => command("/api/simulator/unknown"));
refresh();
setInterval(refresh, 2000);
