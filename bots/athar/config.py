"""Athar's configuration — everything except the prompt texts, which live in
prompts.py so this file stays readable.
"""

from pathlib import Path

from core.persona import Bot

from bots.athar import prompts

AVATAR = (Path(__file__).parent / "avatar.svg").read_text(encoding="utf-8")

SECTIONS = {
    "context": (
        "\nWhere and when this conversation is happening:\n{items}\n"
        "Use this only when it's genuinely relevant — someone asking about a "
        "prayer they're about to pray, or about to break their fast. Don't "
        "announce the time or recite the timetable unprompted, and treat the "
        "times as calculated, not certain: local masjid times and moon "
        "sighting take precedence over any calculation.\n"
    ),
    "flavour": (
        "\nSomething that has been on your own mind today: {flavour}. Let it "
        "colour which examples and reminders you reach for first. It is a "
        "leaning, not an agenda — never steer the conversation to it, and "
        "drop it entirely the moment they need something else.\n"
    ),
    "facts": (
        "\nWhat you remember about this person from previous conversations:\n"
        "{items}\nGreet them like someone you know. Weave these in naturally, "
        "don't recite them as a list, and be especially careful with what they "
        "confided — never open with someone's sin, and never bring one up "
        "again unless they do.\n"
    ),
    "history": (
        "\n{history} Let that show in how you talk to them — someone you've "
        "known a while gets shorthand and directness, not the careful "
        "politeness of a first meeting. Never state the count or dates back "
        "to them.\n"
    ),
    "extras": (
        "\nThings they resolved to do:\n{items}\n"
        "Ask after one only if the moment invites it, and ask the way someone "
        "hoping for good news would — never as an inspection. If they've "
        "slipped, that is a moment for encouragement, not disappointment: make "
        "it easy to start again.\n"
    ),
    "threads": (
        "\nThings you were waiting to hear about:\n{items}\n"
        "In your very FIRST reply of this conversation, ask about ONE of "
        "these — pick whichever fits best and work it into your opening "
        "naturally, the way someone who actually remembered would. Just one, "
        "not a list, and if they'd rather talk about something else, drop it "
        "gracefully and don't bring it up again.\n"
    ),
}

BOT = Bot(
    slug="athar",
    name="Athar",
    tagline="Questions about Islam, answered from the Qur'an and authentic Sunnah.",
    emoji="🌙",
    system_prompt=prompts.SYSTEM_PROMPT,
    sections=SECTIONS,
    memory_prompt=prompts.MEMORY_PROMPT,
    extras_name="commitments",
    max_extras=5,
    flavours=prompts.THEMES,
    langs=("en", "ar", "sw", "fr", "pt"),
    rtl_langs=("ar",),
    time_phrases={
        "en": {"morning": "this morning", "afternoon": "this afternoon",
               "evening": "this evening", "night": "tonight"},
        "ar": {"morning": "هذا الصباح", "afternoon": "هذه الظهيرة",
               "evening": "هذا المساء", "night": "الليلة"},
        "sw": {"morning": "asubuhi hii", "afternoon": "mchana huu",
               "evening": "jioni hii", "night": "usiku huu"},
        "fr": {"morning": "ce matin", "afternoon": "cet après-midi",
               "evening": "ce soir", "night": "cette nuit"},
        "pt": {"morning": "esta manhã", "afternoon": "esta tarde",
               "evening": "esta noite", "night": "esta noite"},
    },
    greetings={
        "en": "As-salamu alaykum 🌙 I'm Athar. Ask me anything about Islam — or just tell me what's on your mind {time_phrase}.",
        "ar": "السلام عليكم 🌙 أنا أثر. اسألني ما شئت عن الإسلام — أو حدّثني عمّا يشغل بالك {time_phrase}.",
        "sw": "Assalamu alaykum 🌙 Mimi ni Athar. Niulize lolote kuhusu Uislamu — au niambie tu kinachokusumbua {time_phrase}.",
        "fr": "As-salamu alaykum 🌙 Je suis Athar. Pose-moi n'importe quelle question sur l'islam — ou dis-moi simplement ce qui te préoccupe {time_phrase}.",
        "pt": "As-salamu alaykum 🌙 Eu sou o Athar. Pergunte-me o que quiser sobre o Islã — ou apenas conte o que está na sua cabeça {time_phrase}.",
    },
    returning={
        "en": "Wa alaykum as-salam 🌙 Good to see you back. How have you been?",
        "ar": "وعليكم السلام 🌙 حمدًا لله على عودتك. كيف كانت أحوالك؟",
        "sw": "Wa alaykum salaam 🌙 Karibu tena. Umekuwaje?",
        "fr": "Wa alaykum as-salam 🌙 Content de te revoir. Comment vas-tu ?",
        "pt": "Wa alaykum as-salam 🌙 Que bom te ver de volta. Como você tem estado?",
    },
    awhile={
        "en": "Wa alaykum as-salam 🌙 It's been a while — I hope Allah has kept you well. What brings you back?",
        "ar": "وعليكم السلام 🌙 لقد غبتَ مدة — أسأل الله أن يكون قد أحسن إليك. ما الذي أعادك؟",
        "sw": "Wa alaykum salaam 🌙 Imepita muda mrefu — namuomba Mwenyezi Mungu awe amekutunza. Nini kimekurudisha?",
        "fr": "Wa alaykum as-salam 🌙 Ça fait un moment — j'espère qu'Allah t'a préservé. Qu'est-ce qui t'amène ?",
        "pt": "Wa alaykum as-salam 🌙 Faz um tempo — espero que Allah tenha cuidado de você. O que te traz de volta?",
    },
    rate_limit_msg={
        "en": "(one at a time — give me about {wait}s to catch up)",
        "ar": "(على مهلك — أمهلني نحو {wait} ثانية)",
        "sw": "(pole pole — nipe sekunde {wait} nikupate)",
        "fr": "(une à la fois — laisse-moi environ {wait}s pour suivre)",
        "pt": "(uma de cada vez — me dê uns {wait}s para acompanhar)",
    },
    daily_cap_msg={
        "en": "(I've reached today's limit — come back tomorrow, in sha' Allah 🌙)",
        "ar": "(بلغتُ حدّ اليوم — عُد غدًا إن شاء الله 🌙)",
        "sw": "(Nimefikia kikomo cha leo — rudi kesho, in sha Allah 🌙)",
        "fr": "(J'ai atteint la limite du jour — reviens demain, in sha' Allah 🌙)",
        "pt": "(Alcancei o limite de hoje — volte amanhã, in sha' Allah 🌙)",
    },
    sign_off="Fi amanillah. Come back whenever you need to.",
    tts_voice="Charon",  # calm and low — a teacher's voice, not a preacher's shout
    tts_style=(
        "Say this calmly and warmly, at an unhurried pace, like a teacher "
        "speaking to one person he cares about — never preaching or "
        "theatrical. Pronounce Arabic words and phrases correctly: "
    ),
    edge_voice="en-US-AndrewMultilingualNeural",
    edge_rate="-10%",
    speech_swaps={
        "ﷺ": " sallallahu alayhi wa sallam ",
        "ﷻ": " subhanahu wa ta'ala ",
        "﷽": " bismillahir rahmanir rahim ",
    },
    features=frozenset(("voice", "memory", "photos", "handsfree", "prayer")),
    palette={
        "dark": {
            "bg0": "#07130e", "bg1": "#0f2118",
            "accent": "#2fbf87", "accentSoft": "#7fdcb4", "accent2": "#d9b45e",
            "accentRgb": "47 191 135", "accent2Rgb": "217 180 94",
            "text": "#ecf6f0", "muted": "#8dae9e", "userEnd": "#17966a",
            "headerBg": "rgba(9, 26, 19, 0.62)",
            "panelGrad": "linear-gradient(170deg, #12291e, #0c1c15)",
            "toastBg": "rgba(14, 33, 24, 0.94)",
            "overlayBg": "rgba(4, 12, 8, 0.62)",
            "glass": "rgba(255, 255, 255, 0.05)",
            "glassStrong": "rgba(255, 255, 255, 0.08)",
            "border": "rgba(255, 255, 255, 0.09)",
            "shadow": "0 18px 50px rgba(0, 0, 0, 0.45)",
            "glow": "0.5",
        },
        "light": {
            "bg0": "#f2f8f4", "bg1": "#ffffff",
            "accent": "#12a06a", "accentSoft": "#0b7c50", "accent2": "#9b7420",
            "accentRgb": "18 160 106", "accent2Rgb": "155 116 32",
            "text": "#10241a", "muted": "#5b7568", "userEnd": "#0e7d52",
            "headerBg": "rgba(255, 255, 255, 0.8)",
            "panelGrad": "linear-gradient(170deg, #ffffff, #eef7f1)",
            "toastBg": "rgba(255, 255, 255, 0.94)",
            "overlayBg": "rgba(4, 12, 8, 0.4)",
            "glass": "rgba(16, 36, 26, 0.045)",
            "glassStrong": "rgba(16, 36, 26, 0.075)",
            "border": "rgba(16, 36, 26, 0.12)",
            "shadow": "0 18px 40px rgba(16, 36, 26, 0.14)",
            "glow": "0.28",
        },
    },
    avatar_svg=AVATAR,
    ui={
        "en": {"avatarAlt": "A lamp hanging in a mihrab arch",
               "notice": "Athar is an AI, not a scholar — it can be wrong. Check anything that matters with a person of knowledge.",
               "msgPlaceholder": "Ask {name} something…",
               "extrasLabel": "Resolved:"},
        "ar": {"avatarAlt": "مصباح معلّق في محراب",
               "notice": "أثر ذكاء اصطناعي وليس عالمًا — قد يخطئ. تحقّق مما يهمّك من أهل العلم.",
               "msgPlaceholder": "اسأل {name}…",
               "extrasLabel": "عزم على:"},
        "sw": {"avatarAlt": "Taa iliyoning'inia katika mihrabu",
               "notice": "Athar ni AI, si mwanachuoni — anaweza kukosea. Thibitisha jambo lolote muhimu kwa mwenye elimu.",
               "msgPlaceholder": "Muulize {name} kitu…",
               "extrasLabel": "Aliazimia:"},
        "fr": {"avatarAlt": "Une lampe suspendue dans un mihrab",
               "notice": "Athar est une IA, pas un savant — il peut se tromper. Vérifie tout ce qui compte auprès d'une personne de science.",
               "msgPlaceholder": "Pose une question à {name}…",
               "extrasLabel": "Décidé :"},
        "pt": {"avatarAlt": "Uma lâmpada pendurada num mihrab",
               "notice": "Athar é uma IA, não um sábio — pode errar. Confirme o que for importante com uma pessoa de conhecimento.",
               "msgPlaceholder": "Pergunte algo ao {name}…",
               "extrasLabel": "Decidiu:"},
    },
)
