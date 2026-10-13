from __future__ import annotations

import asyncio
import functools
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import discord
from sqlalchemy.exc import SQLAlchemyError

from utils.permissions import can_manage

log = logging.getLogger(__name__)

VOICE_PREFIX = "🔊・"
TEXT_PREFIX = "💬・"
MAX_BASE_NAME = 90

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


class RoomActionError(Exception):
    """User-facing error: the message is shown to the user as is."""


class LockRegistry:
    """Keyed asyncio.Lock registry (per guild / per channel)."""

    def __init__(self) -> None:
        self._locks: dict[int, asyncio.Lock] = {}

    def get(self, key: int) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = self._locks[key] = asyncio.Lock()
        return lock

    def discard(self, key: int) -> None:
        self._locks.pop(key, None)


def clean_name(raw: str) -> str:
    return re.sub(r"\s+", " ", raw).strip()[:MAX_BASE_NAME]


def split_room_name(name: str) -> str:
    return name.split("・", 1)[1] if "・" in name else name


def format_room_name(template: str, member: discord.abc.User) -> str:
    name = template.replace("{user}", getattr(member, "display_name", member.name)).strip()
    return (name or f"{VOICE_PREFIX}{member.name}")[:100]


def text_channel_name(voice_name: str) -> str:
    return f"{TEXT_PREFIX}{split_room_name(voice_name)}"[:100]


async def reply(interaction: discord.Interaction, content: str) -> None:
    try:
        if interaction.response.is_done():
            await interaction.followup.send(content, ephemeral=True)
        else:
            await interaction.response.send_message(content, ephemeral=True)
    except discord.HTTPException:
        log.warning("Could not reply to interaction %s", interaction.id, exc_info=True)


def guarded(func: F) -> F:
    """Convert exceptions raised by UI handlers into logged, user-visible ephemeral messages."""

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        interaction = next(a for a in (*args, *kwargs.values()) if isinstance(a, discord.Interaction))
        try:
            return await func(*args, **kwargs)
        except RoomActionError as exc:
            await reply(interaction, f"❌ {exc}")
        except discord.Forbidden:
            log.warning("Missing permissions in %s", func.__qualname__, exc_info=True)
            await reply(interaction, "❌ У бота недостаточно прав для этого действия.")
        except discord.NotFound:
            log.info("Discord object not found in %s", func.__qualname__, exc_info=True)
            await reply(interaction, "❌ Объект не найден (возможно, он уже удалён).")
        except discord.HTTPException:
            log.exception("Discord API error in %s", func.__qualname__)
            await reply(interaction, "❌ Ошибка Discord API. Попробуйте позже.")
        except SQLAlchemyError:
            log.exception("Database error in %s", func.__qualname__)
            await reply(interaction, "❌ Ошибка базы данных.")
        except asyncio.TimeoutError:
            log.warning("Timeout in %s", func.__qualname__)
            await reply(interaction, "❌ Discord ограничил частоту этого действия (например, переименование). Попробуйте позже.")
        return None

    return wrapper  # type: ignore[return-value]


async def resolve_room(interaction: discord.Interaction) -> tuple[Any, discord.VoiceChannel] | None:
    """Find the room bound to the interaction's channel and verify the user may manage it."""
    services = interaction.client.services  # type: ignore[attr-defined]
    guild = interaction.guild
    if guild is None or interaction.channel_id is None:
        await reply(interaction, "❌ Это действие доступно только на сервере.")
        return None
    room = await services.rooms.get_by_channel(interaction.channel_id)
    if room is None or room.guild_id != guild.id:
        await reply(interaction, "❌ Эта комната больше не существует.")
        return None
    voice = guild.get_channel(room.voice_channel_id)
    if not isinstance(voice, discord.VoiceChannel):
        await reply(interaction, "❌ Голосовой канал комнаты был удалён.")
        return None
    if not can_manage(interaction.user, room.owner_id):
        await reply(interaction, "❌ Управлять комнатой может только её владелец или администратор.")
        return None
    return room, voice
