"""Semantic recall — put only the *relevant* memories in front of Lissa.

Every fact used to go into the system prompt on every turn. Ask her about
music and she was also holding your job, your sister's name and the film you
mentioned last week. That costs tokens, dilutes attention, and puts a hard
ceiling on how much she can usefully remember.

Here each message is embedded and compared against the facts, and only the
close ones ride along (plus core facts, which are context for everything).

Everything degrades to the old behaviour — send all the facts — rather than
failing: no key, no quota, a 429, an SDK change, anything. Memory is a
nice-to-have and must never break a conversation.

The selection maths lives in memory_store.select() so it stays pure and
testable; this module only handles the API call and the cache.
"""

from __future__ import annotations

import threading

from google.genai import types

import memory_store

EMBED_MODEL = "gemini-embedding-001"

# 3072 is the model's native width. 768 costs a quarter of the arithmetic in
# the pure-Python cosine and loses nothing that matters at this scale — we're
# ranking a few dozen short sentences, not building a search index.
EMBED_DIM = 768

# Fact texts are stable across turns and across visitors, so one process-wide
# cache spares nearly every repeat embedding. Vectors are ~6 KB each; the cap
# keeps the cache well under a few MB.
_CACHE_MAX = 500
_cache: dict[str, list[float]] = {}
_cache_lock = threading.Lock()


def _cached(texts: list[str]) -> tuple[list[str], dict[str, list[float]]]:
    """Split `texts` into those still needing an embedding and those we have."""
    with _cache_lock:
        have = {t: _cache[t] for t in texts if t in _cache}
    return [t for t in texts if t not in have], have


def _store(pairs: dict[str, list[float]]) -> None:
    with _cache_lock:
        # Wholesale clear rather than LRU bookkeeping: this is a cache of
        # cheap, easily-recomputed values, and the texts churn slowly.
        if len(_cache) + len(pairs) > _CACHE_MAX:
            _cache.clear()
        _cache.update(pairs)


def embed(client, texts: list[str], *, query: bool = False) -> list[list[float]] | None:
    """Embed `texts`, one batched call for whatever isn't cached.

    `query` selects the retrieval task type for the incoming message, as
    opposed to the stored facts it is being matched against. Returns None on
    any failure, which callers read as "fall back to sending everything".
    """
    if not texts:
        return []
    missing, have = _cached(texts)
    if missing:
        try:
            response = client.models.embed_content(
                model=EMBED_MODEL,
                contents=missing,
                config=types.EmbedContentConfig(
                    task_type="RETRIEVAL_QUERY" if query else "RETRIEVAL_DOCUMENT",
                    output_dimensionality=EMBED_DIM,
                ),
            )
            fresh = {t: list(e.values) for t, e in zip(missing, response.embeddings, strict=True)}
        except Exception:
            return None
        if len(fresh) != len(missing):
            return None
        _store(fresh)
        have.update(fresh)
    return [have[t] for t in texts]


def relevant(client, facts: list[dict], message: str) -> list[dict]:
    """The subset of `facts` worth sending along with `message`.

    Short memories skip retrieval entirely — under RECALL_MIN_FACTS the whole
    set fits comfortably in the prompt, and an embedding call per turn would
    buy nothing.
    """
    message = (message or "").strip()
    if not message or len(facts) < memory_store.RECALL_MIN_FACTS:
        return facts

    # Query and documents use different task types, so they can't share one
    # batched call.
    query_vec = embed(client, [message], query=True)
    if not query_vec:
        return facts
    vectors = embed(client, memory_store.texts(facts))
    if vectors is None:
        return facts

    return memory_store.select(facts, query_vec[0], vectors)
