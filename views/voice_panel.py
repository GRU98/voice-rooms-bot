from __future__ import annotations

from collections.abc import Awaitable, Callable

import discord
from discord import ui

from utils.helpers import guarded, resolve_room, split_room_name
from views.modals import RenameModal
from views.selects import LimitView, SettingsView, TargetActionView, TransferView

Handler = Callable[[discord.Interaction], Awaitable[None]]

SEPARATOR = "━" * 20


def build_panel_embed(
    *,
    voice: discord.VoiceChannel,
    owner_id: int,
    locked: bool,
    hidden: bool,
) -> discord.Embed:
    members = len([m for m in voice.members if not m.bot])
    limit = str(voice.user_limit) if voice.user_limit else "∞"
    description = (
        f"{SEPARATOR}\n\n"
        f"🏠 **Комната:**\n{voice.mention}\n\n"
        f"👑 **Владелец:**\n<@{owner_id}>\n\n"
        f"👥 **Участники:**\n{members} / {limit}\n\n"
        f"{'🔒' if locked else '🔓'} **Доступ:**\n{'Закрыт' if locked else 'Открыт'}\n\n"
        f"👁 **Видимость:**\n{'Скрыта' if hidden else 'Видима'}\n\n"
        f"{SEPARATOR}\n\n**УПРАВЛЕНИЕ КОМНАТОЙ**"
    )
    embed = discord.Embed(title="🎙️ VOICE ROOM", description=description, colour=discord.Colour.blurple())
    embed.set_footer(text="Панель обновляется автоматически")
    return embed


class PanelButton(ui.Button["RoomPanelView"]):
    def __init__(
        self,
        *,
        label: str,
        emoji: str,
        custom_id: str,
        handler: Handler,
        row: int,
        style: discord.ButtonStyle = discord.ButtonStyle.secondary,
    ) -> None:
        super().__init__(label=label, emoji=emoji, custom_id=custom_id, style=style, row=row)
        self._handler = handler

    async def callback(self, interaction: discord.Interaction) -> None:
        await self._handler(interaction)


@guarded
async def _set_locked(interaction: discord.Interaction, locked: bool) -> None:
    ctx = await resolve_room(interaction)
    if ctx is None:
        return
    room, voice = ctx
    await interaction.response.defer(ephemeral=True)
    await interaction.client.services.voice.set_locked(room, voice, locked)  # type: ignore[attr-defined]
    await interaction.followup.send(
        "🔒 Комната закрыта\n\nНовые пользователи больше не могут подключаться." if locked else "🔓 Комната открыта",
        ephemeral=True,
    )


@guarded
async def _set_hidden(interaction: discord.Interaction, hidden: bool) -> None:
    ctx = await resolve_room(interaction)
    if ctx is None:
        return
    room, voice = ctx
    await interaction.response.defer(ephemeral=True)
    await interaction.client.services.voice.set_hidden(room, voice, hidden)  # type: ignore[attr-defined]
    await interaction.followup.send("👁 Комната скрыта" if hidden else "👀 Комната снова видна", ephemeral=True)


async def on_lock(interaction: discord.Interaction) -> None:
    await _set_locked(interaction, True)


async def on_unlock(interaction: discord.Interaction) -> None:
    await _set_locked(interaction, False)


async def on_hide(interaction: discord.Interaction) -> None:
    await _set_hidden(interaction, True)


async def on_show(interaction: discord.Interaction) -> None:
    await _set_hidden(interaction, False)


@guarded
async def on_rename(interaction: discord.Interaction) -> None:
    ctx = await resolve_room(interaction)
    if ctx is None:
        return
    _, voice = ctx
    await interaction.response.send_modal(RenameModal(split_room_name(voice.name)))


@guarded
async def on_limit(interaction: discord.Interaction) -> None:
    ctx = await resolve_room(interaction)
    if ctx is None:
        return
    await interaction.response.send_message("👥 Выберите лимит:", view=LimitView(), ephemeral=True)


@guarded
async def on_members(interaction: discord.Interaction) -> None:
    ctx = await resolve_room(interaction)
    if ctx is None:
        return
    room, voice = ctx
    view = TargetActionView.for_members(voice, room.owner_id)
    if view.has_targets:
        content = "👥 **Участники комнаты**\n\nВыберите пользователя:"
    else:
        content = "👥 В комнате нет других участников, которыми можно управлять."
    await interaction.response.send_message(content, view=view, ephemeral=True)


@guarded
async def on_transfer(interaction: discord.Interaction) -> None:
    ctx = await resolve_room(interaction)
    if ctx is None:
        return
    room, voice = ctx
    view = TransferView.build(voice, room.owner_id)
    if view is None:
        await interaction.response.send_message("👑 В комнате нет других участников для передачи прав.", ephemeral=True)
        return
    await interaction.response.send_message("👑 Выберите нового владельца:", view=view, ephemeral=True)


@guarded
async def on_resend(interaction: discord.Interaction) -> None:
    ctx = await resolve_room(interaction)
    if ctx is None:
        return
    room, voice = ctx
    await interaction.response.defer(ephemeral=True)
    await interaction.client.services.voice.resend_panel(room, voice)  # type: ignore[attr-defined]
    await interaction.followup.send("📩 Панель отправлена заново вниз чата.", ephemeral=True)


@guarded
async def on_settings(interaction: discord.Interaction) -> None:
    ctx = await resolve_room(interaction)
    if ctx is None:
        return
    await interaction.response.send_message(
        "⚙️ **Настройки комнаты**", view=SettingsView(interaction.guild.bitrate_limit), ephemeral=True  # type: ignore[union-attr]
    )


class RoomPanelView(ui.View):
    """Persistent panel view.

    With ``locked``/``hidden`` set, it renders the toggle buttons for that state. With ``None`` (used for
    registration on startup) it contains every custom_id so any stored panel message can be dispatched.
    """

    def __init__(self, *, locked: bool | None = None, hidden: bool | None = None) -> None:
        super().__init__(timeout=None)
        if locked is not True:
            self.add_item(PanelButton(label="Закрыть", emoji="🔒", custom_id="voice:lock", handler=on_lock, row=0))
        if locked is not False:
            self.add_item(
                PanelButton(
                    label="Открыть", emoji="🔓", custom_id="voice:unlock", handler=on_unlock, row=0,
                    style=discord.ButtonStyle.success,
                )
            )
        if hidden is not True:
            self.add_item(PanelButton(label="Скрыть", emoji="👁", custom_id="voice:hide", handler=on_hide, row=0))
        if hidden is not False:
            self.add_item(
                PanelButton(
                    label="Показать", emoji="👀", custom_id="voice:show", handler=on_show, row=0,
                    style=discord.ButtonStyle.success,
                )
            )
        self.add_item(PanelButton(label="Название", emoji="✏️", custom_id="voice:rename", handler=on_rename, row=1))
        self.add_item(PanelButton(label="Лимит", emoji="👥", custom_id="voice:limit", handler=on_limit, row=1))
        self.add_item(PanelButton(label="Владелец", emoji="👑", custom_id="voice:transfer", handler=on_transfer, row=2))
        self.add_item(PanelButton(label="Участники", emoji="👤", custom_id="voice:members", handler=on_members, row=2))
        self.add_item(PanelButton(label="Настройки", emoji="⚙️", custom_id="voice:settings", handler=on_settings, row=3))
        self.add_item(PanelButton(label="Панель вниз", emoji="📩", custom_id="voice:resend", handler=on_resend, row=3))
