"""Recovering analytics history from a log export.

The point of the tool is that a deploy no longer costs you your history, so
the cases that matter are: pull events out of noisy log text, merge without
double-counting, and survive a truncated export.
"""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from tools import ingest_analytics as ingest

# What a Render export actually looks like: the host's timestamp and stream
# in front of the line record() printed.
EXPORT = """\
2026-07-30T09:22:31.100000000Z app INFO:     Started server process [42]
2026-07-30T09:22:33.200000000Z app analytics {"t": "2026-07-30T09:22:33+00:00", "e": "visit", "s": "aaa", "bot": "lissa", "chats": 0}
2026-07-30T09:22:40.300000000Z app analytics {"t": "2026-07-30T09:22:40+00:00", "e": "message", "s": "aaa", "len": 12}
2026-07-30T09:22:41.400000000Z app INFO:     127.0.0.1 - "POST /api/lissa/chat HTTP/1.1" 200 OK
"""


class ExtractTests(unittest.TestCase):
    def test_pulls_events_out_of_log_noise(self):
        events = ingest.events_in(EXPORT)
        self.assertEqual([e["e"] for e in events], ["visit", "message"])
        self.assertEqual(events[0]["s"], "aaa")
        self.assertEqual(events[1]["len"], 12)

    def test_reads_a_plain_event_log_too(self):
        """So two analytics.jsonl files can be merged, not just exports."""
        line = json.dumps({"t": "2026-07-30T10:00:00+00:00", "e": "say", "s": "bbb"})
        self.assertEqual(len(ingest.events_in(line)), 1)

    def test_ignores_a_truncated_line(self):
        """Exports get cut at arbitrary points; the rest must still land."""
        torn = EXPORT + '2026-07-30T09:23:00Z app analytics {"t": "2026-07-3'
        self.assertEqual(len(ingest.events_in(torn)), 2)

    def test_ignores_json_that_is_not_an_event(self):
        self.assertEqual(ingest.events_in('{"hello": "world"}'), [])


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.a = {"t": "2026-07-30T09:00:00+00:00", "e": "visit", "s": "aaa"}
        self.b = {"t": "2026-07-30T10:00:00+00:00", "e": "message", "s": "aaa"}

    def test_adds_only_what_is_new(self):
        merged, added = ingest.merge([self.a], [self.a, self.b])
        self.assertEqual(added, 1)
        self.assertEqual(len(merged), 2)

    def test_replaying_the_same_export_changes_nothing(self):
        once, _ = ingest.merge([], [self.a, self.b])
        twice, added = ingest.merge(once, [self.a, self.b])
        self.assertEqual(added, 0)
        self.assertEqual(twice, once)

    def test_key_order_does_not_defeat_deduplication(self):
        reordered = {"s": "aaa", "e": "visit", "t": "2026-07-30T09:00:00+00:00"}
        _, added = ingest.merge([self.a], [reordered])
        self.assertEqual(added, 0)

    def test_output_is_sorted_by_time(self):
        merged, _ = ingest.merge([], [self.b, self.a])
        self.assertEqual([e["t"] for e in merged], [self.a["t"], self.b["t"]])


class RoundTripTests(unittest.TestCase):
    def test_ingesting_an_export_makes_the_history_countable_again(self):
        """The whole point: after a wipe, stats() sees the recovered days."""
        from core import analytics

        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "analytics.jsonl"
            export = Path(d) / "render.log"
            export.write_text(EXPORT, encoding="utf-8")

            # the file was wiped by a deploy: nothing to aggregate
            self.assertEqual(analytics.stats(path=log)["totals"]["visitors"], 0)

            with contextlib.redirect_stdout(io.StringIO()):
                ingest.main([str(export), "--into", str(log)])

            from datetime import datetime, timezone
            now = datetime(2026, 7, 30, 23, 0, tzinfo=timezone.utc)
            totals = analytics.stats(path=log, now=now)["totals"]
            self.assertEqual(totals["visitors"], 1)
            self.assertEqual(totals["messages"], 1)

            # and a second pull of an overlapping export doesn't double it
            with contextlib.redirect_stdout(io.StringIO()):
                ingest.main([str(export), "--into", str(log)])
            totals = analytics.stats(path=log, now=now)["totals"]
            self.assertEqual(totals["messages"], 1)

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "analytics.jsonl"
            export = Path(d) / "render.log"
            export.write_text(EXPORT, encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                ingest.main([str(export), "--into", str(log), "--dry-run"])
            self.assertFalse(log.exists())


if __name__ == "__main__":
    unittest.main()
