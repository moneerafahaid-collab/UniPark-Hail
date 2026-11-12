"""تخزين UniPark Hail والعمليات المطابقة لمخطط تدفق البيانات.

P1 عرض توفر المواقف
P2 تحديث حالة الموقف من المحاكي
P3 تجهيز التوجيه إلى Google Maps
P4 مراقبة إشغال المناطق
"""

import hashlib
import math
import os
import random
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.path.join(BASE_DIR, "instance", "unipark.db")
LOCK = threading.Lock()

CAMPUS = {
    "name": "جامعة حائل",
    "center": [27.67380, 41.71130],
    "demo_point": [27.67605, 41.71020],
    "bounds": {
        "lat_min": 27.6690,
        "lat_max": 27.6782,
        "lng_min": 41.7065,
        "lng_max": 41.7162,
    },
}

ZONES = [
    ("A", "مواقف البوابة الرئيسية", 24, 27.67555, 41.71035),
    ("B", "مواقف الكليات العلمية", 24, 27.67385, 41.71355),
    ("C", "مواقف الكليات الصحية", 20, 27.67195, 41.71055),
    ("D", "مواقف أعضاء هيئة التدريس", 16, 27.67415, 41.70875),
]
SHOWCASE = {"A15", "B15", "C10", "D08"}
DEMO_PASSWORD = "hail1234"
DEMO_ACCOUNTS = [
    ("طالب تجريبي", "student@uoh.edu.sa", "student"),
    ("عضو هيئة تدريس تجريبي", "faculty@uoh.edu.sa", "faculty"),
    ("أمن الحرم تجريبي", "security@uoh.edu.sa", "security"),
]
ALLOWED_ROLES = {"student", "faculty", "staff"}
RESERVE_MINUTES = {30, 60, 90}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('student','faculty','staff','security','administration')),
    phone TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS zones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zone_code TEXT NOT NULL UNIQUE,
    zone_name TEXT NOT NULL,
    total_spots INTEGER NOT NULL,
    available_spots INTEGER NOT NULL,
    center_latitude REAL NOT NULL,
    center_longitude REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS spots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zone_id INTEGER NOT NULL REFERENCES zones(id),
    code TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK(status IN ('Available','Occupied','Reserved')),
    latitude REAL,
    longitude REAL,
    last_updated TEXT NOT NULL,
    reserved_by INTEGER REFERENCES users(id),
    reserved_until TEXT
);
CREATE TABLE IF NOT EXISTS occupancy_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spot_id INTEGER NOT NULL REFERENCES spots(id),
    event_type TEXT NOT NULL CHECK(event_type IN ('arrival','departure')),
    event_time TEXT NOT NULL,
    source TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS navigation_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    spot_id INTEGER NOT NULL REFERENCES spots(id),
    requested_at TEXT NOT NULL,
    latitude REAL NOT NULL,
    longitude REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS reservations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    spot_id INTEGER NOT NULL REFERENCES spots(id),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('active','completed','cancelled','expired')),
    user_latitude REAL,
    user_longitude REAL
);
CREATE TABLE IF NOT EXISTS location_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    latitude REAL NOT NULL,
    longitude REAL NOT NULL,
    recorded_at TEXT NOT NULL,
    nearest_zone_id INTEGER REFERENCES zones(id),
    distance_meters REAL
);
CREATE TABLE IF NOT EXISTS error_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_spots_zone ON spots(zone_id);
CREATE INDEX IF NOT EXISTS idx_spots_status ON spots(status);
CREATE INDEX IF NOT EXISTS idx_reservations_user ON reservations(user_id, status);
CREATE INDEX IF NOT EXISTS idx_events_spot ON occupancy_events(spot_id);
"""


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def db_file():
    return os.environ.get("UNIPARK_DB", DEFAULT_DB)


def get_conn():
    path = db_file()
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def with_db(fn):
    with LOCK:
        conn = get_conn()
        try:
            result = fn(conn)
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def hash_password(password, salt=None):
    """تحفظ كلمة المرور كملخص مملّح، لا كنص واضح."""
    if salt is None:
        salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return salt.hex() + ":" + digest.hex()


def verify_password(password, stored):
    try:
        salt_hex, _digest = stored.split(":", 1)
        candidate = hash_password(password, bytes.fromhex(salt_hex))
        return secrets.compare_digest(candidate, stored)
    except (ValueError, TypeError, AttributeError):
        return False


def haversine(lat1, lon1, lat2, lon2):
    radius = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def format_distance(meters):
    meters = int(round(meters))
    if meters >= 1000:
        return f"{meters / 1000:.1f} كم"
    return f"{meters} م"


def inside_campus(lat, lng):
    bounds = CAMPUS["bounds"]
    return (
        bounds["lat_min"] <= lat <= bounds["lat_max"]
        and bounds["lng_min"] <= lng <= bounds["lng_max"]
    )


def maps_url(lat, lng):
    return (
        "https://www.google.com/maps/dir/?api=1"
        f"&destination={lat:.6f},{lng:.6f}&travelmode=driving"
    )


def spot_coordinate(index, count, lat, lng):
    cols = 6
    rows = math.ceil(count / cols)
    row, col = divmod(index, cols)
    lat_step = 0.000062
    lng_step = 0.000078
    return (
        round(lat + ((rows - 1) / 2 - row) * lat_step, 7),
        round(lng + (col - (cols - 1) / 2) * lng_step, 7),
    )


def log_error_conn(conn, message):
    conn.execute(
        "INSERT INTO error_logs (message, created_at) VALUES (?, ?)",
        (message, now_iso()),
    )


def log_error(message):
    def op(conn):
        log_error_conn(conn, message)

    with_db(op)


def recalc_zone(conn, zone_id):
    row = conn.execute(
        """
        SELECT COUNT(*) AS total,
               COALESCE(SUM(CASE WHEN status = 'Available' THEN 1 ELSE 0 END), 0) AS free
        FROM spots WHERE zone_id = ?
        """,
        (zone_id,),
    ).fetchone()
    conn.execute(
        "UPDATE zones SET total_spots = ?, available_spots = ? WHERE id = ?",
        (row["total"], row["free"], zone_id),
    )


def recalc_all(conn):
    for row in conn.execute("SELECT id FROM zones"):
        recalc_zone(conn, row["id"])


def release_expired(conn):
    ts = now_iso()
    rows = conn.execute(
        """
        SELECT id, spot_id FROM reservations
        WHERE status = 'active' AND expires_at <= ?
        """,
        (ts,),
    ).fetchall()
    zones = set()
    for row in rows:
        conn.execute(
            "UPDATE reservations SET status = 'expired' WHERE id = ?",
            (row["id"],),
        )
        conn.execute(
            """
            UPDATE spots
            SET status = 'Available', reserved_by = NULL, reserved_until = NULL, last_updated = ?
            WHERE id = ? AND status = 'Reserved'
            """,
            (ts, row["spot_id"]),
        )
        zone = conn.execute(
            "SELECT zone_id FROM spots WHERE id = ?", (row["spot_id"],)
        ).fetchone()
        if zone:
            zones.add(zone["zone_id"])
    for zone_id in zones:
        recalc_zone(conn, zone_id)


def _public_user(row):
    return {
        "id": row["id"],
        "full_name": row["full_name"],
        "email": row["email"],
        "role": row["role"],
        "phone": row["phone"],
    }


def seed(conn):
    ts = now_iso()
    for full_name, email, role in DEMO_ACCOUNTS:
        conn.execute(
            """
            INSERT INTO users (full_name, email, password_hash, role, phone, created_at)
            VALUES (?, ?, ?, ?, NULL, ?)
            """,
            (full_name, email, hash_password(DEMO_PASSWORD), role, ts),
        )
    for zone_code, zone_name, count, lat, lng in ZONES:
        cursor = conn.execute(
            """
            INSERT INTO zones (
                zone_code, zone_name, total_spots, available_spots,
                center_latitude, center_longitude
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (zone_code, zone_name, count, count, lat, lng),
        )
        zone_id = cursor.lastrowid
        for index in range(count):
            number = index + 1
            code = f"{zone_code}{number:02d}"
            latitude, longitude = spot_coordinate(index, count, lat, lng)
            status = "Available" if code in SHOWCASE or number % 3 == 0 else "Occupied"
            conn.execute(
                """
                INSERT INTO spots (
                    zone_id, code, status, latitude, longitude, last_updated
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (zone_id, code, status, latitude, longitude, ts),
            )
    occupied = conn.execute("SELECT id FROM spots WHERE status = 'Occupied'").fetchall()
    for offset, row in enumerate(occupied):
        when = (
            datetime.now(timezone.utc) - timedelta(minutes=5 + offset)
        ).replace(microsecond=0).isoformat()
        conn.execute(
            """
            INSERT INTO occupancy_events (spot_id, event_type, event_time, source)
            VALUES (?, 'arrival', ?, 'seed')
            """,
            (row["id"], when),
        )
    recalc_all(conn)


def init_db():
    with LOCK:
        conn = get_conn()
        try:
            conn.executescript(SCHEMA)
            count = conn.execute("SELECT COUNT(*) AS n FROM zones").fetchone()["n"]
            if count == 0:
                seed(conn)
            conn.commit()
        finally:
            conn.close()


def authenticate(email, password):
    def op(conn):
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?",
            ((email or "").strip().lower(),),
        ).fetchone()
        if row is None or not verify_password(password or "", row["password_hash"]):
            return None
        return _public_user(row)

    return with_db(op)


def register_user(full_name, email, password, role, phone):
    full_name = " ".join((full_name or "").split())
    email = (email or "").strip().lower()
    role = (role or "").strip()
    phone = (phone or "").strip() or None
    if len(full_name) < 3 or len(full_name) > 80:
        return {"ok": False, "message": "اكتب الاسم الكامل من 3 إلى 80 حرفاً"}
    if "@" not in email or "." not in email.split("@")[-1] or " " in email:
        return {"ok": False, "message": "البريد الإلكتروني غير صالح"}
    if role not in ALLOWED_ROLES:
        return {"ok": False, "message": "التسجيل متاح للطالب وعضو هيئة التدريس والموظف"}
    if phone and not all(ch.isdigit() or ch in "+ " for ch in phone):
        return {"ok": False, "message": "رقم الجوال يكتفى فيه بالأرقام"}
    if phone and not 8 <= len(phone.replace(" ", "")) <= 15:
        return {"ok": False, "message": "رقم الجوال غير مكتمل"}
    if not 6 <= len(password or "") <= 128:
        return {"ok": False, "message": "كلمة المرور من 6 أحرف على الأقل"}

    def op(conn):
        exists = conn.execute(
            "SELECT id FROM users WHERE email = ?", (email,)
        ).fetchone()
        if exists:
            return {"ok": False, "message": "هذا البريد مسجّل من قبل"}
        cursor = conn.execute(
            """
            INSERT INTO users (full_name, email, password_hash, role, phone, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (full_name, email, hash_password(password), role, phone, now_iso()),
        )
        return {
            "ok": True,
            "message": "تم إنشاء الحساب",
            "user_id": cursor.lastrowid,
        }

    return with_db(op)


def _spot(conn, code):
    code = (code or "").strip().upper()
    if not code:
        return None, ""
    row = conn.execute("SELECT * FROM spots WHERE code = ?", (code,)).fetchone()
    return row, code


def update_spot_status(code, event_type, source="simulator"):
    """P2: يطبّق وصولاً أو مغادرة ويحدّث العداد."""

    def op(conn):
        release_expired(conn)
        return _apply_status(conn, code, event_type, source)

    return with_db(op)


def _apply_status(conn, code, event_type, source):
    if event_type not in ("arrival", "departure"):
        log_error_conn(conn, f"نوع حدث غير معروف: {event_type}")
        return {"ok": False, "message": "نوع الحدث غير معروف"}
    spot, code = _spot(conn, code)
    if spot is None:
        log_error_conn(conn, f"رمز موقف غير معروف: {code or '—'}")
        return {"ok": False, "message": "رمز الموقف غير معروف"}
    if spot["latitude"] is None or spot["longitude"] is None:
        log_error_conn(conn, f"الموقف {code} بلا إحداثيات")
        return {"ok": False, "message": "الموقف بلا إحداثيات"}
    status = spot["status"]
    if status == "Reserved":
        return {"ok": False, "message": "الموقف محجوز ولن يغيّره المحاكي"}
    if event_type == "arrival":
        if status != "Available":
            return {"ok": True, "message": "الموقف مشغول بالفعل", "unchanged": True}
        new_status = "Occupied"
    else:
        if status != "Occupied":
            return {"ok": True, "message": "الموقف متاح بالفعل", "unchanged": True}
        new_status = "Available"
    ts = now_iso()
    conn.execute(
        """
        UPDATE spots
        SET status = ?, last_updated = ?, reserved_by = NULL, reserved_until = NULL
        WHERE id = ?
        """,
        (new_status, ts, spot["id"]),
    )
    conn.execute(
        """
        INSERT INTO occupancy_events (spot_id, event_type, event_time, source)
        VALUES (?, ?, ?, ?)
        """,
        (spot["id"], event_type, ts, source),
    )
    recalc_zone(conn, spot["zone_id"])
    return {"ok": True, "message": "تم تسجيل الحركة", "code": code, "status": new_status}


def simulate_once():
    def op(conn):
        release_expired(conn)
        available = [
            row["code"]
            for row in conn.execute(
                """
                SELECT code FROM spots
                WHERE status = 'Available' AND latitude IS NOT NULL AND longitude IS NOT NULL
                """
            )
        ]
        occupied = [
            row["code"]
            for row in conn.execute(
                """
                SELECT code FROM spots
                WHERE status = 'Occupied' AND latitude IS NOT NULL AND longitude IS NOT NULL
                """
            )
        ]
        options = [("arrival", code) for code in available] + [
            ("departure", code) for code in occupied
        ]
        if not options:
            return {"ok": False, "message": "لا توجد حركة ممكنة"}
        event_type, code = random.choice(options)
        return _apply_status(conn, code, event_type, "simulator")

    return with_db(op)


def display_layout(user_id):
    """P1: المخطط والرموز والحالة وعدادات الشاغر."""

    def op(conn):
        release_expired(conn)
        zones_out = []
        last_updated = None
        for zone in conn.execute("SELECT * FROM zones ORDER BY zone_code"):
            spots = conn.execute(
                "SELECT * FROM spots WHERE zone_id = ? ORDER BY code",
                (zone["id"],),
            ).fetchall()
            occupied = reserved = 0
            spot_out = []
            for spot in spots:
                if spot["status"] == "Occupied":
                    occupied += 1
                elif spot["status"] == "Reserved":
                    reserved += 1
                if last_updated is None or spot["last_updated"] > last_updated:
                    last_updated = spot["last_updated"]
                spot_out.append(
                    {
                        "code": spot["code"],
                        "status": spot["status"],
                        "latitude": spot["latitude"],
                        "longitude": spot["longitude"],
                        "last_updated": spot["last_updated"],
                        "reserved_by_me": spot["reserved_by"] == user_id,
                        "reserved_until": spot["reserved_until"]
                        if spot["reserved_by"] == user_id
                        else None,
                    }
                )
            zones_out.append(
                {
                    "zone_code": zone["zone_code"],
                    "zone_name": zone["zone_name"],
                    "total_spots": zone["total_spots"],
                    "available_spots": zone["available_spots"],
                    "occupied_spots": occupied,
                    "reserved_spots": reserved,
                    "center_latitude": zone["center_latitude"],
                    "center_longitude": zone["center_longitude"],
                    "spots": spot_out,
                }
            )
        active = conn.execute(
            """
            SELECT r.id, s.code AS spot_code, r.expires_at
            FROM reservations r
            JOIN spots s ON s.id = r.spot_id
            WHERE r.user_id = ? AND r.status = 'active'
            """,
            (user_id,),
        ).fetchone()
        return {
            "zones": zones_out,
            "last_updated": last_updated,
            "my_reservation": dict(active) if active else None,
            "campus": CAMPUS,
        }

    return with_db(op)


def prepare_navigation(user_id, spot_code):
    """P3: التوجيه لموقف متاح، أو لحجز المستخدم نفسه."""

    def op(conn):
        release_expired(conn)
        spot, code = _spot(conn, spot_code)
        if spot is None:
            log_error_conn(conn, f"رمز موقف غير معروف: {code or '—'}")
            return {"ok": False, "message": "رمز الموقف غير معروف"}
        if spot["latitude"] is None or spot["longitude"] is None:
            log_error_conn(conn, f"الموقف {code} بلا إحداثيات")
            return {"ok": False, "message": "هذا الموقف بلا إحداثيات ولا يمكن توجيهك إليه"}
        if spot["status"] == "Occupied":
            return {"ok": False, "message": "لا يمكن التوجيه إلى موقف مشغول"}
        if spot["status"] == "Reserved" and spot["reserved_by"] != user_id:
            return {"ok": False, "message": "هذا الموقف محجوز لمستخدم آخر"}
        if spot["status"] == "Available" or (
            spot["status"] == "Reserved" and spot["reserved_by"] == user_id
        ):
            ts = now_iso()
            conn.execute(
                """
                INSERT INTO navigation_requests (
                    user_id, spot_id, requested_at, latitude, longitude
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, spot["id"], ts, spot["latitude"], spot["longitude"]),
            )
            return {
                "ok": True,
                "message": "تم إرسال إحداثيات الموقف إلى خرائط Google",
                "maps_url": maps_url(spot["latitude"], spot["longitude"]),
                "code": code,
                "latitude": spot["latitude"],
                "longitude": spot["longitude"],
            }
        return {"ok": False, "message": "لا يمكن اختيار هذا الموقف"}

    return with_db(op)


def _optional_point(lat, lng):
    if lat in (None, "") or lng in (None, ""):
        return None, None
    lat_f = float(lat)
    lng_f = float(lng)
    if not (-90 <= lat_f <= 90 and -180 <= lng_f <= 180):
        raise ValueError
    return lat_f, lng_f


def reserve_spot(user_id, code, minutes, lat=None, lng=None):
    if minutes not in RESERVE_MINUTES:
        return {"ok": False, "message": "مدة الحجز 30 أو 60 أو 90 دقيقة"}
    try:
        lat_f, lng_f = _optional_point(lat, lng)
    except (TypeError, ValueError):
        lat_f, lng_f = None, None

    def op(conn):
        release_expired(conn)
        active = conn.execute(
            "SELECT id FROM reservations WHERE user_id = ? AND status = 'active'",
            (user_id,),
        ).fetchone()
        if active:
            return {
                "ok": False,
                "message": "لديك حجز قائم. ألغه أو أكّد وصولك قبل حجز جديد",
            }
        spot, code_u = _spot(conn, code)
        if spot is None:
            log_error_conn(conn, f"رمز موقف غير معروف: {code_u or '—'}")
            return {"ok": False, "message": "رمز الموقف غير معروف"}
        if spot["latitude"] is None or spot["longitude"] is None:
            log_error_conn(conn, f"الموقف {code_u} بلا إحداثيات")
            return {"ok": False, "message": "هذا الموقف بلا إحداثيات"}
        if spot["status"] != "Available":
            return {"ok": False, "message": "يمكن حجز الموقف المتاح فقط"}
        ts = now_iso()
        expires = (
            datetime.now(timezone.utc) + timedelta(minutes=minutes)
        ).replace(microsecond=0).isoformat()
        cursor = conn.execute(
            """
            UPDATE spots
            SET status = 'Reserved', reserved_by = ?, reserved_until = ?, last_updated = ?
            WHERE id = ? AND status = 'Available'
            """,
            (user_id, expires, ts, spot["id"]),
        )
        if cursor.rowcount != 1:
            return {"ok": False, "message": "تعذر الحجز، الموقف لم يعد متاحاً"}
        inserted = conn.execute(
            """
            INSERT INTO reservations (
                user_id, spot_id, created_at, expires_at, status, user_latitude, user_longitude
            ) VALUES (?, ?, ?, ?, 'active', ?, ?)
            """,
            (user_id, spot["id"], ts, expires, lat_f, lng_f),
        )
        recalc_zone(conn, spot["zone_id"])
        return {
            "ok": True,
            "message": f"تم حجز الموقف {code_u} لمدة {minutes} دقيقة",
            "reservation_id": inserted.lastrowid,
            "expires_at": expires,
            "code": code_u,
        }

    return with_db(op)


def cancel_reservation(user_id, reservation_id):
    def op(conn):
        release_expired(conn)
        row = conn.execute(
            """
            SELECT r.*, s.zone_id, s.status AS spot_status, s.reserved_by
            FROM reservations r JOIN spots s ON s.id = r.spot_id
            WHERE r.id = ? AND r.user_id = ?
            """,
            (reservation_id, user_id),
        ).fetchone()
        if row is None or row["status"] != "active":
            return {"ok": False, "message": "لا يوجد حجز ساري بهذا الرقم"}
        ts = now_iso()
        conn.execute(
            "UPDATE reservations SET status = 'cancelled' WHERE id = ?",
            (reservation_id,),
        )
        if row["spot_status"] == "Reserved" and row["reserved_by"] == user_id:
            conn.execute(
                """
                UPDATE spots
                SET status = 'Available', reserved_by = NULL, reserved_until = NULL, last_updated = ?
                WHERE id = ?
                """,
                (ts, row["spot_id"]),
            )
            recalc_zone(conn, row["zone_id"])
        return {"ok": True, "message": "تم إلغاء الحجز وأصبح الموقف متاحاً"}

    return with_db(op)


def confirm_arrival(user_id, reservation_id):
    def op(conn):
        release_expired(conn)
        row = conn.execute(
            """
            SELECT r.*, s.zone_id, s.code, s.status AS spot_status, s.reserved_by
            FROM reservations r JOIN spots s ON s.id = r.spot_id
            WHERE r.id = ? AND r.user_id = ?
            """,
            (reservation_id, user_id),
        ).fetchone()
        if row is None or row["status"] != "active":
            return {"ok": False, "message": "لا يوجد حجز ساري لتأكيد الوصول"}
        if row["spot_status"] != "Reserved" or row["reserved_by"] != user_id:
            return {"ok": False, "message": "تعذر تثبيت الوصول على هذا الموقف"}
        ts = now_iso()
        conn.execute(
            """
            UPDATE spots
            SET status = 'Occupied', reserved_by = NULL, reserved_until = NULL, last_updated = ?
            WHERE id = ?
            """,
            (ts, row["spot_id"]),
        )
        conn.execute(
            "UPDATE reservations SET status = 'completed' WHERE id = ?",
            (reservation_id,),
        )
        conn.execute(
            """
            INSERT INTO occupancy_events (spot_id, event_type, event_time, source)
            VALUES (?, 'arrival', ?, 'user')
            """,
            (row["spot_id"], ts),
        )
        recalc_zone(conn, row["zone_id"])
        return {"ok": True, "message": f"تم تسجيل وصولك إلى الموقف {row['code']}"}

    return with_db(op)


def list_reservations(user_id):
    def op(conn):
        release_expired(conn)
        rows = conn.execute(
            """
            SELECT r.id, r.status, r.created_at, r.expires_at,
                   r.user_latitude, r.user_longitude,
                   s.code AS spot_code, s.latitude, s.longitude, s.status AS spot_status,
                   z.zone_name
            FROM reservations r
            JOIN spots s ON s.id = r.spot_id
            JOIN zones z ON z.id = s.zone_id
            WHERE r.user_id = ?
            ORDER BY r.id DESC
            """,
            (user_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    return with_db(op)


def list_available_spots():
    def op(conn):
        release_expired(conn)
        rows = conn.execute(
            """
            SELECT s.code, z.zone_name
            FROM spots s JOIN zones z ON z.id = s.zone_id
            WHERE s.status = 'Available'
            ORDER BY s.code
            """
        ).fetchall()
        return [dict(row) for row in rows]

    return with_db(op)


def locate_user(user_id, lat, lng):
    try:
        lat_f = float(lat)
        lng_f = float(lng)
    except (TypeError, ValueError):
        return {"ok": False, "message": "إحداثيات الموقع غير صالحة"}
    if not (-90 <= lat_f <= 90 and -180 <= lng_f <= 180):
        return {"ok": False, "message": "إحداثيات الموقع غير صالحة"}

    def op(conn):
        release_expired(conn)
        zones = conn.execute("SELECT * FROM zones").fetchall()
        nearest_zone = None
        nearest_zone_distance = None
        for zone in zones:
            distance = haversine(
                lat_f, lng_f, zone["center_latitude"], zone["center_longitude"]
            )
            if nearest_zone_distance is None or distance < nearest_zone_distance:
                nearest_zone = zone
                nearest_zone_distance = distance
        spots = conn.execute(
            """
            SELECT s.*, z.zone_name, z.zone_code
            FROM spots s JOIN zones z ON z.id = s.zone_id
            WHERE s.status = 'Available' AND s.latitude IS NOT NULL
            """
        ).fetchall()
        nearest_spot = None
        nearest_spot_distance = None
        for spot in spots:
            distance = haversine(lat_f, lng_f, spot["latitude"], spot["longitude"])
            if nearest_spot_distance is None or distance < nearest_spot_distance:
                nearest_spot = spot
                nearest_spot_distance = distance
        conn.execute(
            """
            INSERT INTO location_logs (
                user_id, latitude, longitude, recorded_at, nearest_zone_id, distance_meters
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                lat_f,
                lng_f,
                now_iso(),
                nearest_zone["id"] if nearest_zone else None,
                round(nearest_zone_distance) if nearest_zone_distance is not None else None,
            ),
        )
        on_campus = inside_campus(lat_f, lng_f)
        nearest_payload = None
        if nearest_spot is not None:
            nearest_payload = {
                "code": nearest_spot["code"],
                "zone_name": nearest_spot["zone_name"],
                "zone_code": nearest_spot["zone_code"],
                "latitude": nearest_spot["latitude"],
                "longitude": nearest_spot["longitude"],
                "distance_m": round(nearest_spot_distance),
            }
            if on_campus:
                message = (
                    f"موقعك داخل الحرم. أقرب موقف متاح هو {nearest_spot['code']} "
                    f"على بعد {format_distance(nearest_spot_distance)}."
                )
            else:
                message = (
                    "موقعك خارج نطاق الحرم. أقرب موقف متاح عند الوصول هو "
                    f"{nearest_spot['code']} في {nearest_spot['zone_name']}، "
                    f"ويبعد {format_distance(nearest_spot_distance)}."
                )
        else:
            message = "لا يوجد موقف متاح حالياً في الحرم."
        return {
            "ok": True,
            "message": message,
            "inside_campus": on_campus,
            "latitude": lat_f,
            "longitude": lng_f,
            "nearest_zone": {
                "zone_code": nearest_zone["zone_code"],
                "zone_name": nearest_zone["zone_name"],
                "distance_m": round(nearest_zone_distance),
            }
            if nearest_zone
            else None,
            "nearest_available": nearest_payload,
        }

    return with_db(op)


def monitor_zone_utilization():
    """P4: الإجمالي والشاغر والمشغول لكل منطقة."""

    def op(conn):
        release_expired(conn)
        rows = conn.execute(
            """
            SELECT z.zone_code, z.zone_name, COUNT(s.id) AS total_spots,
                   SUM(CASE WHEN s.status = 'Available' THEN 1 ELSE 0 END) AS free_spots,
                   SUM(CASE WHEN s.status = 'Occupied' THEN 1 ELSE 0 END) AS occupied_spots,
                   SUM(CASE WHEN s.status = 'Reserved' THEN 1 ELSE 0 END) AS reserved_spots
            FROM zones z
            JOIN spots s ON s.zone_id = z.id
            GROUP BY z.id
            ORDER BY z.zone_code
            """
        ).fetchall()
        summary = []
        for row in rows:
            item = dict(row)
            for key in ("free_spots", "occupied_spots", "reserved_spots"):
                item[key] = int(item[key] or 0)
            summary.append(item)
        return summary

    return with_db(op)


def latest_update():
    def op(conn):
        row = conn.execute("SELECT MAX(last_updated) AS ts FROM spots").fetchone()
        return row["ts"]

    return with_db(op)


def list_events(limit=12):
    def op(conn):
        rows = conn.execute(
            """
            SELECT e.id, s.code AS spot_code, e.event_type, e.event_time, e.source
            FROM occupancy_events e
            JOIN spots s ON s.id = e.spot_id
            ORDER BY e.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    return with_db(op)


def list_navigation(limit=12):
    def op(conn):
        rows = conn.execute(
            """
            SELECT n.id, u.full_name, u.role, s.code AS spot_code,
                   n.requested_at, n.latitude, n.longitude
            FROM navigation_requests n
            JOIN users u ON u.id = n.user_id
            JOIN spots s ON s.id = n.spot_id
            ORDER BY n.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    return with_db(op)


def list_errors(limit=12):
    def op(conn):
        rows = conn.execute(
            """
            SELECT id, message, created_at
            FROM error_logs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    return with_db(op)
