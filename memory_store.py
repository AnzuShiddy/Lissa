"""Weighted, decaying long-term memory for Lissa.

Replaces the old model — a flat list of ≤30 strings that the LLM rewrote
wholesale every few exchanges — with memory traces that fade unless the
person keeps bringing them up.

Each fact is a record::

    {"text": str, "weight": float, "core": bool,
     "first_seen": iso8601, "last_seen": iso8601, "hits": int}

Every distillation is one *cycle*. On each cycle:

1. every record's weight decays by ``DECAY``;
2. facts this conversation actually supports are reinforced (``+REINFORCE``,
   capped at ``MAX_WEIGHT``) or seeded at ``SEED`` if new;
3. records that fell under ``DROP`` are forgotten, and anything the person
   contradicted is dropped outright.

``core`` facts — a name, where someone lives, what they do — are exempt from
decay: they are the identity scaffold, not a passing mood. Everything else
has a half-life, so a one-off remark fades in ~10 cycles while something
mentioned every time hardens and sticks around ~16 cycles after the person
stops mentioning it.

The design is lifted from AetherMind's ``MemorySystem.ingest_insight``
(weight + decay + provenance + reinforcement); the matching is local
token-overlap so this stays dependency-free.

Records are the wire format for /api/memorize and what the browser keeps in
localStorage, but every entry point also accepts bare strings so memory
saved by the previous version still loads.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Iterable

# Tuned so a fact mentioned once survives roughly ten cycles and a
# well-established one (weight at the cap) roughly sixteen after the person
# goes quiet about it. With the web app distilling every 4 exchanges, that's
# a conversation or two of grace, not an eternity.
DECAY = 0.85          # multiplier applied to every non-core weight per cycle
REINFORCE = 1.0       # added when this conversation supports the fact again
SEED = 2.0            # starting weight for a newly learned fact
DROP = 0.4            # below this a fact is forgotten
MAX_WEIGHT = 5.0      # ceiling, so an obsession can't dominate forever

MAX_TEXT = 200        # per-fact character cap (client-supplied data)

# Token overlap above which two phrasings are treated as the same fact.
# Deliberately lenient: the LLM rewords facts between cycles ("likes jazz" →
# "enjoys jazz music"), and a missed match costs a duplicate plus a lost
# reinforcement.
MATCH_THRESHOLD = 0.5

# Jaccard alone punishes an *elaboration* — "moving to Nairobi" → "moving to
# Nairobi in March" scores 0.4 because the new detail inflates the union, so
# the update would land as a second, contradictory record. Containment (the
# shared fraction of the shorter fact) catches those. It needs the higher bar
# and the two-token floor below, or any two facts sharing one word collapse.
CONTAIN_THRESHOLD = 0.66
CONTAIN_MIN_TOKENS = 2

_WORD_RE = re.compile(r"[a-z0-9']+")

# Small and English-leaning on purpose: it only affects *matching* quality,
# and a stopword that slips through just makes matching slightly stricter.
_STOPWORDS = frozenset("""
a an and are as at be been but by for from had has have he her his him i in is
it its me my not of on or she that the their them they this to us was we were
with you your
""".split())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tokens(text: str) -> set[str]:
    return {
        w for w in _WORD_RE.findall(text.lower())
        if w not in _STOPWORDS and len(w) > 2
    }


def similarity(a: str, b: str) -> float:
    """How much two facts look like the same fact, in [0, 1].

    Jaccard overlap of the meaningful words, except that a clear elaboration
    of one fact by the other is scored on containment instead — see
    CONTAIN_THRESHOLD. Both are normalized against MATCH_THRESHOLD so
    callers compare against one number.
    """
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 1.0 if a.strip().lower() == b.strip().lower() else 0.0
    shared = len(ta & tb)
    jaccard = shared / len(ta | tb)
    smaller = min(len(ta), len(tb))
    if smaller >= CONTAIN_MIN_TOKENS and shared / smaller >= CONTAIN_THRESHOLD:
        return max(jaccard, MATCH_THRESHOLD)
    return jaccard


def _match(text: str, records: list[dict], used: set[int]) -> int | None:
    """Index of the record `text` restates, or None. Best match wins, so a
    cycle mentioning several near-identical facts doesn't collapse them all
    onto whichever record happened to come first."""
    best, best_score = None, MATCH_THRESHOLD
    for i, rec in enumerate(records):
        if i in used:
            continue
        score = similarity(text, rec["text"])
        if score >= best_score:
            best, best_score = i, score
    return best


def normalize(raw: Any, max_facts: int) -> list[dict]:
    """Coerce anything fact-shaped into clean records.

    Accepts the current record format, the previous version's list of bare
    strings, and the partial junk a browser's localStorage can hand back.
    Anything unrecognizable is dropped rather than raising: memory is a
    nice-to-have and must never break a conversation.
    """
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if isinstance(item, str):
            item = {"text": item}
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        try:
            weight = float(item.get("weight", SEED))
        except (TypeError, ValueError):
            weight = SEED
        stamp = _now()
        out.append({
            "text": text.strip()[:MAX_TEXT],
            "weight": min(MAX_WEIGHT, max(0.0, weight)),
            "core": bool(item.get("core", False)),
            "first_seen": item.get("first_seen") if isinstance(item.get("first_seen"), str) else stamp,
            "last_seen": item.get("last_seen") if isinstance(item.get("last_seen"), str) else stamp,
            "hits": int(item["hits"]) if isinstance(item.get("hits"), int) else 1,
        })
    return _rank(out, max_facts)


def _rank(records: list[dict], max_facts: int) -> list[dict]:
    """Strongest first, capped. Core facts outrank everything else so the
    cap can never evict someone's name in favour of a fresh opinion."""
    records.sort(key=lambda r: (r["core"], r["weight"]), reverse=True)
    return records[:max_facts]


def texts(records: Iterable[dict]) -> list[str]:
    """Just the sentences — for prompts and for display."""
    return [r["text"] for r in records if isinstance(r, dict) and r.get("text")]


def merge(
    records: list[dict],
    mentioned: Iterable[Any],
    outdated: Iterable[str] = (),
    max_facts: int = 30,
) -> list[dict]:
    """Fold one cycle's observations into memory.

    ``mentioned`` is what this conversation supports — strings, or dicts with
    ``{"text", "core"}``. ``outdated`` is what the person contradicted; those
    records are dropped regardless of weight, because being wrong about
    someone is worse than forgetting them.
    """
    records = [dict(r) for r in records]
    now = _now()

    # 1. Decay. Core facts are the identity scaffold and never fade.
    for rec in records:
        if not rec["core"]:
            rec["weight"] *= DECAY

    # 2. Reinforce or seed. `used` stops two observations landing on the
    #    same record and double-counting it.
    used: set[int] = set()
    for item in mentioned:
        if isinstance(item, str):
            item = {"text": item}
        if not isinstance(item, dict):
            continue
        text = (item.get("text") or "").strip()[:MAX_TEXT]
        if not text:
            continue
        core = bool(item.get("core", False))
        idx = _match(text, records, used)
        if idx is None:
            records.append({
                "text": text,
                "weight": SEED,
                "core": core,
                "first_seen": now,
                "last_seen": now,
                "hits": 1,
            })
            used.add(len(records) - 1)
        else:
            rec = records[idx]
            rec["weight"] = min(MAX_WEIGHT, rec["weight"] + REINFORCE)
            rec["last_seen"] = now
            rec["hits"] += 1
            rec["core"] = rec["core"] or core
            # Keep the newer phrasing: the LLM's latest wording reflects the
            # most recent thing the person actually said.
            rec["text"] = text
            used.add(idx)

    # 3. Forget: contradicted first, then faded.
    for stale in outdated:
        if not isinstance(stale, str) or not stale.strip():
            continue
        idx = _match(stale.strip(), records, used)
        if idx is not None:
            records.pop(idx)
            used = {i if i < idx else i - 1 for i in used if i != idx}

    records = [r for r in records if r["core"] or r["weight"] >= DROP]

    for rec in records:
        rec["weight"] = round(rec["weight"], 3)
    return _rank(records, max_facts)
