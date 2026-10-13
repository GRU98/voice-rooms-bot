from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

from database.models import TemporaryChannel
from database.repositories import TemporaryChannelRepository
from services.permission_service import PermissionService
from utils.helpers import LockRegistry, format_room_name
from utils.permissions import is_hidden, is_locked
from views.voice_panel import RoomPanelView, build_panel_embed

log = logging.getLogger(__name__)

AUTO_CATEGORY_NAME = "🎙 TEMPORARY ROOMS"
AUTO_TRIGGER_NAME = "➕・Создать комнату"


class ChannelService:
    """Creates/deletes Discord channels and keeps the room panel message up to date."""

    def __init__(
        self, bot: commands.Bot, rooms: TemporaryChannelRepository, permissions: PermissionService
    ) -> None:
        self._bot = bot
        self._rooms = rooms
        self._permissions = permissions
        self._panel_locks = LockRegistry()
        self._refresh_tasks: dict[int, asyncio.Task[None]] = {}

    async def create_room_channel(
        self,
        member: discord.Member,
        category: discord.CategoryChannel | None,
        name_template: str,
        user_limit: int,
    ) -> discord.VoiceChannel:
        guild = member.guild
        return await guild.create_voice_channel(
            format_room_name(name_template, member),
            category=category,
            user_limit=max(0, min(user_limit, 99)),
            overwrites=self._permissions.build_overwrites(guild, member),
            reason=f"Temporary room for {member}",
        )

    async def delete_room_channels(self, guild: discord.Guild, room: TemporaryChannel) -> None:
        channel = guild.get_channel(room.voice_channel_id)
        if channel is not None:
            try:
                await channel.delete(reason="Temporary room removed")
            except discord.NotFound:
                log.debug("Channel %s already deleted", room.voice_channel_id)
        task = self._refresh_tasks.pop(room.voice_channel_id, None)
        if task is not None:
            task.cancel()
        self._panel_locks.discard(room.voice_channel_id)

    async def refresh_panel(
        self,
        room: TemporaryChannel,
        *,
        voice: discord.VoiceChannel | None = None,
        locked: bool | None = None,
        hidden: bool | None = None,
        force_new: bool = False,
    ) -> None:
        guild = self._bot.get_guild(room.guild_id)
        if guild is None:
            log.warning("Guild %s unavailable, panel not refreshed", room.guild_id)
            return
        if voice is None:
            channel = guild.get_channel(room.voice_channel_id)
            voice = channel if isinstance(channel, discord.VoiceChannel) else None
        if voice is None:
            return
        embed = build_panel_embed(
            voice=voice,
            owner_id=room.owner_id,
            locked=is_locked(voice) if locked is None else locked,
            hidden=is_hidden(voice) if hidden is None else hidden,
        )
        view = RoomPanelView(
            locked=is_locked(voice) if locked is None else locked,
            hidden=is_hidden(voice) if hidden is None else hidden,
        )
        async with self._panel_locks.get(voice.id):
            if room.panel_message_id and not force_new:
                try:
                    await voice.get_partial_message(room.panel_message_id).edit(embed=embed, view=view)
                    return
                except discord.NotFound:
                    log.info("Panel message for room %s vanished, sending a new one", voice.id)
            message = await voice.send(embed=embed, view=view)
            await self._rooms.set_panel_message(voice.id, message.id)
            room.panel_message_id = message.id

    def schedule_refresh(self, voice_channel_id: int, delay: float = 1.5) -> None:
        """Debounced refresh, used for join/leave events to avoid hitting rate limits."""
        previous = self._refresh_tasks.pop(voice_channel_id, None)
        if previous is not None:
            previous.cancel()
        task = asyncio.create_task(self._delayed_refresh(voice_channel_id, delay))
        self._refresh_tasks[voice_channel_id] = task

        def _cleanup(done: asyncio.Task[None]) -> None:
            if self._refresh_tasks.get(voice_channel_id) is done:
                self._refresh_tasks.pop(voice_channel_id, None)

        task.add_done_callback(_cleanup)

    async def _delayed_refresh(self, voice_channel_id: int, delay: float) -> None:
        await asyncio.sleep(delay)
        try:
            room = await self._rooms.get_by_voice(voice_channel_id)
            if room is not None:
                await self.refresh_panel(room)
        except discord.HTTPException:
            log.warning("Debounced panel refresh failed for %s", voice_channel_id, exc_info=True)
        except Exception:
            log.exception("Unexpected error in debounced panel refresh for %s", voice_channel_id)

    async def automatic_setup(self, guild: discord.Guild) -> tuple[discord.CategoryChannel, discord.VoiceChannel]:
        category = await guild.create_category(AUTO_CATEGORY_NAME, reason="Temporary voice automatic setup")
        trigger = await guild.create_voice_channel(
            AUTO_TRIGGER_NAME, category=category, reason="Temporary voice automatic setup"
        )
        return category, trigger
