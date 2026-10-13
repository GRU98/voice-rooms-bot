from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands
from sqlalchemy.exc import SQLAlchemyError

from database.models import GuildSettings, TemporaryChannel
from database.repositories import BlockedUserRepository, GuildSettingsRepository, TemporaryChannelRepository
from services.channel_service import ChannelService
from services.ownership_service import OwnershipService
from services.permission_service import PermissionService
from utils.helpers import VOICE_PREFIX, LockRegistry, RoomActionError
from utils.permissions import missing_bot_permissions

log = logging.getLogger(__name__)

RENAME_TIMEOUT = 15.0
DEFAULT_DELETE_DELAY = 5


def _humans(voice: discord.VoiceChannel) -> list[discord.Member]:
    return [m for m in voice.members if not m.bot]


class VoiceService:
    """Temporary room lifecycle (create / join / leave / delete / reconcile) and owner actions."""

    def __init__(
        self,
        bot: commands.Bot,
        settings: GuildSettingsRepository,
        rooms: TemporaryChannelRepository,
        blocked: BlockedUserRepository,
        permissions: PermissionService,
        channels: ChannelService,
        ownership: OwnershipService,
        room_locks: LockRegistry,
    ) -> None:
        self._bot = bot
        self._settings = settings
        self._rooms = rooms
        self._blocked = blocked
        self._permissions = permissions
        self._channels = channels
        self._ownership = ownership
        self._room_locks = room_locks
        self._guild_locks = LockRegistry()
        self._delete_tasks: dict[int, asyncio.Task[None]] = {}

    # ------------------------------------------------------------------ voice events

    async def handle_voice_state(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ) -> None:
        if member.bot:
            return
        left, joined = before.channel, after.channel
        if left is not None and joined is not None and left.id == joined.id:
            return
        try:
            if left is not None:
                await self._on_leave(member, left)
            if joined is not None:
                await self._on_join(member, joined)
        except discord.HTTPException:
            log.warning("Discord API error handling voice update for %s", member.id, exc_info=True)
        except SQLAlchemyError:
            log.exception("Database error handling voice update for %s", member.id)

    async def _on_join(self, member: discord.Member, channel: discord.abc.GuildChannel) -> None:
        room = await self._rooms.get_by_voice(channel.id)
        if room is not None:
            await self._room_joined(room.voice_channel_id)
            return
        settings = await self._settings.get(member.guild.id)
        if settings and settings.enabled and settings.trigger_channel_id == channel.id:
            await self._create_for(member, settings, channel)

    async def _room_joined(self, voice_id: int) -> None:
        async with self._room_locks.get(voice_id):
            if await self._rooms.get_by_voice(voice_id) is None:
                return
            self._cancel_delete(voice_id)
        self._channels.schedule_refresh(voice_id)

    async def _on_leave(self, member: discord.Member, channel: discord.abc.GuildChannel) -> None:
        if await self._rooms.get_by_voice(channel.id) is None:
            return
        refresh = False
        async with self._room_locks.get(channel.id):
            room = await self._rooms.get_by_voice(channel.id)
            if room is None or not isinstance(channel, discord.VoiceChannel):
                return
            remaining = _humans(channel)
            settings = await self._settings.get(room.guild_id)
            if not remaining:
                delay = settings.delete_delay if settings else DEFAULT_DELETE_DELAY
                self._schedule_delete(channel.id, delay)
            elif room.owner_id == member.id and (settings is None or settings.auto_transfer_owner):
                await self._ownership.transfer_locked(member.guild, channel.id, remaining[0])
            refresh = True
        if refresh:
            self._channels.schedule_refresh(channel.id)

    # ------------------------------------------------------------------ creation

    async def _create_for(
        self, member: discord.Member, settings: GuildSettings, trigger: discord.abc.GuildChannel
    ) -> None:
        guild = member.guild
        async with self._guild_locks.get(guild.id):
            if member.voice is None or member.voice.channel is None or member.voice.channel.id != trigger.id:
                return
            for existing in await self._rooms.list_by_owner(guild.id, member.id):
                voice = guild.get_channel(existing.voice_channel_id)
                if isinstance(voice, discord.VoiceChannel):
                    await member.move_to(voice, reason="Owner already has a temporary room")
                    return
                await self._rooms.delete(existing.voice_channel_id)

            category = guild.get_channel(settings.category_id) if settings.category_id else None
            if not isinstance(category, discord.CategoryChannel):
                if settings.category_id:
                    log.warning("Guild %s: configured category %s is missing", guild.id, settings.category_id)
                category = trigger.category
            missing = missing_bot_permissions(guild, category)
            if missing:
                log.warning("Guild %s: bot lacks permissions %s, room not created", guild.id, ", ".join(missing))
                return

            voice = await self._channels.create_room_channel(
                member, category, settings.default_channel_name, settings.default_user_limit
            )
            try:
                room = await self._rooms.add(
                    guild_id=guild.id,
                    voice_channel_id=voice.id,
                    text_channel_id=None,
                    owner_id=member.id,
                    category_id=category.id if category else None,
                )
            except SQLAlchemyError:
                log.exception("Could not persist room %s, rolling back channel", voice.id)
                await voice.delete(reason="Rollback")
                raise
            try:
                await member.move_to(voice, reason="Temporary room created")
            except discord.HTTPException:
                log.info("Could not move %s into new room %s (user left?)", member.id, voice.id)
                self._schedule_delete(voice.id, settings.delete_delay)
            await self._channels.refresh_panel(room, voice=voice, locked=False, hidden=False, force_new=True)
        log.info("Guild %s: created room %s for %s", guild.id, voice.id, member.id)

    # ------------------------------------------------------------------ deletion

    def _schedule_delete(self, voice_id: int, delay: int) -> None:
        self._cancel_delete(voice_id)
        task = asyncio.create_task(self._delete_after(voice_id, delay), name=f"delete-room-{voice_id}")
        self._delete_tasks[voice_id] = task

        def _cleanup(done: asyncio.Task[None]) -> None:
            if self._delete_tasks.get(voice_id) is done:
                self._delete_tasks.pop(voice_id, None)

        task.add_done_callback(_cleanup)

    def _cancel_delete(self, voice_id: int) -> None:
        task = self._delete_tasks.pop(voice_id, None)
        if task is not None and task is not asyncio.current_task():
            task.cancel()

    async def _delete_after(self, voice_id: int, delay: int) -> None:
        try:
            await asyncio.sleep(delay)
            async with self._room_locks.get(voice_id):
                room = await self._rooms.get_by_voice(voice_id)
                if room is None:
                    return
                guild = self._bot.get_guild(room.guild_id)
                if guild is None:
                    log.warning("Guild %s unavailable, deletion of room %s postponed", room.guild_id, voice_id)
                    return
                voice = guild.get_channel(voice_id)
                if isinstance(voice, discord.VoiceChannel) and _humans(voice):
                    return
                await self._destroy_locked(room, guild)
                log.info("Guild %s: deleted empty room %s", guild.id, voice_id)
        except discord.HTTPException:
            log.warning("Discord API error deleting room %s", voice_id, exc_info=True)
        except SQLAlchemyError:
            log.exception("Database error deleting room %s", voice_id)

    async def _destroy_locked(self, room: TemporaryChannel, guild: discord.Guild) -> None:
        self._cancel_delete(room.voice_channel_id)
        await self._channels.delete_room_channels(guild, room)
        await self._rooms.delete(room.voice_channel_id)
        self._room_locks.discard(room.voice_channel_id)

    async def destroy_room(self, room: TemporaryChannel) -> None:
        guild = self._bot.get_guild(room.guild_id)
        if guild is None:
            raise RoomActionError("Сервер недоступен.")
        async with self._room_locks.get(room.voice_channel_id):
            fresh = await self._rooms.get_by_voice(room.voice_channel_id)
            if fresh is not None:
                await self._destroy_locked(fresh, guild)

    async def handle_channel_deleted(self, channel: discord.abc.GuildChannel) -> None:
        try:
            room = await self._rooms.get_by_channel(channel.id)
            if room is None:
                await self._forget_config_channel(channel)
                return
            async with self._room_locks.get(room.voice_channel_id):
                fresh = await self._rooms.get_by_voice(room.voice_channel_id)
                if fresh is None:
                    return
                await self._destroy_locked(fresh, channel.guild)
                log.info("Room %s removed: voice channel deleted manually", channel.id)
        except discord.HTTPException:
            log.warning("Discord API error handling deleted channel %s", channel.id, exc_info=True)
        except SQLAlchemyError:
            log.exception("Database error handling deleted channel %s", channel.id)

    async def _forget_config_channel(self, channel: discord.abc.GuildChannel) -> None:
        settings = await self._settings.get(channel.guild.id)
        if settings is None:
            return
        if settings.trigger_channel_id == channel.id:
            await self._settings.update(channel.guild.id, trigger_channel_id=None)
            log.info("Guild %s: trigger channel deleted, setting cleared", channel.guild.id)
        elif settings.category_id == channel.id:
            await self._settings.update(channel.guild.id, category_id=None)
            log.info("Guild %s: category deleted, setting cleared", channel.guild.id)

    # ------------------------------------------------------------------ reconciliation

    async def reconcile(self) -> None:
        rooms = await self._rooms.list_all()
        log.info("Reconciling %d stored temporary rooms", len(rooms))
        for room in rooms:
            try:
                await self._reconcile_room(room)
            except discord.HTTPException:
                log.warning("Reconcile failed for room %s", room.voice_channel_id, exc_info=True)
            except SQLAlchemyError:
                log.exception("Database error reconciling room %s", room.voice_channel_id)

    async def _reconcile_room(self, room: TemporaryChannel) -> None:
        guild = self._bot.get_guild(room.guild_id)
        if guild is None:
            log.warning("Guild %s unavailable, room %s left untouched", room.guild_id, room.voice_channel_id)
            return
        async with self._room_locks.get(room.voice_channel_id):
            fresh = await self._rooms.get_by_voice(room.voice_channel_id)
            if fresh is None:
                return
            voice = guild.get_channel(fresh.voice_channel_id)
            if not isinstance(voice, discord.VoiceChannel):
                log.info("Stale record for room %s removed", fresh.voice_channel_id)
                await self._destroy_locked(fresh, guild)
                return
            settings = await self._settings.get(fresh.guild_id)
            humans = _humans(voice)
            if not humans:
                self._schedule_delete(voice.id, settings.delete_delay if settings else DEFAULT_DELETE_DELAY)
                return
            if fresh.owner_id not in {m.id for m in humans} and (settings is None or settings.auto_transfer_owner):
                await self._ownership.transfer_locked(guild, voice.id, humans[0])
        await self._channels.refresh_panel(fresh, voice=voice)

    # ------------------------------------------------------------------ owner actions

    async def set_locked(self, room: TemporaryChannel, voice: discord.VoiceChannel, locked: bool) -> None:
        async with self._room_locks.get(voice.id):
            await self._permissions.set_locked(voice, locked)
        await self._channels.refresh_panel(room, voice=voice, locked=locked)

    async def set_hidden(self, room: TemporaryChannel, voice: discord.VoiceChannel, hidden: bool) -> None:
        async with self._room_locks.get(voice.id):
            await self._permissions.set_hidden(voice, hidden)
        await self._channels.refresh_panel(room, voice=voice, hidden=hidden)

    async def set_limit(self, room: TemporaryChannel, voice: discord.VoiceChannel, limit: int) -> None:
        async with self._room_locks.get(voice.id):
            updated = await voice.edit(user_limit=max(0, min(limit, 99)), reason="Room limit changed")
        await self._channels.refresh_panel(room, voice=updated or voice)

    async def set_bitrate(self, room: TemporaryChannel, voice: discord.VoiceChannel, bitrate: int) -> None:
        async with self._room_locks.get(voice.id):
            updated = await voice.edit(bitrate=bitrate, reason="Room bitrate changed")
        await self._channels.refresh_panel(room, voice=updated or voice)

    async def rename(self, room: TemporaryChannel, voice: discord.VoiceChannel, base_name: str) -> str:
        new_name = f"{VOICE_PREFIX}{base_name}"
        async with self._room_locks.get(voice.id):
            updated = await asyncio.wait_for(voice.edit(name=new_name, reason="Room renamed"), RENAME_TIMEOUT)
            current = updated or voice
        await self._channels.refresh_panel(room, voice=current)
        return current.name

    async def kick(self, room: TemporaryChannel, voice: discord.VoiceChannel, target_id: int) -> str:
        async with self._room_locks.get(voice.id):
            member = next((m for m in voice.members if m.id == target_id), None)
            if member is None:
                raise RoomActionError("Пользователь уже покинул комнату.")
            self._ensure_targetable(room, member)
            await member.move_to(None, reason="Kicked from temporary room")
        return f"🚫 {member.mention} был отключён от комнаты."

    async def block(self, room: TemporaryChannel, voice: discord.VoiceChannel, target_id: int) -> str:
        async with self._room_locks.get(voice.id):
            target = await self._resolve_user(voice.guild, target_id)
            if target is None:
                raise RoomActionError("Пользователь не найден.")
            self._ensure_targetable(room, target)
            await self._blocked.add(room.id, room.guild_id, target.id)
            try:
                await self._permissions.block(voice, target)
            except discord.HTTPException:
                await self._blocked.remove(room.id, target.id)
                raise
            member = next((m for m in voice.members if m.id == target.id), None)
            if member is not None:
                try:
                    await member.move_to(None, reason="Blocked in temporary room")
                except discord.HTTPException:
                    log.info("Blocked user %s left before being disconnected", target.id)
        return f"🔇 {target.mention} заблокирован и больше не сможет подключиться к комнате."

    async def unblock(self, room: TemporaryChannel, voice: discord.VoiceChannel, target_id: int) -> str:
        async with self._room_locks.get(voice.id):
            target = await self._resolve_user(voice.guild, target_id)
            if target is not None:
                await self._permissions.unblock(voice, target)
            await self._blocked.remove(room.id, target_id)
        return f"🔊 <@{target_id}> разблокирован."

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _ensure_targetable(room: TemporaryChannel, target: discord.abc.User) -> None:
        if target.id == room.owner_id:
            raise RoomActionError("Нельзя применить это действие к владельцу комнаты.")
        if isinstance(target, discord.Member) and target.guild_permissions.administrator:
            raise RoomActionError("Нельзя применить это действие к администратору сервера.")

    async def _resolve_user(self, guild: discord.Guild, user_id: int) -> discord.abc.User | None:
        member = guild.get_member(user_id)
        if member is not None:
            return member
        try:
            return await self._bot.fetch_user(user_id)
        except discord.NotFound:
            return None
