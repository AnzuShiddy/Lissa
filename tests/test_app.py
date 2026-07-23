"""Unit tests for the web server's pure helpers — rate limiting, image
decoding, and hour validation. No network, no running server: take_quota
works on a lightweight fake session and the module-level daily counter.

Run:  .venv/bin/python -m unittest discover -s tests -t . -v
"""

import base64
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app


def fake_session(tokens=None):
    """The subset of UserSession that take_quota touches."""
    return SimpleNamespace(
        tokens=app.RATE_PER_MIN if tokens is None else tokens,
        tokens_at=time.time(),
    )


class TestTakeQuota(unittest.TestCase):
    def setUp(self):
        # take_quota mutates a module-global daily counter — reset it so
        # tests don't leak into each other.
        with app._daily_lock:
            app._daily["day"] = time.strftime("%Y-%m-%d")
            app._daily["count"] = 0

    def test_allows_and_spends_a_token(self):
        sess = fake_session()
        self.assertIsNone(app.take_quota(sess))
        self.assertAlmostEqual(sess.tokens, app.RATE_PER_MIN - 1, places=3)
        self.assertEqual(app._daily["count"], 1)

    def test_per_minute_limit_returns_wait(self):
        sess = fake_session(tokens=0.0)
        result = app.take_quota(sess, "en")
        self.assertIsNotNone(result)
        msg, wait = result
        self.assertGreater(wait, 0)
        self.assertIn("catch my breath", msg)
        # A blocked call must not have spent the daily budget.
        self.assertEqual(app._daily["count"], 0)

    def test_unknown_language_falls_back_to_english(self):
        sess = fake_session(tokens=0.0)
        msg, wait = app.take_quota(sess, "xx")
        self.assertEqual(msg, app.RATE_LIMIT_MSG["en"].format(wait=wait))

    def test_localized_limit_message(self):
        sess = fake_session(tokens=0.0)
        msg, _ = app.take_quota(sess, "fr")
        self.assertIn("reprendre mon souffle", msg)

    def test_daily_cap_blocks_with_no_countdown(self):
        with app._daily_lock:
            app._daily["count"] = app.DAILY_CALLS
        result = app.take_quota(fake_session(), "en")
        self.assertIsNotNone(result)
        msg, wait = result
        self.assertEqual(wait, 0)
        self.assertEqual(msg, app.DAILY_CAP_MSG["en"])

    def test_daily_rollover_resets_count(self):
        with app._daily_lock:
            app._daily["day"] = "2000-01-01"
            app._daily["count"] = app.DAILY_CALLS
        # A new day resets the counter, so this call is allowed again.
        self.assertIsNone(app.take_quota(fake_session()))
        self.assertEqual(app._daily["count"], 1)

    def test_background_call_skips_token_bucket(self):
        # per_minute=False (memory distillation) must never be throttled by
        # the per-visitor bucket, only the daily cap.
        sess = fake_session(tokens=0.0)
        self.assertIsNone(app.take_quota(sess, per_minute=False))
        self.assertEqual(sess.tokens, 0.0)  # bucket untouched
        self.assertEqual(app._daily["count"], 1)


class TestDecodeImage(unittest.TestCase):
    @staticmethod
    def data_url(raw: bytes, mime: str = "image/png") -> str:
        return f"data:{mime};base64," + base64.b64encode(raw).decode()

    def test_valid_png(self):
        result = app.decode_image(self.data_url(b"\x89PNG\r\n\x1a\n fake"))
        self.assertIsNotNone(result)
        raw, mime = result
        self.assertEqual(mime, "image/png")
        self.assertTrue(raw.startswith(b"\x89PNG"))

    def test_non_image_mime_rejected(self):
        self.assertIsNone(app.decode_image(self.data_url(b"hello", "text/plain")))

    def test_empty_payload_rejected(self):
        self.assertIsNone(app.decode_image("data:image/png;base64,"))

    def test_garbage_rejected(self):
        self.assertIsNone(app.decode_image("not a data url"))
        self.assertIsNone(app.decode_image("data:image/png;base64,@@@not-base64@@@"))

    def test_oversize_rejected(self):
        original = app.MAX_IMAGE_BYTES
        app.MAX_IMAGE_BYTES = 8
        try:
            self.assertIsNone(app.decode_image(self.data_url(b"x" * 32)))
        finally:
            app.MAX_IMAGE_BYTES = original


class TestCleanHour(unittest.TestCase):
    def test_valid_hours_pass_through(self):
        self.assertEqual(app.clean_hour(0), 0)
        self.assertEqual(app.clean_hour(23), 23)
        self.assertEqual(app.clean_hour(14), 14)

    def test_out_of_range_becomes_none(self):
        self.assertIsNone(app.clean_hour(-1))
        self.assertIsNone(app.clean_hour(24))

    def test_non_int_becomes_none(self):
        self.assertIsNone(app.clean_hour(None))
        self.assertIsNone(app.clean_hour("5"))
        # bool is an int subclass but not a real hour we ever send
        self.assertIsNone(app.clean_hour(12.5))


if __name__ == "__main__":
    unittest.main()
