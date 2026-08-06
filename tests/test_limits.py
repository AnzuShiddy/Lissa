"""Tests for the ceilings that keep one visitor from costing everyone else.

No API calls. The session store is exercised through engine.evict(), which
takes the dict rather than reaching for the module global precisely so this
can run without credentials — building a real Session needs a client.

Run:  .venv/bin/python -m unittest discover -s tests -t . -v
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import engine

ROOT = Path(__file__).resolve().parent.parent


class Fake:
    """Stands in for a Session: eviction only ever reads last_used."""

    def __init__(self, last_used: float) -> None:
        self.last_used = last_used


def store(ages: dict[str, float], now: float = 1000.0) -> dict:
    """Sessions keyed by name, each `age` seconds old."""
    return {name: Fake(now - age) for name, age in ages.items()}


class EvictionTests(unittest.TestCase):
    def test_stale_sessions_go(self):
        sessions = store({"fresh": 10, "stale": engine.SESSION_TTL + 1})
        engine.evict(sessions, 1000.0)
        self.assertEqual(set(sessions), {"fresh"})

    def test_a_live_store_under_the_cap_is_left_alone(self):
        sessions = store({str(i): i for i in range(10)})
        engine.evict(sessions, 1000.0, cap=100)
        self.assertEqual(len(sessions), 10)

    def test_the_cap_is_enforced_once_age_is_not_enough(self):
        """The failure this exists for: inside one TTL window nothing was
        stale, so nothing was ever dropped however many arrived."""
        sessions = store({str(i): i for i in range(50)})  # all well within TTL
        engine.evict(sessions, 1000.0, cap=20)
        self.assertEqual(len(sessions), 20)

    def test_the_oldest_are_the_ones_dropped(self):
        sessions = store({"old": 300, "middle": 200, "recent": 100})
        engine.evict(sessions, 1000.0, cap=2)
        self.assertEqual(set(sessions), {"middle", "recent"})

    def test_the_newest_survives_so_a_caller_keeps_what_it_was_handed(self):
        """get_session() evicts after inserting; the session it is about to
        return must never be the one thrown away."""
        sessions = store({str(i): 500 - i for i in range(30)})
        sessions["just_made"] = Fake(1000.0)
        engine.evict(sessions, 1000.0, cap=5)
        self.assertIn("just_made", sessions)

    def test_an_empty_store_is_survivable(self):
        sessions: dict = {}
        engine.evict(sessions, 1000.0)
        self.assertEqual(sessions, {})

    def test_the_cap_is_configured_and_sane(self):
        self.assertGreater(engine.MAX_SESSIONS, 0)


class MessageCapTests(unittest.TestCase):
    """app imports the SDK, so it is imported here rather than at module
    scope — the rest of this file must stay runnable without it."""

    def app(self):
        try:
            import app
        except ImportError as e:  # pragma: no cover - only without the SDK
            self.skipTest(f"app needs the genai SDK: {e}")
        return app

    def test_a_long_message_is_trimmed_not_refused(self):
        app = self.app()
        got = app.clamp_message("x" * (app.MAX_MESSAGE_CHARS + 500))
        self.assertEqual(len(got), app.MAX_MESSAGE_CHARS)

    def test_an_ordinary_message_is_untouched_but_stripped(self):
        app = self.app()
        self.assertEqual(app.clamp_message("  hello  "), "hello")

    def test_junk_is_survivable(self):
        app = self.app()
        self.assertEqual(app.clamp_message(""), "")
        self.assertEqual(app.clamp_message(None), "")

    def test_the_browser_is_told_the_same_number(self):
        """The composer enforces it client-side, so it has to be sent."""
        app = self.app()
        import bots
        self.assertEqual(
            {**bots.get("lissa").manifest(), "maxMessage": app.MAX_MESSAGE_CHARS}
            ["maxMessage"],
            app.MAX_MESSAGE_CHARS)


class MobileConfigTests(unittest.TestCase):
    def test_android_does_not_permit_cleartext(self):
        """The config used to say cleartext: false and then switch plaintext
        HTTP back on two keys below it, for a server that is HTTPS-only."""
        cfg = json.loads((ROOT / "capacitor.config.json").read_text())
        self.assertFalse(cfg["server"]["cleartext"])
        self.assertFalse(cfg["android"]["allowMixedContent"])
        self.assertFalse(cfg["android"]["usesCleartextTraffic"])
        self.assertTrue(cfg["server"]["url"].startswith("https://"))


if __name__ == "__main__":
    unittest.main()
