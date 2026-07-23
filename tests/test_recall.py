"""Unit tests for semantic recall — the embedding cache and the fallbacks
in relevant(). No network: a fake client stands in for Gemini embeddings.

Run:  .venv/bin/python -m unittest discover -s tests -t . -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import memory_store as ms
import recall


class FakeEmbedding:
    def __init__(self, values):
        self.values = values


class FakeResponse:
    def __init__(self, embeddings):
        self.embeddings = embeddings


class FakeModels:
    """Stand-in for client.models. Records how many embed calls it saw so a
    test can prove the cache spared a round-trip. `table` maps a text to the
    vector to return; anything absent gets a default. `fail` raises (the
    "quota/network hiccup" path); `short` drops one embedding to simulate a
    truncated response."""

    def __init__(self, table=None, fail=False, short=False):
        self.table = table or {}
        self.fail = fail
        self.short = short
        self.calls = 0
        self.embedded = []  # every batch of contents actually sent

    def embed_content(self, *, model, contents, config):
        self.calls += 1
        self.embedded.append(list(contents))
        if self.fail:
            raise RuntimeError("simulated embedding failure")
        embs = [FakeEmbedding(self.table.get(t, [0.0, 0.0, 1.0])) for t in contents]
        if self.short:
            embs = embs[:-1]
        return FakeResponse(embs)


class FakeClient:
    def __init__(self, **kw):
        self.models = FakeModels(**kw)


class ExplodingClient:
    """Any use of the API is a bug for the short-circuit paths."""

    @property
    def models(self):
        raise AssertionError("recall must not call the API here")


def facts(n, core_indices=()):
    return [
        {"text": f"fact number {i}", "weight": 1.0, "core": i in core_indices}
        for i in range(n)
    ]


class TestCache(unittest.TestCase):
    def setUp(self):
        recall._cache.clear()

    def test_cached_splits_hits_and_misses(self):
        recall._store({"alpha": [1.0], "beta": [2.0]})
        missing, have = recall._cached(["alpha", "gamma"])
        self.assertEqual(missing, ["gamma"])
        self.assertEqual(have, {"alpha": [1.0]})

    def test_store_evicts_wholesale_at_cap(self):
        recall._store({f"k{i}": [float(i)] for i in range(recall._CACHE_MAX)})
        self.assertEqual(len(recall._cache), recall._CACHE_MAX)
        # One more entry would exceed the cap → the cache is cleared first,
        # so only the newcomer survives.
        recall._store({"newcomer": [1.0]})
        self.assertEqual(recall._cache, {"newcomer": [1.0]})


class TestEmbed(unittest.TestCase):
    def setUp(self):
        recall._cache.clear()

    def test_empty_texts_short_circuits(self):
        client = FakeClient()
        self.assertEqual(recall.embed(client, []), [])
        self.assertEqual(client.models.calls, 0)

    def test_returns_vectors_in_input_order(self):
        client = FakeClient(table={"a": [1.0], "b": [2.0]})
        self.assertEqual(recall.embed(client, ["a", "b"]), [[1.0], [2.0]])

    def test_second_call_is_served_from_cache(self):
        client = FakeClient(table={"a": [1.0]})
        recall.embed(client, ["a"])
        recall.embed(client, ["a"])
        self.assertEqual(client.models.calls, 1)  # the repeat hit the cache

    def test_failure_returns_none(self):
        self.assertIsNone(recall.embed(FakeClient(fail=True), ["a"]))

    def test_length_mismatch_returns_none(self):
        client = FakeClient(short=True)
        self.assertIsNone(recall.embed(client, ["a", "b"]))


class TestRelevant(unittest.TestCase):
    def setUp(self):
        recall._cache.clear()

    def test_short_memory_skips_retrieval(self):
        few = facts(ms.RECALL_MIN_FACTS - 1)
        self.assertEqual(recall.relevant(ExplodingClient(), few, "music"), few)

    def test_blank_message_skips_retrieval(self):
        many = facts(ms.RECALL_MIN_FACTS + 2)
        self.assertEqual(recall.relevant(ExplodingClient(), many, "   "), many)

    def test_embed_failure_falls_back_to_all_facts(self):
        many = facts(ms.RECALL_MIN_FACTS + 2)
        self.assertEqual(recall.relevant(FakeClient(fail=True), many, "music"), many)

    def test_selects_matching_fact_and_keeps_core(self):
        # Nine facts; make fact 3 point the same direction as the query and
        # everything else orthogonal, and mark fact 0 core. Recall should
        # return a subset that includes the on-topic fact and the core one.
        recs = facts(9, core_indices=(0,))
        table = {r["text"]: [1.0, 0.0] if i == 3 else [0.0, 1.0]
                 for i, r in enumerate(recs)}
        table["what music do you like"] = [1.0, 0.0]
        client = FakeClient(table=table)
        out = recall.relevant(client, recs, "what music do you like")
        kept = ms.texts(out)
        self.assertIn("fact number 3", kept)   # the on-topic match
        self.assertIn("fact number 0", kept)   # core rides along regardless
        self.assertLess(len(out), len(recs))   # and it actually narrowed


if __name__ == "__main__":
    unittest.main()
