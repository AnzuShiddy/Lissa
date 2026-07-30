"""Unit tests for the prayer-time astronomy — pure arithmetic, no API calls.

Run:  .venv/bin/python -m unittest discover -s tests -t . -v

The times are checked against published timetables for the same day, method
and place, with a few minutes of slack: calculators legitimately differ by a
minute or two over rounding and the elevation they assume. A tighter bound
would just make the suite fail on somebody else's rounding.
"""

import sys
import unittest
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import prayer


def minutes(hm: str) -> int:
    h, m = hm.split(":")
    return int(h) * 60 + int(m)


class TestTimes(unittest.TestCase):
    def check(self, got, expected, slack=4):
        """Every expected time present and within `slack` minutes."""
        for name, want in expected.items():
            self.assertIsNotNone(got[name], f"{name} not computed")
            delta = abs(minutes(got[name]) - minutes(want))
            self.assertLessEqual(
                delta, slack, f"{name}: got {got[name]}, expected ~{want}")

    def times(self, d, lat, lon, tz, method="MWL", asr="standard"):
        return {k: prayer.format_hm(v) for k, v in
                prayer.times(d, lat, lon, tz, method, asr).items()}

    def test_makkah_umm_al_qura(self):
        got = self.times(date(2026, 7, 29), 21.4225, 39.8262, 3, "Makkah")
        self.check(got, {"fajr": "04:29", "sunrise": "05:53", "dhuhr": "12:27",
                         "asr": "15:45", "maghrib": "19:00", "isha": "20:30"})

    def test_cairo_egyptian_method(self):
        got = self.times(date(2026, 7, 29), 30.0444, 31.2357, 2, "Egypt")
        self.check(got, {"sunrise": "05:12", "dhuhr": "12:03", "maghrib": "18:51"})

    def test_jakarta_southern_hemisphere(self):
        got = self.times(date(2026, 7, 29), -6.2088, 106.8456, 7, "Singapore")
        self.check(got, {"sunrise": "06:04", "dhuhr": "11:59", "maghrib": "17:54"})

    def test_isha_as_fixed_interval(self):
        """Umm al-Qura puts Isha 90 minutes after Maghrib, not at an angle."""
        got = prayer.times(date(2026, 7, 29), 21.4225, 39.8262, 3, "Makkah")
        self.assertAlmostEqual(got["isha"] - got["maghrib"], 1.5, places=6)

    def test_hanafi_asr_is_later(self):
        d, args = date(2026, 3, 15), (41.0082, 28.9784, 3)  # Istanbul
        standard = prayer.times(d, *args, "MWL", "standard")["asr"]
        hanafi = prayer.times(d, *args, "MWL", "hanafi")["asr"]
        self.assertGreater(hanafi, standard)
        self.assertLess(hanafi - standard, 2.0)  # later, but not absurdly

    def test_dhuhr_tracks_the_meridian(self):
        """Solar noon shifts with longitude within one zone: a place 15° east
        of another on the same offset sees Dhuhr about an hour earlier."""
        east = prayer.times(date(2026, 7, 29), 20.0, 45.0, 3)["dhuhr"]
        west = prayer.times(date(2026, 7, 29), 20.0, 30.0, 3)["dhuhr"]
        self.assertAlmostEqual(west - east, 1.0, delta=0.05)

    def test_unknown_method_falls_back(self):
        d = date(2026, 7, 29)
        self.assertEqual(prayer.times(d, 21.4, 39.8, 3, "nonsense"),
                         prayer.times(d, 21.4, 39.8, 3, prayer.DEFAULT_METHOD))

    def test_polar_summer_returns_none_not_a_guess(self):
        """Tromsø in June: the sun never dips 18° below the horizon, so Fajr
        and Isha have no astronomical answer. Better none than invented."""
        got = prayer.times(date(2026, 6, 21), 69.6496, 18.9560, 2, "MWL")
        self.assertIsNone(got["fajr"])
        self.assertIsNone(got["isha"])
        self.assertIsNotNone(got["dhuhr"])  # noon always exists


class TestNextPrayer(unittest.TestCase):
    def setUp(self):
        self.day = {"fajr": 5.0, "sunrise": 6.5, "dhuhr": 12.5,
                    "asr": 16.0, "maghrib": 19.0, "isha": 20.5}

    def test_picks_the_soonest_ahead(self):
        self.assertEqual(prayer.next_prayer(self.day, 13.0)[0], "asr")

    def test_wraps_to_tomorrows_fajr_after_isha(self):
        name, gap = prayer.next_prayer(self.day, 22.0)
        self.assertEqual(name, "fajr")
        self.assertAlmostEqual(gap, 7.0)

    def test_skips_times_that_could_not_be_computed(self):
        day = {**self.day, "isha": None}
        self.assertEqual(prayer.next_prayer(day, 19.5)[0], "fajr")


class TestQibla(unittest.TestCase):
    def test_known_bearings(self):
        # published qibla bearings, to the nearest degree
        for lat, lon, want in [(51.5074, -0.1278, 119),   # London
                               (40.7128, -74.0060, 58),   # New York
                               (-6.2088, 106.8456, 295),  # Jakarta
                               (33.6844, 73.0479, 256)]:  # Islamabad
            self.assertAlmostEqual(prayer.qibla(lat, lon), want, delta=1.5)

    def test_from_due_south_of_the_kaaba_it_points_north(self):
        self.assertAlmostEqual(prayer.qibla(0.0, prayer.KAABA_LON), 0.0, delta=0.5)

    def test_compass_points(self):
        self.assertEqual(prayer.compass_point(0), "N")
        self.assertEqual(prayer.compass_point(119), "ESE")
        self.assertEqual(prayer.compass_point(359), "N")


class TestHijri(unittest.TestCase):
    def test_known_dates(self):
        # 1 Jan 2000 was 24 Ramadan 1420 in the tabular calendar
        self.assertEqual(prayer.hijri(date(2000, 1, 1)), (1420, 9, 24))
        self.assertEqual(prayer.hijri_text(date(2000, 1, 1)), "24 Ramadan 1420 AH")

    def test_months_stay_in_range(self):
        for year in (2024, 2026, 2030):
            for month in range(1, 13):
                y, m, d = prayer.hijri(date(year, month, 15))
                self.assertTrue(1 <= m <= 12)
                self.assertTrue(1 <= d <= 30)


class TestSummary(unittest.TestCase):
    def setUp(self):
        self.data = prayer.summary(
            -6.7924, 39.2083, 3, "MWL", "standard",
            now=datetime(2026, 7, 29, 14, 30))  # Dar es Salaam, mid-afternoon

    def test_shape(self):
        self.assertEqual(self.data["next"], "asr")
        self.assertEqual(self.data["hijri"], prayer.hijri_text(date(2026, 7, 29)))
        self.assertTrue(self.data["approximate"])
        self.assertEqual(set(self.data["times"]), set(prayer.PRAYERS))

    def test_context_mentions_the_next_prayer_and_the_caveat(self):
        text = prayer.context(self.data, datetime(2026, 7, 29, 14, 30))
        self.assertIn("Asr", text)
        self.assertIn("approximate", text)
        self.assertIn("qibla", text.lower())

    def test_context_is_empty_without_a_location(self):
        self.assertEqual(prayer.context(None), "")


if __name__ == "__main__":
    unittest.main()
