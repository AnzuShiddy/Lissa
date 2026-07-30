#!/usr/bin/env python3
"""Talk to any bot on the platform from a terminal.

    .venv/bin/python cli.py            # pick from the registry
    .venv/bin/python cli.py athar      # straight to one

Commands: /talk speaks a message instead of typing it, /voice toggles spoken
replies, /memory shows what it remembers, /forget wipes that, /reset clears
the conversation but keeps the memory, /quit exits.

Memory here is a file per bot under .memory/, which is the one place the
terminal app differs from the web app — there, it lives in the browser.
"""

import json
import os
import signal
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from google.genai import errors

import bots
from core import engine, persona, speech
from core.persona import Bot

MEMORY_DIR = Path(__file__).parent / ".memory"
AUDIO_PLAYERS = ("paplay", "aplay", "ffplay", "mpv", "play")


def memory_file(bot: Bot) -> Path:
    return MEMORY_DIR / f"{bot.slug}.json"


def load_memory(bot: Bot) -> dict:
    try:
        return persona.clean_memory(bot, json.loads(memory_file(bot).read_text()))
    except (FileNotFoundError, json.JSONDecodeError):
        return persona.blank_memory()


def save_memory(bot: Bot, mem: dict) -> None:
    # Written atomically: a crash mid-write would leave a truncated file, and
    # the next run would greet a regular as a stranger.
    MEMORY_DIR.mkdir(exist_ok=True)
    tmp = memory_file(bot).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(mem, indent=2, ensure_ascii=False))
    os.replace(tmp, memory_file(bot))


def find_player() -> list[str] | None:
    for name in AUDIO_PLAYERS:
        path = shutil.which(name)
        if path:
            if name == "ffplay":
                return [path, "-nodisp", "-autoexit", "-loglevel", "quiet"]
            if name == "mpv":
                return [path, "--really-quiet"]
            return [path]
    return None


def find_recorder() -> list[str] | None:
    """A mic-capture command that writes raw s16le PCM to a path appended as
    its last argument."""
    path = shutil.which("parecord")
    if path:
        return [path, "--raw", "--format=s16le",
                f"--rate={speech.RECORD_RATE}", "--channels=1"]
    path = shutil.which("arecord")
    if path:
        return [path, "-q", "-t", "raw", "-f", "S16_LE",
                "-r", str(speech.RECORD_RATE), "-c", "1"]
    return None


def record_audio(recorder: list[str]) -> bytes:
    """Record until Enter. Returns raw PCM."""
    with tempfile.NamedTemporaryFile(suffix=".raw", delete=False) as tmp:
        raw_path = tmp.name
    proc = subprocess.Popen(recorder + [raw_path],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        input("\n(listening... press Enter when you're done) ")
    except (EOFError, KeyboardInterrupt):
        pass
    finally:
        # SIGINT lets the recorder flush and close the file cleanly
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    try:
        return Path(raw_path).read_bytes()
    finally:
        os.unlink(raw_path)


def speak(bot: Bot, client, player: list[str], text: str) -> bool:
    """Say it out loud. False when the quota is spent, so the caller can stop
    trying for this session."""
    try:
        wav = speech.synthesize(bot, client, text)
    except speech.VoiceQuotaError:
        print("(voice quota hit for now — it'll just type)")
        return False
    if wav is None:
        return True
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(wav)
        path = tmp.name
    try:
        subprocess.run(player + [path], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=120)
    finally:
        os.unlink(path)
    return True


def local_context(bot: Bot) -> str:
    """Prayer/qibla context for bots that use it, from PLATFORM_LAT and
    PLATFORM_LON. The web app gets coordinates from the browser; here they're
    opt-in environment variables and everything works without them."""
    if not bot.has("prayer"):
        return ""
    try:
        from datetime import datetime

        from core import prayer
        lat = float(os.environ["PLATFORM_LAT"])
        lon = float(os.environ["PLATFORM_LON"])
        now = datetime.now()
        offset = (now - datetime.utcnow()).total_seconds() / 3600.0
        data = prayer.summary(lat, lon, round(offset * 4) / 4,
                              os.environ.get("PLATFORM_METHOD", prayer.DEFAULT_METHOD),
                              os.environ.get("PLATFORM_ASR", "standard"), now)
        return prayer.context(data, now)
    except Exception:
        return ""


def choose_bot(argv: list[str]) -> Bot:
    if len(argv) > 1:
        bot = bots.get(argv[1].lower())
        if bot is None:
            print(f"No bot called {argv[1]!r}. Available: "
                  + ", ".join(bots.REGISTRY))
            sys.exit(1)
        return bot
    listing = bots.all_bots()
    print("\nWho do you want to talk to?\n")
    for i, bot in enumerate(listing, 1):
        print(f"  {i}. {bot.name} {bot.emoji} — {bot.tagline}")
    while True:
        try:
            pick = input("\n> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            sys.exit(0)
        if pick.isdigit() and 1 <= int(pick) <= len(listing):
            return listing[int(pick) - 1]
        if bots.get(pick):
            return bots.get(pick)
        print("Pick a number or a name.")


def show_memory(bot: Bot, mem: dict) -> None:
    if not (mem["facts"] or mem["threads"] or mem["extras"]):
        print("\n(no memories yet — they're saved when a chat ends)\n")
        return
    print(f"\nWhat {bot.name} remembers about you:")
    for fact in mem["facts"]:
        # how firmly each is held: core facts are permanent, the rest fade
        strength = "core" if fact["core"] else f"{fact['weight']:.1f}"
        print(f"  - {fact['text']}  ({strength})")
    if mem["threads"]:
        print("\nWaiting to hear about:")
        for thread in mem["threads"]:
            print(f"  - {thread}")
    if mem["extras"]:
        print(f"\n{bot.extras_name.capitalize()}:")
        for extra in mem["extras"]:
            print(f"  - {extra}")
    print()


def chat(bot: Bot) -> None:
    client = engine.make_client()
    mem = persona.touch_memory(bot, load_memory(bot))
    context = local_context(bot)
    session = client.chats.create(model=engine.MODEL,
                                  config=engine.config_for(bot, mem, context))

    def remember() -> dict:
        """Distill and persist. Best-effort: memory never breaks a goodbye."""
        updated = engine.distill_chat(bot, client, session, mem)
        save_memory(bot, updated)
        return updated

    player = find_player()
    voice_on = player is not None
    if player is None:
        print("\n(no audio player found — voice disabled. To enable it:"
              " sudo apt install pulseaudio-utils)")
    recorder = find_recorder()
    if recorder is not None:
        print(f"\n(type /talk to speak to {bot.name} instead of typing)")

    hello = persona.greeting(bot, mem)
    print(f"\n{bot.name}: {hello}\n")
    if voice_on:
        voice_on = speak(bot, client, player, hello)

    while True:
        try:
            entry = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{bot.name}: {bot.sign_off}")
            mem = remember()
            break
        if not entry:
            continue

        command = entry.lower()
        if command in ("/quit", "/exit"):
            print(f"\n{bot.name}: {bot.sign_off}\n")
            mem = remember()
            break
        if command == "/memory":
            show_memory(bot, mem)
            continue
        if command == "/forget":
            mem = persona.blank_memory()
            memory_file(bot).unlink(missing_ok=True)
            session = client.chats.create(model=engine.MODEL,
                                          config=engine.config_for(bot, mem, context))
            print(f"\n(memory wiped — {bot.name} is meeting you for the first time again)\n")
            print(f"{bot.name}: {persona.greeting(bot, mem)}\n")
            continue
        if command == "/voice":
            if player is None:
                print("\n(no audio player installed — run: sudo apt install "
                      "pulseaudio-utils, then restart)\n")
            else:
                voice_on = not voice_on
                print(f"\n(voice {'on' if voice_on else 'off'})\n")
            continue
        if command in ("/talk", "/t"):
            if recorder is None:
                print("\n(no mic recorder found — run: sudo apt install "
                      "pulseaudio-utils, then restart)\n")
                continue
            pcm = record_audio(recorder)
            if len(pcm) < speech.RECORD_RATE:  # under half a second
                print("(didn't catch anything — check your mic and try again)\n")
                continue
            heard = speech.transcribe_pcm(client, pcm, engine.thinking())
            if not heard:
                print("(couldn't make out any words — try again)\n")
                continue
            print(f"You said: {heard}")
            entry = heard
        elif command == "/reset":
            mem = remember()
            session = client.chats.create(model=engine.MODEL,
                                          config=engine.config_for(bot, mem, context))
            print("\n(conversation cleared — long-term memory kept)\n")
            print(f"{bot.name}: {persona.greeting(bot, mem)}\n")
            continue

        print(f"\n{bot.name}: ", end="", flush=True)
        reply: list[str] = []
        try:
            cfg = engine.turn_config(bot, client, mem, entry, context)
            for chunk in session.send_message_stream(entry, config=cfg):
                if chunk.text:
                    reply.append(chunk.text)
                    print(chunk.text, end="", flush=True)
        except errors.ClientError as e:
            if e.code == 429:
                print("\n\n(Free-tier rate limit hit — wait a few seconds and try again.)")
            elif e.code in (400, 401, 403) and "API key" in (e.message or ""):
                print("\n\nError: your API key was rejected. Check GEMINI_API_KEY "
                      "against https://aistudio.google.com/apikey.")
            else:
                print(f"\n\n(API error {e.code}: {e.message})")
            continue
        except errors.APIError as e:
            print(f"\n\n(API error {e.code}: {e.message})")
            continue

        print("\n")
        if voice_on and reply:
            voice_on = speak(bot, client, player, "".join(reply))


if __name__ == "__main__":
    try:
        chat(choose_bot(sys.argv))
    except Exception as exc:  # last resort, so the terminal isn't left mid-stream
        print(f"\nUnexpected error: {exc}", file=sys.stderr)
        sys.exit(1)
