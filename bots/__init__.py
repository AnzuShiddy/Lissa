"""The bot registry — the whole list of who lives on this platform.

Adding a bot is a folder with a `BOT` in it plus one line here. Order is the
order they appear on the landing page.
"""

from bots.athar import BOT as athar
from bots.lissa import BOT as lissa
from core.persona import Bot

REGISTRY: dict[str, Bot] = {bot.slug: bot for bot in (lissa, athar)}


def get(slug: str) -> Bot | None:
    return REGISTRY.get(slug)


def all_bots() -> list[Bot]:
    return list(REGISTRY.values())
