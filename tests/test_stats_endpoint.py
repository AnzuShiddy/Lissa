"""/api/stats is closed unless a token is configured, and /healthz is not.

Skipped when FastAPI isn't installed: the unit job deliberately runs on the
standard library alone, and this is the one suite that needs the web stack.
The same ground is covered against a live server in tests/ui_test.js.
"""

import os
import unittest

try:
    from fastapi.testclient import TestClient
    HAVE_FASTAPI = True
except ImportError:  # pragma: no cover - depends on the environment
    HAVE_FASTAPI = False


@unittest.skipUnless(HAVE_FASTAPI, "FastAPI not installed")
class StatsEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("GEMINI_API_KEY", "test-key-not-used")
        import app
        cls.app = app
        cls.client = TestClient(app.app)

    def setUp(self):
        self._saved = self.app.STATS_TOKEN

    def tearDown(self):
        self.app.STATS_TOKEN = self._saved

    def test_closed_when_no_token_is_configured(self):
        """The state of a fresh deploy: it must expose nothing, not everything."""
        self.app.STATS_TOKEN = ""
        r = self.client.get("/api/stats")
        self.assertEqual(r.status_code, 404)
        self.assertNotIn("totals", r.text)

    def test_rejects_a_wrong_token(self):
        self.app.STATS_TOKEN = "the-real-token"
        self.assertEqual(self.client.get("/api/stats?token=nope").status_code, 403)

    def test_rejects_a_missing_token_when_one_is_configured(self):
        self.app.STATS_TOKEN = "the-real-token"
        self.assertEqual(self.client.get("/api/stats").status_code, 403)

    def test_serves_the_counts_with_the_right_token(self):
        self.app.STATS_TOKEN = "the-real-token"
        r = self.client.get("/api/stats?token=the-real-token")
        self.assertEqual(r.status_code, 200)
        self.assertIn("totals", r.json())

    def test_a_token_prefix_is_not_enough(self):
        """compare_digest, not startswith — guards against a sloppy rewrite."""
        self.app.STATS_TOKEN = "the-real-token"
        self.assertEqual(self.client.get("/api/stats?token=the-real").status_code, 403)


@unittest.skipUnless(HAVE_FASTAPI, "FastAPI not installed")
class HealthzTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("GEMINI_API_KEY", "test-key-not-used")
        import app
        cls.app = app
        cls.client = TestClient(app.app)

    def test_open_without_any_token(self):
        """Keep-warm pings this every 10 minutes and holds no secret."""
        self.app.STATS_TOKEN = ""
        r = self.client.get("/healthz")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"ok": True})

    def test_stays_open_when_stats_is_locked(self):
        self.app.STATS_TOKEN = "the-real-token"
        self.assertEqual(self.client.get("/healthz").status_code, 200)

    def test_leaks_no_counts(self):
        """A heartbeat shouldn't answer 'how many people came' to anyone asking."""
        body = self.client.get("/healthz").json()
        for leaky in ("totals", "days", "sessions_live", "visitors"):
            self.assertNotIn(leaky, body)


if __name__ == "__main__":
    unittest.main()
