from __future__ import annotations

import discord

REQUIRED_BOT_PERMISSIONS: tuple[str, ...] = (
    "view_channel",
    "manage_channels",
    "manage_roles",
    "connect",
    "move_members",
    "send_messages",
    "embed_links",
    "read_message_history",
)


def missing_bot_permissions(guild: discord.Guild, category: discord.CategoryChannel | None) -> list[str]:
    me = guild.me
    if me is None:
        return list(REQUIRED_BOT_PERMISSIONS)
    perms = category.permissions_for(me) if category is not None else me.guild_permissions
    return [name for name in REQUIRED_BOT_PERMISSIONS if not getattr(perms, name)]


def can_manage(member: discord.abc.User, owner_id: int) -> bool:
    if member.id == owner_id:
        return True
    return isinstance(member, discord.Member) and member.guild_permissions.administrator


def is_locked(voice: discord.VoiceChannel) -> bool:
    return voice.overwrites_for(voice.guild.default_role).connect is False


def is_hidden(voice: discord.VoiceChannel) -> bool:
    return voice.overwrites_for(voice.guild.default_role).view_channel is False
