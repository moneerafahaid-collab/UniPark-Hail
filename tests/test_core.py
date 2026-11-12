import os
import sqlite3
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
fd, DB_PATH = tempfile.mkstemp(suffix=".db")
os.close(fd)
os.environ["UNIPARK_DB"] = DB_PATH
os.environ["UNIPARK_SECRET"] = "test-secret"

import database
from simulator import SensorFeed
import app as unipark


def spot_status(code):
    layout = database.display_layout(1)
    for zone in layout["zones"]:
        for spot in zone["spots"]:
            if spot["code"] == code:
                return spot["status"], zone["available_spots"]
    return None, None


class UniParkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        unipark.app.config["TESTING"] = True
        cls.client = unipark.app.test_client()

    def test_showcase_and_occupied_seed(self):
        self.assertEqual(spot_status("A15")[0], "Available")
        self.assertEqual(spot_status("A01")[0], "Occupied")

    def test_password_is_salted_hash(self):
        user = database.authenticate("student@uoh.edu.sa", database.DEMO_PASSWORD)
        self.assertIsNotNone(user)
        self.assertIsNone(database.authenticate("student@uoh.edu.sa", "wrong-pass"))
        conn = sqlite3.connect(DB_PATH)
        stored = conn.execute(
            "SELECT password_hash FROM users WHERE email = ?",
            ("student@uoh.edu.sa",),
        ).fetchone()[0]
        conn.close()
        self.assertNotIn(database.DEMO_PASSWORD, stored)
        self.assertIn(":", stored)

    def test_arrival_and_departure_update_count(self):
        before = spot_status("A01")[1]
        result = database.update_spot_status("A01", "departure", "test")
        self.assertTrue(result["ok"])
        status, after = spot_status("A01")
        self.assertEqual(status, "Available")
        self.assertEqual(after, before + 1)
        database.update_spot_status("A01", "arrival", "test")
        self.assertEqual(spot_status("A01")[0], "Occupied")

    def test_unknown_code_is_logged(self):
        result = database.update_spot_status("Z99", "arrival", "test")
        self.assertFalse(result["ok"])
        self.assertTrue(any("Z99" in row["message"] for row in database.list_errors(10)))

    def test_reservation_blocks_others_and_allows_owner_navigation(self):
        owner = database.authenticate("student@uoh.edu.sa", database.DEMO_PASSWORD)
        other = database.register_user("مستخدم آخر", "other@uoh.edu.sa", "secret12", "student", None)
        booked = database.reserve_spot(owner["id"], "B15", 30)
        self.assertTrue(booked["ok"])
        self.assertEqual(spot_status("B15")[0], "Reserved")
        self.assertFalse(database.reserve_spot(other["user_id"], "B15", 30)["ok"])
        second = database.reserve_spot(owner["id"], "A15", 30)
        self.assertFalse(second["ok"])
        denied = database.prepare_navigation(other["user_id"], "B15")
        self.assertFalse(denied["ok"])
        allowed = database.prepare_navigation(owner["id"], "B15")
        self.assertTrue(allowed["ok"])
        self.assertIn("google.com/maps", allowed["maps_url"])
        occupied = database.prepare_navigation(owner["id"], "A01")
        self.assertFalse(occupied["ok"])

    def test_expired_reservation_is_released(self):
        owner = database.authenticate("faculty@uoh.edu.sa", database.DEMO_PASSWORD)
        booked = database.reserve_spot(owner["id"], "D08", 30)
        self.assertTrue(booked["ok"])
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "UPDATE reservations SET expires_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00+00:00", booked["reservation_id"]),
        )
        conn.commit()
        conn.close()
        layout = database.display_layout(owner["id"])
        self.assertIsNone(layout["my_reservation"])
        self.assertEqual(spot_status("D08")[0], "Available")

    def test_location_inside_campus(self):
        owner = database.authenticate("student@uoh.edu.sa", database.DEMO_PASSWORD)
        point = database.CAMPUS["demo_point"]
        result = database.locate_user(owner["id"], point[0], point[1])
        self.assertTrue(result["ok"])
        self.assertTrue(result["inside_campus"])
        self.assertIsNotNone(result["nearest_available"])

    def test_simulator_records_one_event(self):
        feed = SensorFeed(interval=60)
        before = len(database.list_events(5000))
        result = feed.tick()
        self.assertTrue(result["ok"])
        self.assertEqual(len(database.list_events(5000)), before + 1)
        feed.start()
        self.assertTrue(feed.status()["running"])
        feed.stop()
        self.assertFalse(feed.status()["running"])

    def test_security_summary_is_hidden_from_students(self):
        self.login("student@uoh.edu.sa")
        blocked = self.client.get("/admin", follow_redirects=False)
        self.assertEqual(blocked.status_code, 302)
        denied = self.client.post(
            "/api/simulator/start",
            json={"ok": True},
            headers={"X-CSRF-Token": self.token()},
        )
        self.assertEqual(denied.status_code, 403)
        self.client.post("/logout", data={"csrf_token": self.token()})
        self.login("security@uoh.edu.sa")
        page = self.client.get("/admin")
        self.assertEqual(page.status_code, 200)
        overview = self.client.get("/api/admin/overview")
        self.assertEqual(overview.status_code, 200)
        self.assertIn("zones", overview.get_json())

    def test_registration_rejects_security_role(self):
        result = database.register_user(
            "أمن جديد", "guard@uoh.edu.sa", "secret12", "security", None
        )
        self.assertFalse(result["ok"])

    def token(self):
        with self.client.session_transaction() as current:
            return current["csrf"]

    def login(self, email):
        self.client.get("/login")
        return self.client.post(
            "/login",
            data={
                "email": email,
                "password": database.DEMO_PASSWORD,
                "csrf_token": self.token(),
            },
        )


if __name__ == "__main__":
    unittest.main()
