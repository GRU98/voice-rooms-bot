from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from utils.helpers import reply

if TYPE_CHECKING:
    from bot import VoiceBot

log = logging.getLogger(__name__)


class AdminCog(commands.Cog):
    """Maintenance commands for server administrators."""

    def __init__(self, bot: VoiceBot) -> None:
        self.bot = bot

    voice_admin = app_commands.Group(
        name="voice_admin",
        description="Обслуживание временных комнат",
        guild_only=True,
        default_permissions=discord.Permissions(administrator=True),
    )

    @voice_admin.command(name="rooms", description="Список активных временных комнат")
    @app_commands.checks.has_permissions(administrator=True)
    async def rooms(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        rooms = await self.bot.services.rooms.list_for_guild(interaction.guild.id)
        if not rooms:
            await reply(interaction, "Активных временных комнат нет.")
            return
        lines = [f"<#{r.voice_channel_id}> — владелец <@{r.owner_id}>" for r in rooms[:40]]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @voice_admin.command(name="reconcile", description="Сверить базу данных с Discord и очистить мусор")
    @app_commands.checks.has_permissions(administrator=True)
    async def reconcile(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        await self.bot.services.voice.reconcile()
        await interaction.followup.send("✅ Сверка завершена.", ephemeral=True)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            await reply(interaction, "❌ Команда доступна только администраторам сервера.")
            return
        log.error("Unhandled admin command error", exc_info=error)
        await reply(interaction, "❌ Внутренняя ошибка.")


async def setup(bot: VoiceBot) -> None:
    await bot.add_cog(AdminCog(bot))
