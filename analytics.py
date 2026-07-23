"""Anonymous usage analytics for the web app.

Answers the founder questions — how many people showed up, did they come
back, did they actually talk to her — without collecting anything new about
the visitor:

* Who a visitor *is* stays out of it. The ``sid`` cookie is hashed before it
  touches a log line, and return visits are read from the memory record the
  browser already carries (``chats``/``met``/``last``), so there is no new
  identifier anywhere.
* What a visitor *says* stays out of it. Message events carry lengths and
  flags, never text.

Each event is one JSON line::

    {"t": iso8601-utc, "e": "visit|message|say|transcribe|reset",
     "s": anon-session-hash, ...event fields}

written to two places: ``analytics.jsonl`` next to the app (what
:func:`stats` aggregates) and stdout with an ``analytics `` prefix. The
double write is deliberate — Render's free tier wipes the disk on every
spin-down, but its log store keeps stdout for days, so the file serves the
live /api/stats view while the logs are the durable copy to pull down and
analyze properly.

Recording must never break the chat: every entry point swallows its own
errors.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

FILE = Path(os.environ.get("LISSA_ANALYTICS_FILE", Path(__file__).parent / "analytics.jsonl"))

# A session that sent at least this many messages was a conversation,
# not a drive-by look at the greeting.
ENGAGED_MIN = 3

_write_lock = threading.Lock()


def anon(sid: str | None) -> str:
    """Collapse the session cookie to a short hash: log lines still correlate
    within one session, but a leaked log can't be replayed as a cookie."""
    if not sid:
        return "-"
    return hashlib.sha256(sid.encode()).hexdigest()[:10]


def record(event: str, sid: str | None, **fields: Any) -> None:
    """Append one event, best-effort. Extra fields must be JSON scalars."""
    try:
        entry = {"t": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "e": event, "s": anon(sid)}
        entry.update(fields)
        line = json.dumps(entry, ensure_ascii=False)
        with _write_lock:
            with FILE.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        print("analytics " + line, flush=True)
    except Exception:
        pass  # analytics never takes the app down


def _events(path: Path) -> list[dict]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for line in raw.splitlines():
        try:
            e = json.loads(line)
            if isinstance(e, dict) and "t" in e and "e" in e:
                out.append(e)
        except ValueError:
            continue  # a torn write shouldn't hide the rest
    return out


def stats(days: int = 14, path: Path | None = None, now: datetime | None = None) -> dict:
    """Aggregate the event file into per-day counts (most recent day first).

    visitors   unique sessions that greeted her (visit events)
    returning  of those, sessions whose browser-held memory said chats > 0
    messages   chat messages actually answered
    limited    chat messages refused by a rate/daily limit
    engaged    unique sessions with >= ENGAGED_MIN answered messages
    voice      say events (her replies spoken aloud)
    minutes    total span between each session's first and last event
    """
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    day_of: dict[str, dict] = {}
    msgs_per_sess: dict[tuple[str, str], int] = defaultdict(int)
    span_per_sess: dict[tuple[str, str], list[str]] = {}

    def bucket(day: str) -> dict:
        return day_of.setdefault(day, {
            "day": day, "visitors": set(), "returning": set(),
            "messages": 0, "limited": 0, "engaged": set(), "voice": 0,
            "minutes": 0.0,
        })

    for e in _events(path or FILE):
        day = e["t"][:10]
        if day < cutoff or day > now.strftime("%Y-%m-%d"):
            continue
        b = bucket(day)
        sess = e.get("s", "-")
        kind = e["e"]
        if kind == "visit":
            b["visitors"].add(sess)
            if e.get("chats", 0):
                b["returning"].add(sess)
        elif kind == "message":
            if e.get("limited"):
                b["limited"] += 1
            else:
                b["messages"] += 1
                msgs_per_sess[(day, sess)] += 1
                if msgs_per_sess[(day, sess)] >= ENGAGED_MIN:
                    b["engaged"].add(sess)
        elif kind == "say":
            b["voice"] += 1
        first_last = span_per_sess.setdefault((day, sess), [e["t"], e["t"]])
        first_last[0] = min(first_last[0], e["t"])
        first_last[1] = max(first_last[1], e["t"])

    for (day, _), (first, last) in span_per_sess.items():
        try:
            span = datetime.fromisoformat(last) - datetime.fromisoformat(first)
            day_of[day]["minutes"] += span.total_seconds() / 60.0
        except ValueError:
            continue

    days_out = []
    for day in sorted(day_of, reverse=True):
        b = day_of[day]
        days_out.append({
            "day": day,
            "visitors": len(b["visitors"]),
            "returning": len(b["returning"]),
            "messages": b["messages"],
            "limited": b["limited"],
            "engaged": len(b["engaged"]),
            "voice": b["voice"],
            "minutes": round(b["minutes"], 1),
        })
    totals = {k: sum(d[k] for d in days_out)
              for k in ("visitors", "returning", "messages", "limited", "engaged", "voice")}
    totals["minutes"] = round(sum(d["minutes"] for d in days_out), 1)
    return {"days": days_out, "totals": totals}
