"""Unit tests for the weighted memory store — pure logic, no API calls.

Run:  .venv/bin/python -m unittest discover -s tests -t . -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import memory_store as ms


def cycles(records, mentioned, n, outdated=()):
    """Run n merge cycles, mentioning the same things each time."""
    for _ in range(n):
        records = ms.merge(records, mentioned, outdated)
    return records


def find(records, needle):
    for r in records:
        if needle in r["text"]:
            return r
    return None


class TestNormalize(unittest.TestCase):
    def test_accepts_old_string_list(self):
        """Memory written by the previous version must still load."""
        out = ms.normalize(["Their name is Aziza", "Likes jazz"], 30)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["weight"], ms.SEED)
        self.assertFalse(out[0]["core"])

    def test_records_round_trip(self):
        recs = ms.normalize([{"text": "Lives in Nairobi", "weight": 3.5, "core": True}], 30)
        self.assertEqual(recs[0]["weight"], 3.5)
        self.assertTrue(recs[0]["core"])

    def test_drops_junk_without_raising(self):
        out = ms.normalize([None, 42, {}, {"text": "   "}, {"text": "ok"}], 30)
        self.assertEqual(ms.texts(out), ["ok"])

    def test_non_list_is_empty(self):
        self.assertEqual(ms.normalize("not a list", 30), [])
        self.assertEqual(ms.normalize(None, 30), [])

    def test_clamps_weight_and_length(self):
        out = ms.normalize([{"text": "x" * 500, "weight": 99}], 30)
        self.assertEqual(len(out[0]["text"]), ms.MAX_TEXT)
        self.assertEqual(out[0]["weight"], ms.MAX_WEIGHT)

    def test_caps_to_max_facts_keeping_strongest(self):
        raw = [{"text": f"fact {i}", "weight": i / 10} for i in range(50)]
        out = ms.normalize(raw, 5)
        self.assertEqual(len(out), 5)
        self.assertEqual(out[0]["text"], "fact 49")


class TestReinforcement(unittest.TestCase):
    def test_new_fact_is_seeded(self):
        out = ms.merge([], ["Loves late-night drives"])
        self.assertEqual(out[0]["weight"], ms.SEED)
        self.assertEqual(out[0]["hits"], 1)

    def test_repetition_strengthens(self):
        out = cycles([], ["Loves late-night drives"], 4)
        self.assertEqual(len(out), 1)
        self.assertGreater(out[0]["weight"], ms.SEED)
        self.assertEqual(out[0]["hits"], 4)

    def test_weight_is_capped(self):
        out = cycles([], ["Loves late-night drives"], 50)
        self.assertLessEqual(out[0]["weight"], ms.MAX_WEIGHT)

    def test_rewording_matches_instead_of_duplicating(self):
        """The model rewords facts between cycles; that must reinforce, not
        create a second copy of the same thing."""
        out = ms.merge([], ["They love jazz music"])
        out = ms.merge(out, ["They love listening to jazz music"])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["hits"], 2)

    def test_elaboration_does_not_become_a_contradictory_duplicate(self):
        out = ms.merge([], ["Lives in Nairobi"])
        out = ms.merge(out, ["Lives in Nairobi with two sisters"])
        self.assertEqual(len(out), 1)

    def test_same_shape_different_detail_stays_separate(self):
        """Containment matching must not fuse facts that differ in the one
        word that carries the meaning."""
        out = ms.merge([], ["Lives in Nairobi"])
        out = ms.merge(out, ["Lives in Mombasa"])
        self.assertEqual(len(out), 2)

    def test_unrelated_facts_stay_separate(self):
        out = ms.merge([], ["They love jazz music"])
        out = ms.merge(out, ["They work as a nurse in Mombasa"])
        self.assertEqual(len(out), 2)

    def test_latest_phrasing_wins(self):
        out = ms.merge([], ["Is thinking about moving to Nairobi"])
        out = ms.merge(out, ["Is moving to Nairobi in March"])
        self.assertEqual(len(out), 1)
        self.assertIn("March", out[0]["text"])

    def test_one_observation_reinforces_one_record(self):
        """Two near-identical stored facts must not both be bumped by a
        single mention."""
        start = ms.normalize(["Likes jazz", "Likes jazz a lot"], 30)
        out = ms.merge(start, ["Likes jazz"])
        self.assertEqual(sum(r["hits"] for r in out), 3)  # 1 + 1 seeded, +1


class TestDecay(unittest.TestCase):
    def test_unmentioned_fact_fades(self):
        start = ms.merge([], ["Was in a bad mood on Tuesday"])
        faded = cycles(start, [], 20)
        self.assertEqual(faded, [])

    def test_one_off_outlives_a_conversation_but_not_forever(self):
        """A passing remark should survive the next chat, not a month."""
        start = ms.merge([], ["Was in a bad mood on Tuesday"])
        self.assertTrue(cycles(start, [], 3))    # still there shortly after
        self.assertFalse(cycles(start, [], 15))  # long gone later

    def test_established_facts_outlast_new_ones(self):
        established = cycles([], ["Plays guitar every evening"], 10)
        fresh = ms.merge([], ["Mentioned a film once"])
        # A seeded fact crosses DROP after ~10 quiet cycles, a capped one
        # after ~16, so the two are only distinguishable in between.
        quiet = 12
        self.assertTrue(cycles(established, [], quiet))
        self.assertFalse(cycles(fresh, [], quiet))

    def test_core_facts_never_decay(self):
        start = ms.merge([], [{"text": "Their name is Aziza", "core": True}])
        out = cycles(start, [], 200)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["weight"], ms.SEED)

    def test_core_promotion_is_sticky(self):
        out = ms.merge([], ["Their name is Aziza"])
        out = ms.merge(out, [{"text": "Their name is Aziza", "core": True}])
        out = ms.merge(out, [{"text": "Their name is Aziza", "core": False}])
        self.assertTrue(out[0]["core"])

    def test_core_outranks_weight_under_the_cap(self):
        loud = [{"text": f"opinion {i}", "weight": ms.MAX_WEIGHT} for i in range(30)]
        start = ms.normalize(loud + [{"text": "Their name is Aziza", "core": True}], 31)
        out = ms.merge(start, [], max_facts=5)
        self.assertIsNotNone(find(out, "Aziza"))


class TestForgetting(unittest.TestCase):
    def test_contradiction_drops_regardless_of_weight(self):
        start = cycles([], ["Lives in Nairobi"], 10)
        self.assertGreater(start[0]["weight"], ms.SEED)
        out = ms.merge(start, [], outdated=["Lives in Nairobi"])
        self.assertEqual(out, [])

    def test_correction_replaces_old_fact(self):
        start = cycles([], ["Works as a teacher"], 5)
        out = ms.merge(start, ["Works as a nurse"], outdated=["Works as a teacher"])
        self.assertEqual(len(out), 1)
        self.assertIn("nurse", out[0]["text"])

    def test_outdated_does_not_eat_a_freshly_mentioned_fact(self):
        """A fact confirmed this cycle must not be removed by a stale
        'outdated' entry naming the same thing."""
        start = ms.merge([], ["Lives in Nairobi"])
        out = ms.merge(start, ["Lives in Nairobi"], outdated=["Lives in Nairobi"])
        self.assertEqual(len(out), 1)

    def test_unknown_outdated_entry_is_harmless(self):
        start = ms.merge([], ["Likes jazz"])
        out = ms.merge(start, [], outdated=["Has a pet iguana", "", None])
        self.assertEqual(len(out), 1)


class TestMergeHygiene(unittest.TestCase):
    def test_does_not_mutate_input(self):
        start = ms.merge([], ["Likes jazz"])
        before = [dict(r) for r in start]
        ms.merge(start, ["Likes jazz"])
        self.assertEqual(start, before)

    def test_ignores_malformed_observations(self):
        out = ms.merge([], [None, 7, {}, {"text": ""}, "Likes jazz"])
        self.assertEqual(ms.texts(out), ["Likes jazz"])

    def test_respects_max_facts(self):
        out = ms.merge([], [f"fact number {i}" for i in range(100)], max_facts=10)
        self.assertEqual(len(out), 10)

    def test_texts_helper(self):
        out = ms.merge([], ["Likes jazz"])
        self.assertEqual(ms.texts(out), ["Likes jazz"])


class TestSimilarity(unittest.TestCase):
    def test_identical(self):
        self.assertEqual(ms.similarity("likes jazz", "likes jazz"), 1.0)

    def test_unrelated(self):
        self.assertLess(ms.similarity("likes jazz", "works in Mombasa"), ms.MATCH_THRESHOLD)

    def test_stopword_only_strings_compare_exactly(self):
        self.assertEqual(ms.similarity("in the", "in the"), 1.0)
        self.assertEqual(ms.similarity("in the", "of it"), 0.0)


if __name__ == "__main__":
    unittest.main()
