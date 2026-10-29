"""Host-side regression checks for Travel Globe's time, sun and globe renderer."""

import ast
import builtins
import calendar
import datetime as dt
import importlib.util
import math
from array import array
from pathlib import Path
import sys
import time
import types
import unittest

APP = Path(__file__).resolve().parents[1] / "badge/apps/travel_globe"
ZONES = {
    "USA": "America/New_York", "CRI": "America/Costa_Rica", "PRI": "America/Puerto_Rico",
    "SLV": "America/El_Salvador", "HND": "America/Tegucigalpa", "COL": "America/Bogota",
    "PAN": "America/Panama", "ESP": "Europe/Madrid", "ITA": "Europe/Rome", "DEU": "Europe/Berlin",
}


def load(name):
    spec = importlib.util.spec_from_file_location("travel_globe_" + name, APP / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_globe():
    """globe.py with viper run as plain Python, the way the simulator runs it."""
    fake = types.ModuleType("micropython")
    fake.viper = fake.native = lambda function: function
    fake.const = lambda value: value
    saved = sys.modules.get("micropython")
    sys.modules["micropython"] = fake
    builtins.micropython = fake
    for name in ("ptr8", "ptr16", "ptr32"):
        setattr(builtins, name, lambda buffer: buffer)
    try:
        return load("globe")
    finally:
        if saved is None:
            sys.modules.pop("micropython", None)
        else:
            sys.modules["micropython"] = saved


def visited():
    source = (APP / "__init__.py").read_text(encoding="utf-8")
    start = source.index("VISITED = (") + len("VISITED = ")
    return ast.literal_eval(source[start:source.index("WORLD_COUNTRIES")].strip())


def noaa_sun(moment):
    """Subsolar point from the NOAA solar calculator, independent of sky.py."""
    jd = moment.timestamp() / 86400 + 2440587.5
    t = (jd - 2451545) / 36525
    l0 = (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360
    m = math.radians(357.52911 + t * (35999.05029 - 0.0001537 * t))
    e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    c = (math.sin(m) * (1.914602 - t * (0.004817 + 0.000014 * t))
         + math.sin(2 * m) * (0.019993 - 0.000101 * t) + math.sin(3 * m) * 0.000289)
    omega = math.radians(125.04 - 1934.136 * t)
    lam = math.radians(l0 + c - 0.00569 - 0.00478 * math.sin(omega))
    eps = math.radians(23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60) / 60
                       + 0.00256 * math.cos(omega))
    dec = math.degrees(math.asin(math.sin(eps) * math.sin(lam)))
    y = math.tan(eps / 2) ** 2
    l0r = math.radians(l0)
    eot = 4 * math.degrees(y * math.sin(2 * l0r) - 2 * e * math.sin(m) + 4 * e * y * math.sin(m) * math.cos(2 * l0r)
                           - 0.5 * y * y * math.sin(4 * l0r) - 1.25 * e * e * math.sin(2 * m))
    minutes = moment.hour * 60 + moment.minute + moment.second / 60
    return dec, (-(minutes + eot - 720) / 4 + 540) % 360 - 180


def since_2000(moment):
    return (moment.date() - dt.date(2000, 1, 1)).days, moment.hour * 3600 + moment.minute * 60 + moment.second


class SkyTests(unittest.TestCase):
    def setUp(self):
        self.sky = load("sky")

    def test_calendar_matches_datetime(self):
        day = dt.date(1999, 1, 1)
        while day.year < 2102:
            n = self.sky.days_from_civil(day.year, day.month, day.day)
            self.assertEqual(n, (day - dt.date(2000, 1, 1)).days)
            self.assertEqual(self.sky.civil_from_days(n), (day.year, day.month, day.day))
            self.assertEqual(self.sky.weekday(n), day.weekday())
            day += dt.timedelta(days=13)

    def test_local_time_matches_time_zones(self):
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo("Europe/Madrid")
        except Exception:
            self.skipTest("no time zone database")
        for code, _, hours, rule, _, _ in visited():
            zone = ZoneInfo(ZONES[code])
            moment = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)
            while moment.year < 2031:
                day, second = since_2000(moment)
                h, m, _ = self.sky.local_time(day, second, hours, rule)
                local = moment.astimezone(zone)
                self.assertEqual((h, m), (local.hour, local.minute), (code, moment))
                # every 50 minutes, so each DST change is crossed at different minutes
                moment += dt.timedelta(minutes=50)

    def test_sun_position_matches_noaa(self):
        moment = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
        for _ in range(1500):
            lat, lon = self.sky.sun_position(*since_2000(moment))
            ref_lat, ref_lon = noaa_sun(moment)
            self.assertLess(abs(lat - ref_lat), 0.05)
            self.assertLess(abs((lon - ref_lon + 540) % 360 - 180), 0.05)
            moment += dt.timedelta(hours=61, minutes=17)

    def test_clock_applies_ntp_before_checking_the_year(self):
        now = [calendar.timegm((2021, 1, 1, 3, 0, 0))]
        self.sky.time = types.SimpleNamespace(gmtime=lambda: time.gmtime(now[0]))
        clock = self.sky.Clock()
        self.assertFalse(clock.valid)
        clock.correction = calendar.timegm((2026, 10, 29, 20, 15, 0)) - now[0]
        clock.read()
        self.assertTrue(clock.valid)
        self.assertEqual(self.sky.civil_from_days(clock.day), (2026, 10, 29))
        self.assertEqual(clock.hours_minutes(), (20, 15))

    def test_time_lapse_runs_ahead_and_back(self):
        now = [calendar.timegm((2026, 10, 29, 22, 0, 0))]
        self.sky.time = types.SimpleNamespace(gmtime=lambda: time.gmtime(now[0]))
        clock = self.sky.Clock()
        clock.speed = 14400
        for _ in range(600):
            clock.advance(1000 / 60)
        self.assertEqual(self.sky.civil_from_days(clock.day), (2026, 10, 31))
        clock.live()
        self.assertEqual((self.sky.civil_from_days(clock.day), clock.hours_minutes()), ((2026, 10, 29), (22, 0)))


class GlobeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.globe = load_globe()
        cls.tab = cls.globe.build_tables()

    def test_longitude_table_matches_atan2(self):
        g, tab = self.globe, self.tab
        for qy in range(258):
            for qx in range(258):
                x, y = qx * 128 - 16448, qy * 128 - 16448
                want = (math.atan2(y, x) + math.pi) / (2 * math.pi) * g.TEX_W
                got = tab[g._O_LON + qy * 258 + qx]
                self.assertLess(abs((got - want + 512) % 1024 - 512), 1.01, (qx, qy))

    def render(self, lon, lat, radius, cx, cy, width=96, height=72):
        """Each pixel's sampled texel as row * 1024 + col, or -1 where transparent."""
        g = self.globe
        lam, phi = math.radians(lon), math.radians(lat)
        out = (math.cos(phi) * math.cos(lam), math.cos(phi) * math.sin(lam), math.sin(phi))
        east = (-math.sin(lam), math.cos(lam), 0.0)
        north = (-math.sin(phi) * math.cos(lam), -math.sin(phi) * math.sin(lam), math.cos(phi))
        prm = array("i", bytes(4 * (g._PALETTE + 256 * g.LEVELS)))
        for index in range(256 * g.LEVELS):
            prm[g._PALETTE + index] = index >> 5          # the palette hands back the texel value
        rows = [int(c * g.ONE + (0.5 if c >= 0 else -0.5)) for v in (east, north, out, (1.0, 0, 0)) for c in v]
        irad = int(radius)
        inv = (1 << 20) // irad
        x0, x1 = max(0, cx - irad - 1), min(width, cx + irad + 2)
        y0, y1 = max(0, cy - irad - 1), min(height, cy + irad + 2)
        prm[0:5] = array("i", [width, height, cx, cy, irad])
        prm[5:17] = array("i", rows)
        prm[17:26] = array("i", [(4096 << 16) // (irad * irad), y0, y1, x0, x1, inv,
                                 (rows[0] * inv) >> 6, (rows[1] * inv) >> 6, (rows[2] * inv) >> 6])
        # a texture whose value says where it was read from: 4 x 4 texel blocks
        tex = bytearray(((r // 4) * 37 + c // 4) % 251 + 1 for r in range(512) for c in range(1024))
        out_buf = array("i", bytes(4 * width * height))
        self.globe._render(out_buf, tex, self.tab, prm)
        return out_buf, tex, (east, north, out), (x0, x1, y0, y1)

    def test_render_samples_the_right_place(self):
        cases = [(-84.0, 10.0, 30, 48, 36), (179.9, 45.0, 34, 40, 30), (0.0, -60.0, 28, 70, 40), (-100.0, 39.0, 50, 48, 36)]
        for lon, lat, radius, cx, cy in cases:
            out_buf, tex, (east, north, out), (x0, x1, y0, y1) = self.render(lon, lat, radius, cx, cy)
            checked = 0
            for y in range(y0, y1):
                for x in range(x0, x1):
                    vx, vy = (x - cx) / radius, -(y - cy) / radius
                    r2 = vx * vx + vy * vy
                    value = out_buf[y * 96 + x]
                    if r2 > 1.08:
                        self.assertEqual(value, 0, (lon, lat, x, y))
                        continue
                    if r2 > 0.9:
                        continue                      # the limb may round either way
                    self.assertNotEqual(value, 0)
                    vz = math.sqrt(1 - r2)
                    w = [east[i] * vx + north[i] * vy + out[i] * vz for i in range(3)]
                    lat_here = math.degrees(math.asin(max(-1, min(1, w[2]))))
                    if abs(lat_here) > 86:
                        continue                      # at the pole every longitude is right
                    row = (90 - lat_here) / 180 * 512
                    col = (math.degrees(math.atan2(w[1], w[0])) + 180) / 360 * 1024
                    # The value must come from a 4x4 block next to the true texel.
                    # Columns narrow towards the poles, so the same error on the
                    # ground spans more of them there.
                    reach = 3 + int(2 / max(0.05, math.cos(math.radians(lat_here))))
                    near = {tex[(int(row + dr) % 512) * 1024 + int(col + dc) % 1024]
                            for dr in (-2, 0, 2) for dc in range(-reach, reach + 1)}
                    self.assertIn(value, near, (lon, lat, x, y))
                    checked += 1
            self.assertGreater(checked, 1000)


if __name__ == "__main__":
    unittest.main()
