from __future__ import annotations

import discord

OWNER_VOICE = discord.PermissionOverwrite(view_channel=True, connect=True, speak=True, stream=True)


class PermissionService:
    """All permission-overwrite manipulation lives here. Owners never get guild-wide rights."""

    def build_overwrites(
        self, guild: discord.Guild, owner: discord.abc.Snowflake
    ) -> dict[discord.abc.Snowflake, discord.PermissionOverwrite]:
        voice: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {owner: OWNER_VOICE}
        me = guild.me
        if me is not None:
            voice[me] = discord.PermissionOverwrite(
                view_channel=True,
                connect=True,
                move_members=True,
                manage_channels=True,
                send_messages=True,
                embed_links=True,
                read_message_history=True,
            )
        return voice

    async def set_locked(self, voice: discord.VoiceChannel, locked: bool) -> None:
        await self._set_default(voice, connect=False if locked else None)

    async def set_hidden(self, voice: discord.VoiceChannel, hidden: bool) -> None:
        if hidden:
            for member in voice.members:
                if member.bot:
                    continue
                overwrite = voice.overwrites_for(member)
                if overwrite.view_channel is not True:
                    overwrite.view_channel = True
                    await voice.set_permissions(member, overwrite=overwrite, reason="Room hidden")
        await self._set_default(voice, view_channel=False if hidden else None)

    async def clear_view_grant(self, voice: discord.VoiceChannel, member: discord.abc.Snowflake) -> None:
        """Remove an explicit view_channel grant left over from hiding the room."""
        overwrite = voice.overwrites_for(member)
        if overwrite.view_channel is not True:
            return
        overwrite.view_channel = None
        await voice.set_permissions(
            member, overwrite=None if overwrite.is_empty() else overwrite, reason="Left temporary room"
        )

    async def _set_default(self, voice: discord.VoiceChannel, **changes: bool | None) -> None:
        role = voice.guild.default_role
        overwrite = voice.overwrites_for(role)
        for key, value in changes.items():
            setattr(overwrite, key, value)
        await voice.set_permissions(role, overwrite=None if overwrite.is_empty() else overwrite)

    async def block(self, voice: discord.VoiceChannel, target: discord.abc.User) -> None:
        overwrite = voice.overwrites_for(target)
        overwrite.connect = False
        # A blocked user must not keep a leftover view grant that would let them see a hidden room.
        overwrite.view_channel = False
        await voice.set_permissions(target, overwrite=overwrite, reason="Blocked in temporary room")

    async def unblock(self, voice: discord.VoiceChannel, target: discord.abc.User) -> None:
        overwrite = voice.overwrites_for(target)
        overwrite.connect = None
        overwrite.view_channel = None
        await voice.set_permissions(
            target, overwrite=None if overwrite.is_empty() else overwrite, reason="Unblocked in temporary room"
        )

    async def transfer_owner(
        self,
        voice: discord.VoiceChannel,
        old_owner: discord.abc.User | None,
        new_owner: discord.Member,
    ) -> None:
        await voice.set_permissions(new_owner, overwrite=OWNER_VOICE, reason="Room ownership transferred")
        if old_owner is None or old_owner.id == new_owner.id:
            return
        old_overwrite = voice.overwrites_for(old_owner)
        old_overwrite.connect = None
        old_overwrite.speak = None
        old_overwrite.stream = None
        if not any(m.id == old_owner.id for m in voice.members):
            old_overwrite.view_channel = None
        await voice.set_permissions(
            old_owner, overwrite=None if old_overwrite.is_empty() else old_overwrite, reason="Ownership transferred"
        )
