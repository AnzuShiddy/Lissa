"""Unit tests for the anonymous analytics — pure logic, no API calls.

Run:  .venv/bin/python -m unittest discover -s tests -t . -v
"""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import analytics


NOW = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)


def line(t, e, s, **fields):
    return json.dumps({"t": t, "e": e, "s": s, **fields})


class TestAnon(unittest.TestCase):
    def test_hides_the_cookie(self):
        """The raw sid must never be recoverable from a log line."""
        out = analytics.anon("super-secret-session-token")
        self.assertNotIn("super-secret", out)
        self.assertEqual(len(out), 10)

    def test_stable_within_a_session(self):
        self.assertEqual(analytics.anon("abc"), analytics.anon("abc"))
        self.assertNotEqual(analytics.anon("abc"), analytics.anon("abd"))

    def test_missing_sid(self):
        self.assertEqual(analytics.anon(None), "-")
        self.assertEqual(analytics.anon(""), "-")


class TestRecord(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "events.jsonl"
        self.orig = analytics.FILE
        analytics.FILE = self.path

    def tearDown(self):
        analytics.FILE = self.orig
        self.dir.cleanup()

    def test_writes_one_json_line(self):
        analytics.record("visit", "sid123", lang="en", chats=4)
        lines = self.path.read_text().splitlines()
        self.assertEqual(len(lines), 1)
        e = json.loads(lines[0])
        self.assertEqual(e["e"], "visit")
        self.assertEqual(e["chats"], 4)
        self.assertEqual(e["s"], analytics.anon("sid123"))
        self.assertNotIn("sid123", lines[0])
        # timestamp parses and is UTC
        self.assertIsNotNone(datetime.fromisoformat(e["t"]).tzinfo)

    def test_appends(self):
        analytics.record("visit", "a")
        analytics.record("message", "a", len=12)
        self.assertEqual(len(self.path.read_text().splitlines()), 2)

    def test_never_raises(self):
        """A broken file location must not take the request down."""
        analytics.FILE = Path(self.dir.name)  # a directory: open() fails
        analytics.record("visit", "a")  # must not raise


class TestStats(unittest.TestCase):
    def write(self, *lines):
        path = Path(self.dir.name) / "events.jsonl"
        path.write_text("\n".join(lines) + "\n")
        return path

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.dir.cleanup()

    def test_counts_unique_visitors_and_returning(self):
        path = self.write(
            line("2026-07-23T10:00:00+00:00", "visit", "aa", chats=0),
            line("2026-07-23T10:05:00+00:00", "visit", "aa", chats=0),  # refresh
            line("2026-07-23T11:00:00+00:00", "visit", "bb", chats=7),
        )
        day = analytics.stats(path=path, now=NOW)["days"][0]
        self.assertEqual(day["visitors"], 2)
        self.assertEqual(day["returning"], 1)

    def test_engaged_needs_a_real_conversation(self):
        msgs_aa = [line(f"2026-07-23T10:0{i}:00+00:00", "message", "aa", len=9)
                   for i in range(analytics.ENGAGED_MIN)]
        path = self.write(
            *msgs_aa,
            line("2026-07-23T10:00:00+00:00", "message", "bb", len=9),
        )
        day = analytics.stats(path=path, now=NOW)["days"][0]
        self.assertEqual(day["messages"], analytics.ENGAGED_MIN + 1)
        self.assertEqual(day["engaged"], 1)  # bb's single message doesn't count

    def test_limited_messages_counted_separately(self):
        path = self.write(
            line("2026-07-23T10:00:00+00:00", "message", "aa", len=9, limited="rate"),
            line("2026-07-23T10:01:00+00:00", "message", "aa", len=9, limited=None),
        )
        day = analytics.stats(path=path, now=NOW)["days"][0]
        self.assertEqual(day["limited"], 1)
        self.assertEqual(day["messages"], 1)

    def test_minutes_span_first_to_last_event(self):
        path = self.write(
            line("2026-07-23T10:00:00+00:00", "visit", "aa"),
            line("2026-07-23T10:12:00+00:00", "message", "aa", len=9),
        )
        day = analytics.stats(path=path, now=NOW)["days"][0]
        self.assertEqual(day["minutes"], 12.0)

    def test_days_sorted_recent_first_with_totals(self):
        path = self.write(
            line("2026-07-22T10:00:00+00:00", "visit", "aa", chats=0),
            line("2026-07-23T10:00:00+00:00", "visit", "bb", chats=0),
        )
        out = analytics.stats(path=path, now=NOW)
        self.assertEqual([d["day"] for d in out["days"]], ["2026-07-23", "2026-07-22"])
        self.assertEqual(out["totals"]["visitors"], 2)

    def test_old_days_cut_off(self):
        path = self.write(
            line("2026-07-01T10:00:00+00:00", "visit", "aa", chats=0),
            line("2026-07-23T10:00:00+00:00", "visit", "bb", chats=0),
        )
        out = analytics.stats(days=14, path=path, now=NOW)
        self.assertEqual(len(out["days"]), 1)
        self.assertEqual(out["days"][0]["day"], "2026-07-23")

    def test_survives_junk_lines(self):
        """A torn write mid-crash must not hide the readable events."""
        path = self.write(
            "not json at all",
            '{"t": "2026-07-23T10:00:00+00:00"',  # torn
            line("2026-07-23T10:00:00+00:00", "visit", "aa", chats=0),
        )
        out = analytics.stats(path=path, now=NOW)
        self.assertEqual(out["totals"]["visitors"], 1)

    def test_missing_file_is_empty(self):
        out = analytics.stats(path=Path(self.dir.name) / "nope.jsonl", now=NOW)
        self.assertEqual(out["days"], [])
        self.assertEqual(out["totals"]["messages"], 0)

    def test_voice_counted(self):
        path = self.write(
            line("2026-07-23T10:00:00+00:00", "say", "aa", edge=False),
            line("2026-07-23T10:01:00+00:00", "say", "aa", edge=True),
        )
        self.assertEqual(analytics.stats(path=path, now=NOW)["days"][0]["voice"], 2)


if __name__ == "__main__":
    unittest.main()
