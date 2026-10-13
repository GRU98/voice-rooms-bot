from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

if TYPE_CHECKING:
    from bot import VoiceBot

log = logging.getLogger(__name__)


class VoiceCog(commands.Cog):
    """Gateway event listeners for the temporary voice system."""

    def __init__(self, bot: VoiceBot) -> None:
        self.bot = bot
        self._reconciled = False

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        if self._reconciled:
            return
        self._reconciled = True
        try:
            await self.bot.services.voice.reconcile()
        except Exception:
            self._reconciled = False
            log.exception("Startup reconciliation failed")

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ) -> None:
        await self.bot.services.voice.handle_voice_state(member, before, after)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        await self.bot.services.voice.handle_channel_deleted(channel)


async def setup(bot: VoiceBot) -> None:
    await bot.add_cog(VoiceCog(bot))
