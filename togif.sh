#!/usr/bin/env bash
# togif.sh — turn a screen recording into a small, sharp GIF for launch posts.
#
# Uses ffmpeg's two-pass palette method (generate an optimal 256-colour
# palette from the clip, then map to it) — far cleaner and smaller than a
# naive one-pass GIF, which is what makes text in the recording stay legible.
#
# Usage:
#   ./togif.sh recording.mp4                 # -> recording.gif
#   ./togif.sh recording.mp4 lissa-demo.gif  # explicit output name
#   FPS=15 WIDTH=600 ./togif.sh in.mp4       # override defaults
#   START=2 DURATION=10 ./togif.sh in.mp4    # trim: 10s starting at 0:02
#
# Env knobs (all optional):
#   FPS       frames/sec           (default 12 — smooth enough, keeps size down)
#   WIDTH     output width in px   (default 640; height auto, aspect kept)
#   START     trim start, seconds  (default: from the beginning)
#   DURATION  clip length, seconds (default: to the end)
#
# Smaller file: lower FPS (10) and WIDTH (480) first — they cut size the most.

set -euo pipefail

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg not found. Install it first:  sudo apt-get install -y ffmpeg" >&2
  exit 1
fi

IN="${1:-}"
if [ -z "$IN" ] || [ ! -f "$IN" ]; then
  echo "usage: $0 <input-video> [output.gif]" >&2
  exit 1
fi

OUT="${2:-${IN%.*}.gif}"
FPS="${FPS:-12}"
WIDTH="${WIDTH:-640}"

# Optional trim, only added to the command when the vars are set.
trim=()
[ -n "${START:-}" ] && trim+=(-ss "$START")
[ -n "${DURATION:-}" ] && trim+=(-t "$DURATION")

palette="$(mktemp --suffix=.png)"
trap 'rm -f "$palette"' EXIT

filters="fps=${FPS},scale=${WIDTH}:-1:flags=lanczos"

echo "Pass 1/2: building colour palette..."
ffmpeg -hide_banner -loglevel error -y "${trim[@]}" -i "$IN" \
  -vf "${filters},palettegen=stats_mode=diff" "$palette"

echo "Pass 2/2: encoding GIF..."
ffmpeg -hide_banner -loglevel error -y "${trim[@]}" -i "$IN" -i "$palette" \
  -lavfi "${filters} [x]; [x][1:v] paletteuse=dither=sierra2_4a" "$OUT"

size="$(du -h "$OUT" | cut -f1)"
echo "Done -> $OUT  (${size}, ${FPS}fps, ${WIDTH}px wide)"
echo "If it's over ~5MB, retry with:  FPS=10 WIDTH=480 $0 \"$IN\" \"$OUT\""
