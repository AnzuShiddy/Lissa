"""The speaking rate, and the number the page paces its typing off.

The requirement these guard: however fast a bot is set to speak — including
when that's changed on the host rather than in the code — the text has to
come out in step with the voice.
"""

import os
import unittest

import bots
from core.persona import rate_factor


class RateFactorTests(unittest.TestCase):
    def test_slower_rate_is_a_factor_below_one(self):
        """-8% means 8% slower, so a clip runs ~1.087x longer."""
        self.assertAlmostEqual(rate_factor("-8%"), 0.92)

    def test_faster_rate_is_a_factor_above_one(self):
        self.assertAlmostEqual(rate_factor("+10%"), 1.1)

    def test_normal_speed(self):
        self.assertAlmostEqual(rate_factor("0%"), 1.0)

    def test_accepts_a_decimal_and_stray_whitespace(self):
        self.assertAlmostEqual(rate_factor("  -12.5 % "), 0.875)

    def test_a_typo_reads_as_ordinary_speed(self):
        """A bad dashboard value must not make the voice absurd or silent."""
        for junk in ("", "fast", "8", "-8", "%", "--8%", None):
            self.assertEqual(rate_factor(junk), 1.0, junk)

    def test_clamped_so_the_typing_pace_can_never_divide_by_zero(self):
        self.assertEqual(rate_factor("-100%"), 0.25)
        self.assertEqual(rate_factor("+900%"), 3.0)


class OverrideTests(unittest.TestCase):
    """PLATFORM_EDGE_RATE_<SLUG> beats PLATFORM_EDGE_RATE beats the config."""

    def setUp(self):
        self.bot = bots.get("lissa")
        self._saved = {k: os.environ.get(k) for k in
                       ("PLATFORM_EDGE_RATE", "PLATFORM_EDGE_RATE_LISSA")}
        for k in self._saved:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_falls_back_to_the_bots_own_setting(self):
        self.assertEqual(self.bot.speech_rate, self.bot.edge_rate)

    def test_a_platform_wide_variable_overrides_the_config(self):
        os.environ["PLATFORM_EDGE_RATE"] = "-25%"
        self.assertEqual(self.bot.speech_rate, "-25%")

    def test_a_per_bot_variable_wins_over_the_platform_wide_one(self):
        """The two bots ship at different speeds on purpose."""
        os.environ["PLATFORM_EDGE_RATE"] = "-25%"
        os.environ["PLATFORM_EDGE_RATE_LISSA"] = "-5%"
        self.assertEqual(self.bot.speech_rate, "-5%")
        self.assertEqual(bots.get("athar").speech_rate, "-25%")

    def test_read_at_call_time_so_no_restart_is_needed(self):
        os.environ["PLATFORM_EDGE_RATE"] = "-30%"
        self.assertEqual(self.bot.speech_rate, "-30%")
        os.environ["PLATFORM_EDGE_RATE"] = "-40%"
        self.assertEqual(self.bot.speech_rate, "-40%")


class ManifestTests(unittest.TestCase):
    """The page can only match a speed it was told about."""

    def setUp(self):
        self._saved = os.environ.get("PLATFORM_EDGE_RATE")
        os.environ.pop("PLATFORM_EDGE_RATE", None)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("PLATFORM_EDGE_RATE", None)
        else:
            os.environ["PLATFORM_EDGE_RATE"] = self._saved

    def test_every_bot_publishes_its_speech_rate(self):
        for bot in bots.all_bots():
            rate = bot.manifest().get("speechRate")
            self.assertIsInstance(rate, float, bot.slug)
            self.assertAlmostEqual(rate, rate_factor(bot.edge_rate), msg=bot.slug)

    def test_the_published_rate_follows_the_override(self):
        os.environ["PLATFORM_EDGE_RATE"] = "-50%"
        for bot in bots.all_bots():
            self.assertAlmostEqual(bot.manifest()["speechRate"], 0.5, msg=bot.slug)


class PacingArithmeticTests(unittest.TestCase):
    """Mirrors guessedRevealMs() in app.html: BASE_MS_PER_CHAR / factor.

    Kept here because the property that matters is arithmetic, not DOM: a
    slower voice must always produce a *longer* reveal, never a shorter one.
    """

    BASE = 46

    def reveal_ms(self, chars: int, rate: str) -> float:
        return max(1000, chars * (self.BASE / rate_factor(rate)))

    def test_the_default_pace_is_unchanged(self):
        """46 / 0.92 is the 50ms per character the app has always used."""
        self.assertAlmostEqual(self.BASE / rate_factor("-8%"), 50.0)

    def test_slower_speech_types_more_slowly(self):
        fast = self.reveal_ms(400, "+20%")
        normal = self.reveal_ms(400, "0%")
        slow = self.reveal_ms(400, "-40%")
        self.assertLess(fast, normal)
        self.assertLess(normal, slow)

    def test_halving_the_speed_doubles_the_reveal(self):
        self.assertAlmostEqual(self.reveal_ms(400, "-50%"),
                               2 * self.reveal_ms(400, "0%"))

    def test_a_short_line_still_gets_a_readable_minimum(self):
        self.assertEqual(self.reveal_ms(3, "+50%"), 1000)


if __name__ == "__main__":
    unittest.main()
