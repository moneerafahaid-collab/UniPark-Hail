function toast(message) {
  const el = document.getElementById("toast");
  if (!el || !message) return;
  el.textContent = message;
  el.classList.add("show");
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => el.classList.remove("show"), 3400);
}

function csrfToken() {
  const meta = document.querySelector('meta[name="csrf"]');
  return meta ? meta.content : "";
}

async function api(url, body) {
  const options = { method: body ? "POST" : "GET", headers: {} };
  if (body) {
    options.headers["Content-Type"] = "application/json";
    options.headers["X-CSRF-Token"] = csrfToken();
    options.body = JSON.stringify(body);
  }
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({ ok: false, message: "تعذر قراءة الرد" }));
  data.status = response.status;
  return data;
}

function formatTime(iso) {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat("ar-SA", {
    timeZone: "Asia/Riyadh",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatDistance(meters) {
  const value = Math.round(meters);
  if (value >= 1000) return (value / 1000).toFixed(1) + " كم";
  return value + " م";
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}
