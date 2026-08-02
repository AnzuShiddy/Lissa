#!/usr/bin/env python3
"""Rebuild analytics.jsonl from Render's logs.

Render's free tier has no persistent disk, so ``analytics.jsonl`` is wiped by
every deploy and every spin-down — which is why :mod:`core.analytics` mirrors
each event to stdout as well. The log store keeps that copy for days, but the
running process can't read its own logs back, so recovering history is a pull,
not a sync: export the logs from the dashboard (or ``render logs``), point this
at the file, and the events are merged back into the event log that
``/api/stats`` aggregates.

    python tools/ingest_analytics.py render-logs.txt
    render logs --tail 5000 | python tools/ingest_analytics.py -

Merging is idempotent: events are deduplicated on their canonical JSON, so
overlapping exports can be replayed as often as you like without inflating a
single count. Output is sorted by timestamp, which is also the order
``stats()`` prefers to read.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Where core.analytics writes. Imported rather than duplicated so the two can
# never drift apart on the path or the environment variable that overrides it.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import analytics  # noqa: E402

# The prefix record() puts in front of the JSON on stdout. A log export wraps
# that in the host's own timestamp and stream name, so we look for the marker
# anywhere in the line rather than anchoring at the start.
MARKER = "analytics {"


def events_in(text: str) -> list[dict]:
    """Pull every analytics event out of arbitrary log text.

    Accepts both a raw export (host timestamp, then ``analytics {...}``) and a
    plain ``analytics.jsonl``, so this doubles as a way to merge two event logs
    from different machines.
    """
    out = []
    for line in text.splitlines():
        start = line.find(MARKER)
        if start >= 0:
            blob = line[start + len(MARKER) - 1:]
        elif line.lstrip().startswith("{"):
            blob = line.lstrip()
        else:
            continue  # ordinary log chatter
        try:
            event = json.loads(blob)
        except ValueError:
            continue  # a truncated line at the edge of an export
        if isinstance(event, dict) and "t" in event and "e" in event:
            out.append(event)
    return out


def canonical(event: dict) -> str:
    """A stable identity for an event, so the same one from two exports — or
    from the file and an export — collapses to one record regardless of key
    order or how it was serialized."""
    return json.dumps(event, sort_keys=True, ensure_ascii=False)


def merge(existing: list[dict], incoming: list[dict]) -> tuple[list[dict], int]:
    """Return the union sorted by timestamp, plus how many were genuinely new."""
    seen = {canonical(e) for e in existing}
    merged = list(existing)
    added = 0
    for event in incoming:
        key = canonical(event)
        if key in seen:
            continue
        seen.add(key)
        merged.append(event)
        added += 1
    merged.sort(key=lambda e: e.get("t", ""))
    return merged, added


def write(path: Path, events: list[dict]) -> None:
    """Replace the log atomically: a half-written file here would lose the very
    history this script exists to recover."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events),
                   encoding="utf-8")
    tmp.replace(path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("logs", nargs="+",
                    help="Render log export(s), or - for stdin")
    ap.add_argument("--into", type=Path, default=analytics.FILE,
                    help=f"event log to merge into (default: {analytics.FILE})")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be added, write nothing")
    args = ap.parse_args(argv)

    incoming: list[dict] = []
    for name in args.logs:
        text = sys.stdin.read() if name == "-" else Path(name).read_text(
            encoding="utf-8", errors="replace")
        found = events_in(text)
        print(f"{name}: {len(found)} events")
        incoming += found

    existing = analytics._events(args.into)
    merged, added = merge(existing, incoming)

    if args.dry_run:
        print(f"would add {added} new event(s) to {args.into} "
              f"({len(existing)} -> {len(merged)})")
        return 0

    write(args.into, merged)
    print(f"added {added} new event(s) to {args.into} "
          f"({len(existing)} -> {len(merged)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
