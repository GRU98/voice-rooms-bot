from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy.exc import SQLAlchemyError

from utils.helpers import reply
from views.setup_panel import show_setup

if TYPE_CHECKING:
    from bot import VoiceBot

log = logging.getLogger(__name__)


class SetupCog(commands.Cog):
    def __init__(self, bot: VoiceBot) -> None:
        self.bot = bot

    @app_commands.command(name="setup", description="Настройка временных голосовых комнат")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_command(self, interaction: discord.Interaction) -> None:
        try:
            await show_setup(interaction)
        except SQLAlchemyError:
            log.exception("Database error in /setup")
            await reply(interaction, "❌ Ошибка базы данных.")
        except discord.HTTPException:
            log.warning("Discord API error in /setup", exc_info=True)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            await reply(interaction, "❌ Команда доступна только администраторам сервера.")
            return
        log.error("Unhandled /setup error", exc_info=error)
        await reply(interaction, "❌ Внутренняя ошибка.")


async def setup(bot: VoiceBot) -> None:
    await bot.add_cog(SetupCog(bot))
