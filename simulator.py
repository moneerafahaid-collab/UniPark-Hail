"""محاكي حساسات المواقف.

هذا الملف منفصل عن الخريطة وعن التوجيه حتى يمكن استبداله لاحقاً
بتغذية حساسات حقيقية دون تغيير قواعد الحجز والملاحة.
"""

import threading

import database


class SensorFeed:
    def __init__(self, interval=5):
        self.interval = interval
        self._stop = threading.Event()
        self._thread = None
        self.last_event_at = None
        self.last_result = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return {"ok": True, "message": "المحاكي يعمل بالفعل ويسجّل الحركة"}
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="unipark-sensor-feed", daemon=True
        )
        self._thread.start()
        return {"ok": True, "message": "بدأ المحاكي بتسجيل الوصول والمغادرة"}

    def stop(self):
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=3)
        return {
            "ok": True,
            "message": "توقف المحاكي. تبقى آخر حالة مسجّلة لكل موقف",
        }

    def tick(self):
        result = database.simulate_once()
        self.last_event_at = database.now_iso()
        self.last_result = result
        return result

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:
                database.log_error(f"خطأ في محاكي التسجيل: {exc}")
            if self._stop.wait(self.interval):
                break

    def status(self):
        return {
            "running": bool(self._thread and self._thread.is_alive()),
            "last_event_at": self.last_event_at,
            "interval_seconds": self.interval,
        }

    def inject_unknown(self):
        """يسجّل خطأ رمز موقف غير معروف، كما يطلب متطلب الصيانة."""
        return database.update_spot_status("Z99", "arrival", "test")
