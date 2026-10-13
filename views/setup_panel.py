from __future__ import annotations

from typing import Any

import discord
from discord import ui

from database.models import GuildSettings
from utils.helpers import RoomActionError, guarded, reply
from utils.permissions import missing_bot_permissions
from views.modals import RoomNameTemplateModal
from views.selects import PickerView, SetupChannelSelect, SetupValueSelect

LIMIT_CHOICES = [("Без лимита", 0), *[(str(v), v) for v in (1, 2, 3, 4, 5, 6, 8, 10, 15, 20, 25, 50, 99)]]
DELAY_CHOICES = [(f"{v} сек.", v) for v in (1, 3, 5, 10, 15, 30, 60, 120, 300)]


def _services(interaction: discord.Interaction) -> Any:
    return interaction.client.services  # type: ignore[attr-defined]


def build_setup_embed(guild: discord.Guild, settings: GuildSettings) -> discord.Embed:
    trigger = f"<#{settings.trigger_channel_id}>" if settings.trigger_channel_id else "не настроен"
    category = f"<#{settings.category_id}>" if settings.category_id else "не настроена"
    limit = str(settings.default_user_limit) if settings.default_user_limit else "без лимита"
    embed = discord.Embed(
        title="⚙️ TEMPORARY VOICE SETUP",
        colour=discord.Colour.green() if settings.enabled else discord.Colour.red(),
    )
    embed.add_field(name="Status", value="🟢 Enabled" if settings.enabled else "🔴 Disabled", inline=False)
    embed.add_field(name="Trigger", value=trigger, inline=True)
    embed.add_field(name="Category", value=category, inline=True)
    embed.add_field(name="Delete delay", value=f"{settings.delete_delay} seconds", inline=False)
    embed.add_field(name="Default limit", value=limit, inline=True)
    embed.add_field(name="Auto transfer", value="Enabled" if settings.auto_transfer_owner else "Disabled", inline=True)
    embed.add_field(name="Room name", value=f"`{settings.default_channel_name}`", inline=False)
    category_channel = guild.get_channel(settings.category_id) if settings.category_id else None
    missing = missing_bot_permissions(
        guild, category_channel if isinstance(category_channel, discord.CategoryChannel) else None
    )
    if missing:
        embed.add_field(name="⚠️ У бота не хватает прав", value=", ".join(f"`{m}`" for m in missing), inline=False)
    if not settings.trigger_channel_id:
        embed.set_footer(text="Выберите trigger-канал или нажмите «Automatic Setup»")
    return embed


async def show_setup(interaction: discord.Interaction) -> None:
    """Send (first call) or edit (button callbacks) the setup panel."""
    guild = interaction.guild
    assert guild is not None
    settings = await _services(interaction).settings.get_or_create(guild.id)
    embed = build_setup_embed(guild, settings)
    view = SetupView(interaction.user.id, settings)
    if interaction.type is discord.InteractionType.application_command:
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    elif interaction.response.is_done():
        await interaction.edit_original_response(embed=embed, view=view)
    else:
        await interaction.response.edit_message(embed=embed, view=view)


class SetupView(ui.View):
    def __init__(self, owner_id: int, settings: GuildSettings) -> None:
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self.toggle_enabled.label = "Disable" if settings.enabled else "Enable"
        self.toggle_enabled.emoji = "🔴" if settings.enabled else "🟢"
        self.toggle_enabled.style = discord.ButtonStyle.danger if settings.enabled else discord.ButtonStyle.success
        self.toggle_transfer.label = f"Auto Transfer: {'On' if settings.auto_transfer_owner else 'Off'}"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await reply(interaction, "❌ Это меню настройки открыто другим администратором.")
            return False
        perms = getattr(interaction.user, "guild_permissions", None)
        if perms is None or not perms.administrator:
            await reply(interaction, "❌ Нужны права администратора.")
            return False
        return True

    async def _open_picker(self, interaction: discord.Interaction, select: ui.Item[Any]) -> None:
        await interaction.response.edit_message(
            embed=None, content="Выберите значение:", view=PickerView(select, self._back, self.owner_id)
        )

    async def _back(self, interaction: discord.Interaction) -> None:
        await self._render_after_picker(interaction)

    async def _render_after_picker(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        assert guild is not None
        settings = await _services(interaction).settings.get_or_create(guild.id)
        await interaction.response.edit_message(
            content=None, embed=build_setup_embed(guild, settings), view=SetupView(self.owner_id, settings)
        )

    async def _save_and_back(self, interaction: discord.Interaction, **fields: Any) -> None:
        assert interaction.guild is not None
        await _services(interaction).settings.update(interaction.guild.id, **fields)
        await self._render_after_picker(interaction)

    @ui.button(label="Trigger", emoji="🎙", row=0)
    @guarded
    async def pick_trigger(self, interaction: discord.Interaction, button: ui.Button) -> None:
        async def on_pick(i: discord.Interaction, channel: Any) -> None:
            await self._guarded_save(i, trigger_channel_id=channel.id)

        select = SetupChannelSelect([discord.ChannelType.voice], "Выберите trigger voice-канал", on_pick)
        await self._open_picker(interaction, select)

    @ui.button(label="Category", emoji="📁", row=0)
    @guarded
    async def pick_category(self, interaction: discord.Interaction, button: ui.Button) -> None:
        async def on_pick(i: discord.Interaction, channel: Any) -> None:
            await self._guarded_save(i, category_id=channel.id)

        select = SetupChannelSelect([discord.ChannelType.category], "Выберите категорию для комнат", on_pick)
        await self._open_picker(interaction, select)

    @ui.button(label="Default Limit", emoji="👥", row=1)
    @guarded
    async def pick_limit(self, interaction: discord.Interaction, button: ui.Button) -> None:
        async def on_pick(i: discord.Interaction, value: int) -> None:
            await self._guarded_save(i, default_user_limit=value)

        await self._open_picker(interaction, SetupValueSelect(LIMIT_CHOICES, "Лимит по умолчанию", on_pick))

    @ui.button(label="Delete Delay", emoji="⏱", row=1)
    @guarded
    async def pick_delay(self, interaction: discord.Interaction, button: ui.Button) -> None:
        async def on_pick(i: discord.Interaction, value: int) -> None:
            await self._guarded_save(i, delete_delay=value)

        await self._open_picker(interaction, SetupValueSelect(DELAY_CHOICES, "Задержка удаления пустой комнаты", on_pick))

    @ui.button(label="Room Name", emoji="✏️", row=2)
    @guarded
    async def edit_name(self, interaction: discord.Interaction, button: ui.Button) -> None:
        assert interaction.guild is not None
        settings = await _services(interaction).settings.get_or_create(interaction.guild.id)

        async def on_submit(i: discord.Interaction, value: str) -> None:
            await self._guarded_save(i, default_channel_name=value[:100])

        await interaction.response.send_modal(RoomNameTemplateModal(settings.default_channel_name, on_submit))

    @ui.button(label="Auto Transfer", emoji="👑", row=2)
    @guarded
    async def toggle_transfer(self, interaction: discord.Interaction, button: ui.Button) -> None:
        assert interaction.guild is not None
        settings = await _services(interaction).settings.get_or_create(interaction.guild.id)
        await self._save_and_back(interaction, auto_transfer_owner=not settings.auto_transfer_owner)

    @ui.button(label="Enable", emoji="🟢", row=3)
    @guarded
    async def toggle_enabled(self, interaction: discord.Interaction, button: ui.Button) -> None:
        assert interaction.guild is not None
        settings = await _services(interaction).settings.get_or_create(interaction.guild.id)
        await self._save_and_back(interaction, enabled=not settings.enabled)

    @ui.button(label="Automatic Setup", emoji="⚡", style=discord.ButtonStyle.primary, row=3)
    @guarded
    async def automatic(self, interaction: discord.Interaction, button: ui.Button) -> None:
        guild = interaction.guild
        assert guild is not None
        missing = missing_bot_permissions(guild, None)
        if missing:
            raise RoomActionError("Боту не хватает прав: " + ", ".join(missing))
        await interaction.response.defer()
        services = _services(interaction)
        category, trigger = await services.channels.automatic_setup(guild)
        settings = await services.settings.update(
            guild.id, trigger_channel_id=trigger.id, category_id=category.id, enabled=True
        )
        await interaction.edit_original_response(
            content=None, embed=build_setup_embed(guild, settings), view=SetupView(self.owner_id, settings)
        )

    @guarded
    async def _guarded_save(self, interaction: discord.Interaction, **fields: Any) -> None:
        await self._save_and_back(interaction, **fields)
