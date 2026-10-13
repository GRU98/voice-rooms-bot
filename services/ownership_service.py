from __future__ import annotations

import logging

import discord
from discord.ext import commands

from database.models import TemporaryChannel
from database.repositories import TemporaryChannelRepository
from services.channel_service import ChannelService
from services.permission_service import PermissionService
from utils.helpers import LockRegistry, RoomActionError

log = logging.getLogger(__name__)


class OwnershipService:
    def __init__(
        self,
        bot: commands.Bot,
        rooms: TemporaryChannelRepository,
        permissions: PermissionService,
        channels: ChannelService,
        locks: LockRegistry,
    ) -> None:
        self._bot = bot
        self._rooms = rooms
        self._permissions = permissions
        self._channels = channels
        self._locks = locks

    async def transfer(self, guild: discord.Guild, room: TemporaryChannel, new_owner: discord.Member) -> None:
        """Public entry point: takes the room lock, then refreshes the panel."""
        async with self._locks.get(room.voice_channel_id):
            fresh = await self.transfer_locked(guild, room.voice_channel_id, new_owner)
        await self._channels.refresh_panel(fresh)

    async def transfer_locked(
        self, guild: discord.Guild, voice_channel_id: int, new_owner: discord.Member
    ) -> TemporaryChannel:
        """Must be called while holding the room lock."""
        room = await self._rooms.get_by_voice(voice_channel_id)
        voice = guild.get_channel(voice_channel_id)
        if room is None or not isinstance(voice, discord.VoiceChannel):
            raise RoomActionError("Комната больше не существует.")
        if new_owner.bot:
            raise RoomActionError("Нельзя передать владение боту.")
        old_owner = await self._resolve_user(guild, room.owner_id)
        await self._permissions.transfer_owner(voice, old_owner, new_owner)
        await self._rooms.set_owner(voice_channel_id, new_owner.id)
        room.owner_id = new_owner.id
        log.info("Room %s ownership: %s -> %s", voice_channel_id, old_owner.id if old_owner else None, new_owner.id)
        return room

    async def _resolve_user(self, guild: discord.Guild, user_id: int) -> discord.abc.User | None:
        member = guild.get_member(user_id)
        if member is not None:
            return member
        try:
            return await self._bot.fetch_user(user_id)
        except discord.NotFound:
            return None
