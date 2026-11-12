"""UniPark Hail — منصة مواقف جامعة حائل.

تشغيل النظام:
    python app.py
ثم افتح http://127.0.0.1:5050
"""

import os
import secrets
from datetime import timedelta, timezone
from functools import wraps

from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

import database
from simulator import SensorFeed

ADMIN_ROLES = {"security", "administration"}
ROLE_LABELS = {
    "student": "طالب",
    "faculty": "عضو هيئة تدريس",
    "staff": "موظف",
    "security": "أمن الحرم",
    "administration": "إدارة الحرم",
}
STATUS_AR = {
    "Available": "متاح",
    "Occupied": "مشغول",
    "Reserved": "محجوز",
    "active": "ساري",
    "completed": "اكتمل بالوصول",
    "cancelled": "ملغى",
    "expired": "انتهى",
    "arrival": "وصول",
    "departure": "مغادرة",
}
RIYADH = timezone(timedelta(hours=3))

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("UNIPARK_SECRET", ""),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    MAX_CONTENT_LENGTH=1024 * 1024,
    JSON_AS_ASCII=False,
)
app.json.ensure_ascii = False
feed = SensorFeed(interval=5)


def load_secret():
    if app.config["SECRET_KEY"]:
        return app.config["SECRET_KEY"]
    folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instance")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "secret.key")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            return handle.read().strip()
    key = secrets.token_hex(32)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(key)
    return key


app.config["SECRET_KEY"] = load_secret()


def ensure_csrf():
    token = session.get("csrf")
    if not token:
        token = secrets.token_hex(16)
        session["csrf"] = token
    return token


def csrf_ok():
    sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or ""
    expected = session.get("csrf") or ""
    if not sent or not expected or len(sent) != len(expected):
        return False
    return secrets.compare_digest(sent, expected)


@app.before_request
def guard_csrf():
    if request.method != "POST":
        return None
    if csrf_ok():
        return None
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "message": "حدّث الصفحة ثم أعد المحاولة"}), 400
    flash("حدّث الصفحة ثم أعد المحاولة", "error")
    return redirect(url_for("login"))


@app.context_processor
def inject_template_data():
    return {
        "csrf_token": ensure_csrf(),
        "role_label": ROLE_LABELS.get(session.get("role", ""), ""),
        "status_ar": STATUS_AR,
        "role_labels": ROLE_LABELS,
    }


@app.template_filter("riyadh")
def riyadh(value):
    if not value:
        return "—"
    from datetime import datetime

    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(RIYADH).strftime("%d/%m/%Y %H:%M")


@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "message": "يلزم تسجيل الدخول"}), 401
            return redirect(url_for("login"))
        return fn(*args, **kwargs)

    return wrapper


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "message": "يلزم تسجيل الدخول"}), 401
            return redirect(url_for("login"))
        if session.get("role") not in ADMIN_ROLES:
            if request.path.startswith("/api/"):
                return jsonify(
                    {"ok": False, "message": "ملخص المناطق لأمن الحرم والإدارة فقط"}
                ), 403
            flash("ملخص المناطق متاح لأمن الحرم والإدارة فقط", "error")
            return redirect(url_for("map_page"))
        return fn(*args, **kwargs)

    return wrapper


def _minutes(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


@app.get("/")
def home():
    if session.get("user_id"):
        return redirect(url_for("map_page"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id") and request.method == "GET":
        return redirect(url_for("map_page"))
    if request.method == "POST":
        user = database.authenticate(
            request.form.get("email", ""), request.form.get("password", "")
        )
        if user is None:
            flash("البريد أو كلمة المرور غير صحيحة", "error")
            return redirect(url_for("login"))
        session["user_id"] = user["id"]
        session["name"] = user["full_name"]
        session["role"] = user["role"]
        session.permanent = True
        return redirect(url_for("map_page"))
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        if request.form.get("password") != request.form.get("confirm", ""):
            flash("تأكيد كلمة المرور غير مطابق", "error")
            return redirect(url_for("register"))
        result = database.register_user(
            request.form.get("full_name", ""),
            request.form.get("email", ""),
            request.form.get("password", ""),
            request.form.get("role", ""),
            request.form.get("phone", ""),
        )
        if not result["ok"]:
            flash(result["message"], "error")
            return redirect(url_for("register"))
        user = database.authenticate(
            request.form.get("email", ""), request.form.get("password", "")
        )
        session["user_id"] = user["id"]
        session["name"] = user["full_name"]
        session["role"] = user["role"]
        session.permanent = True
        flash("تم إنشاء الحساب. يمكنك الآن حجز موقف.", "ok")
        return redirect(url_for("map_page"))
    return render_template("register.html")


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/map")
@login_required
def map_page():
    return render_template("map.html", campus=database.CAMPUS)


@app.get("/reservations")
@login_required
def reservations_page():
    return render_template(
        "reservations.html",
        reservations=database.list_reservations(session["user_id"]),
        free_spots=database.list_available_spots(),
    )


@app.post("/reserve")
@login_required
def reserve_form():
    result = database.reserve_spot(
        session["user_id"],
        request.form.get("spot_code", ""),
        _minutes(request.form.get("minutes")),
    )
    flash(result["message"], "ok" if result["ok"] else "error")
    return redirect(url_for("reservations_page"))


@app.post("/reservations/<int:reservation_id>/cancel")
@login_required
def cancel_form(reservation_id):
    result = database.cancel_reservation(session["user_id"], reservation_id)
    flash(result["message"], "ok" if result["ok"] else "error")
    return redirect(url_for("reservations_page"))


@app.post("/reservations/<int:reservation_id>/arrive")
@login_required
def arrive_form(reservation_id):
    result = database.confirm_arrival(session["user_id"], reservation_id)
    flash(result["message"], "ok" if result["ok"] else "error")
    return redirect(url_for("reservations_page"))


@app.post("/navigate")
@login_required
def navigate_form():
    result = database.prepare_navigation(
        session["user_id"], request.form.get("spot_code", "")
    )
    if not result["ok"]:
        return render_template("navigate_result.html", result=result), 409
    return redirect(result["maps_url"])


@app.get("/admin")
@admin_required
def admin_page():
    return render_template("admin.html")


@app.get("/api/layout")
@login_required
def api_layout():
    data = database.display_layout(session["user_id"])
    data["ok"] = True
    data["feed"] = feed.status()
    return jsonify(data)


@app.post("/api/location")
@login_required
def api_location():
    payload = request.get_json(silent=True) or {}
    result = database.locate_user(
        session["user_id"], payload.get("latitude"), payload.get("longitude")
    )
    return jsonify(result), (200 if result["ok"] else 400)


@app.post("/api/reserve")
@login_required
def api_reserve():
    payload = request.get_json(silent=True) or {}
    result = database.reserve_spot(
        session["user_id"],
        payload.get("spot_code", ""),
        _minutes(payload.get("minutes")),
        payload.get("latitude"),
        payload.get("longitude"),
    )
    return jsonify(result), (200 if result["ok"] else 409)


@app.post("/api/reservations/<int:reservation_id>/cancel")
@login_required
def api_cancel(reservation_id):
    result = database.cancel_reservation(session["user_id"], reservation_id)
    return jsonify(result), (200 if result["ok"] else 409)


@app.post("/api/reservations/<int:reservation_id>/arrive")
@login_required
def api_arrive(reservation_id):
    result = database.confirm_arrival(session["user_id"], reservation_id)
    return jsonify(result), (200 if result["ok"] else 409)


@app.post("/api/navigate")
@login_required
def api_navigate():
    payload = request.get_json(silent=True) or {}
    result = database.prepare_navigation(
        session["user_id"], payload.get("spot_code", "")
    )
    return jsonify(result), (200 if result["ok"] else 409)


@app.get("/api/admin/overview")
@admin_required
def api_overview():
    return jsonify(
        {
            "ok": True,
            "zones": database.monitor_zone_utilization(),
            "events": database.list_events(12),
            "navigations": database.list_navigation(12),
            "errors": database.list_errors(12),
            "feed": feed.status(),
            "last_updated": database.latest_update(),
        }
    )


@app.post("/api/simulator/start")
@admin_required
def api_feed_start():
    return jsonify(feed.start())


@app.post("/api/simulator/stop")
@admin_required
def api_feed_stop():
    return jsonify(feed.stop())


@app.post("/api/simulator/tick")
@admin_required
def api_feed_tick():
    result = feed.tick()
    result["feed"] = feed.status()
    return jsonify(result)


@app.post("/api/simulator/unknown")
@admin_required
def api_feed_unknown():
    result = feed.inject_unknown()
    return jsonify(result), 409


database.init_db()


if __name__ == "__main__":
    feed.start()
    print("UniPark Hail: http://127.0.0.1:5050")
    app.run(host="127.0.0.1", port=5050, debug=False, use_reloader=False, threaded=True)
