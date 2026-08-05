"""Somo's configuration — everything except the prompt texts, which live in
prompts.py so this file stays readable.
"""

from pathlib import Path

from core.persona import Bot

from bots.somo import prompts

AVATAR = (Path(__file__).parent / "avatar.svg").read_text(encoding="utf-8")

SECTIONS = {
    "context": (
        "\nWhat you can ground on:\n{items}\n"
    ),
    "flavour": (
        "\nSomething you've been chewing on today: {flavour}. Let it colour "
        "which angle you reach for first. It is a leaning, not a lesson plan "
        "— never steer a student towards it, and drop it the moment they need "
        "something else.\n"
    ),
    "facts": (
        "\nWhat you remember about this student from previous sessions:\n"
        "{items}\nUse it so they don't have to introduce themselves again — "
        "if you already know their form and subjects, don't ask. Weave it in "
        "naturally rather than reciting it, and never read their weak spots "
        "back to them as a list.\n"
    ),
    "history": (
        "\n{history} Let that show in how you talk to them — a student you've "
        "worked with for weeks gets shorthand and directness. Never state the "
        "count or dates back to them.\n"
    ),
    "extras": (
        "\nWhere this student got stuck before:\n{items}\n"
        "Slip a check on one of these into the session when it fits what "
        "they're already doing — a question that would reveal whether it has "
        "landed, not an announcement that you are testing them. If they've "
        "got it now, say so; being told you've improved is the thing that "
        "keeps a student coming back.\n"
    ),
    "threads": (
        "\nThings you were waiting to hear about:\n{items}\n"
        "In your very FIRST reply of this session, ask about ONE of these — "
        "whichever fits best, worked into your opening the way someone who "
        "actually remembered would. Just one, not a list, and if they'd "
        "rather work on something else, drop it and don't raise it again.\n"
    ),
}

BOT = Bot(
    slug="somo",
    name="Somo",
    tagline="A study partner for the Tanzanian secondary syllabus, Form One to Four.",
    emoji="📘",
    system_prompt=prompts.SYSTEM_PROMPT,
    sections=SECTIONS,
    memory_prompt=prompts.MEMORY_PROMPT,
    extras_name="sticking points",
    max_extras=6,
    flavours=prompts.THEMES,
    # English and Kiswahili only: this syllabus belongs to one country, and
    # offering a UI in languages its students don't sit exams in would be
    # decoration rather than reach.
    langs=("en", "sw"),
    time_phrases={
        "en": {"morning": "this morning", "afternoon": "this afternoon",
               "evening": "this evening", "night": "tonight"},
        "sw": {"morning": "asubuhi hii", "afternoon": "mchana huu",
               "evening": "jioni hii", "night": "usiku huu"},
    },
    greetings={
        "en": "Habari 📘 I'm Somo. What are we working on {time_phrase}? Tell me the subject and which form you're in, and we'll start where you're stuck.",
        "sw": "Habari 📘 Mimi ni Somo. Tunasoma nini {time_phrase}? Niambie somo na uko kidato cha ngapi, tuanze pale unapokwama.",
    },
    returning={
        "en": "Habari tena 📘 Good to see you back. What are we working on today?",
        "sw": "Habari tena 📘 Karibu tena. Leo tunafanyia nini kazi?",
    },
    awhile={
        "en": "Habari 📘 It's been a while — hope school's been kind. Still the same form, or have you moved up?",
        "sw": "Habari 📘 Imepita muda — natumai shule imekuwa sawa. Bado kidato kile kile, au umepanda?",
    },
    rate_limit_msg={
        "en": "(give me about {wait}s — I'm still writing)",
        "sw": "(nipe sekunde {wait} hivi — bado naandika)",
    },
    daily_cap_msg={
        "en": "(I've hit today's limit — come back tomorrow and we'll carry on 📘)",
        "sw": "(Nimefikia kikomo cha leo — rudi kesho tuendelee 📘)",
    },
    sign_off="Soma kwa bidii. Come back when you're stuck on the next one.",
    tts_voice="Puck",  # bright and quick — a peer explaining, not a lecturer
    tts_style=(
        "Say this clearly and encouragingly, at a steady pace, like an older "
        "sibling explaining something to a student who is trying. Read any "
        "formula slowly and separate the steps: "
    ),
    edge_voice="en-US-AndrewMultilingualNeural",
    edge_rate="-6%",
    features=frozenset(("voice", "memory", "photos", "handsfree", "syllabus")),
    palette={
        "dark": {
            "bg0": "#080d1c", "bg1": "#131a30",
            "accent": "#5b8def", "accentSoft": "#9dbcf7", "accent2": "#f2b544",
            "accentRgb": "91 141 239", "accent2Rgb": "242 181 68",
            "text": "#eef1f8", "muted": "#93a0bd", "userEnd": "#3a6fd0",
            "headerBg": "rgba(11, 17, 36, 0.62)",
            "panelGrad": "linear-gradient(170deg, #172041, #0d1428)",
            "toastBg": "rgba(16, 23, 46, 0.94)",
            "overlayBg": "rgba(4, 7, 16, 0.62)",
            "glass": "rgba(255, 255, 255, 0.05)",
            "glassStrong": "rgba(255, 255, 255, 0.08)",
            "border": "rgba(255, 255, 255, 0.09)",
            "shadow": "0 18px 50px rgba(0, 0, 0, 0.45)",
            "glow": "0.5",
        },
        "light": {
            "bg0": "#f3f6fc", "bg1": "#ffffff",
            "accent": "#2f5fc4", "accentSoft": "#23499b", "accent2": "#a9760d",
            "accentRgb": "47 95 196", "accent2Rgb": "169 118 13",
            "text": "#131a2c", "muted": "#5c6a86", "userEnd": "#2b58bb",
            "headerBg": "rgba(255, 255, 255, 0.8)",
            "panelGrad": "linear-gradient(170deg, #ffffff, #eef2fb)",
            "toastBg": "rgba(255, 255, 255, 0.94)",
            "overlayBg": "rgba(4, 7, 16, 0.4)",
            "glass": "rgba(19, 26, 44, 0.045)",
            "glassStrong": "rgba(19, 26, 44, 0.075)",
            "border": "rgba(19, 26, 44, 0.12)",
            "shadow": "0 18px 40px rgba(19, 26, 44, 0.14)",
            "glow": "0.28",
        },
    },
    avatar_svg=AVATAR,
    ui={
        "en": {"avatarAlt": "An open book with a question mark rising from it",
               "notice": "Somo is an AI, not a teacher — it can be wrong. Your teacher and your textbook come first.",
               "msgPlaceholder": "Ask {name} something…",
               "extrasLabel": "Stuck on:"},
        "sw": {"avatarAlt": "Kitabu kilichofunguliwa na alama ya swali juu yake",
               "notice": "Somo ni AI, si mwalimu — inaweza kukosea. Mwalimu wako na kitabu chako ndio vya kwanza.",
               "msgPlaceholder": "Muulize {name} kitu…",
               "extrasLabel": "Unakwama:"},
    },
)
