from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

import discord
from discord import ui

from utils.helpers import MAX_BASE_NAME, RoomActionError, clean_name, guarded, reply, resolve_room

log = logging.getLogger(__name__)


class RenameModal(ui.Modal, title="Изменение названия комнаты"):
    def __init__(self, current: str) -> None:
        super().__init__(timeout=300)
        self.name = ui.TextInput(
            label="Новое название",
            placeholder="Например: Gaming Room",
            default=current[:MAX_BASE_NAME],
            min_length=1,
            max_length=MAX_BASE_NAME,
        )
        self.add_item(self.name)

    @guarded
    async def on_submit(self, interaction: discord.Interaction) -> None:
        new_name = clean_name(self.name.value)
        if not new_name:
            raise RoomActionError("Название не может быть пустым.")
        ctx = await resolve_room(interaction)
        if ctx is None:
            return
        room, voice = ctx
        await interaction.response.defer(ephemeral=True)
        updated = await interaction.client.services.voice.rename(room, voice, new_name)  # type: ignore[attr-defined]
        await interaction.followup.send(f"✏️ Название изменено: {updated}", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        log.error("Unhandled error in RenameModal", exc_info=error)
        await reply(interaction, "❌ Не удалось изменить название.")


class RoomNameTemplateModal(ui.Modal, title="Шаблон названия комнаты"):
    def __init__(self, current: str, on_submit_cb: Callable[[discord.Interaction, str], Awaitable[None]]) -> None:
        super().__init__(timeout=300)
        self.template = ui.TextInput(
            label="Шаблон ({user} = ник владельца)", default=current[:90], min_length=1, max_length=90
        )
        self.add_item(self.template)
        self._cb = on_submit_cb

    async def on_submit(self, interaction: discord.Interaction) -> None:
        value = self.template.value.strip()
        if not value:
            await reply(interaction, "❌ Шаблон не может быть пустым.")
            return
        await self._cb(interaction, value)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        log.error("Unhandled error in RoomNameTemplateModal", exc_info=error)
        await reply(interaction, "❌ Не удалось сохранить шаблон.")
