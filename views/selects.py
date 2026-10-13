from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import discord
from discord import ui

from utils.helpers import RoomActionError, clean_name, guarded, reply, resolve_room, split_room_name
from utils.permissions import can_manage

LIMIT_VALUES = (0, 1, 2, 3, 4, 5, 10, 15, 20, 25)
BITRATE_VALUES_KBPS = (8, 32, 64, 96, 128, 256, 384)
MAX_OPTIONS = 25


def _services(interaction: discord.Interaction) -> Any:
    return interaction.client.services  # type: ignore[attr-defined]


def _is_targetable(member: discord.Member, owner_id: int) -> bool:
    return not member.bot and member.id != owner_id and not member.guild_permissions.administrator


# --------------------------------------------------------------------------- room: user limit


class LimitSelect(ui.Select["LimitView"]):
    def __init__(self) -> None:
        options = [
            discord.SelectOption(label="0 — Без лимита" if v == 0 else str(v), value=str(v)) for v in LIMIT_VALUES
        ]
        super().__init__(placeholder="Выберите лимит", options=options, min_values=1, max_values=1)

    @guarded
    async def callback(self, interaction: discord.Interaction) -> None:
        ctx = await resolve_room(interaction)
        if ctx is None:
            return
        room, voice = ctx
        limit = int(self.values[0])
        await interaction.response.defer()
        await _services(interaction).voice.set_limit(room, voice, limit)
        text = "Без лимита" if limit == 0 else str(limit)
        await interaction.edit_original_response(content=f"👥 Лимит установлен: {text}", view=None)


class LimitView(ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=120)
        self.add_item(LimitSelect())


# --------------------------------------------------------------------------- room: members / blocked


class TargetSelect(ui.Select["TargetActionView"]):
    def __init__(self, targets: list[tuple[int, str]], placeholder: str) -> None:
        options = [discord.SelectOption(label=label[:100], value=str(uid)) for uid, label in targets[:MAX_OPTIONS]]
        super().__init__(placeholder=placeholder, options=options, min_values=1, max_values=1, row=0)

    async def callback(self, interaction: discord.Interaction) -> None:
        assert self.view is not None
        self.view.selected_id = int(self.values[0])
        for item in self.view.children:
            if isinstance(item, ActionButton):
                item.disabled = False
        await interaction.response.edit_message(content=f"Что сделать с <@{self.view.selected_id}>?", view=self.view)


class ActionButton(ui.Button["TargetActionView"]):
    def __init__(self, kind: str, label: str, emoji: str, style: discord.ButtonStyle, custom_id: str) -> None:
        super().__init__(label=label, emoji=emoji, style=style, custom_id=custom_id, disabled=True, row=1)
        self.kind = kind

    async def callback(self, interaction: discord.Interaction) -> None:
        assert self.view is not None
        await self.view.run(interaction, self.kind)


class BlockedListButton(ui.Button["TargetActionView"]):
    def __init__(self) -> None:
        super().__init__(label="Разблокировать", emoji="🔊", style=discord.ButtonStyle.success, custom_id="voice:unblock", row=2)

    @guarded
    async def callback(self, interaction: discord.Interaction) -> None:
        ctx = await resolve_room(interaction)
        if ctx is None:
            return
        room, voice = ctx
        view = await TargetActionView.for_blocked(voice, room.id, _services(interaction))
        if view is None:
            await reply(interaction, "🔇 В этой комнате нет заблокированных пользователей.")
            return
        await interaction.response.edit_message(
            content="🔇 **Заблокированные пользователи**\n\nВыберите пользователя:", view=view
        )


class TargetActionView(ui.View):
    def __init__(self, targets: list[tuple[int, str]], *, blocked_mode: bool) -> None:
        super().__init__(timeout=120)
        self.selected_id: int | None = None
        self.has_targets = bool(targets)
        if targets:
            placeholder = "Заблокированный пользователь" if blocked_mode else "Выберите пользователя"
            self.add_item(TargetSelect(targets, placeholder))
        if blocked_mode:
            self.add_item(ActionButton("unblock", "Разблокировать", "🔊", discord.ButtonStyle.success, "voice:unblock"))
        else:
            self.add_item(ActionButton("kick", "Кикнуть", "🚫", discord.ButtonStyle.danger, "voice:kick"))
            self.add_item(ActionButton("block", "Заблокировать", "🔇", discord.ButtonStyle.danger, "voice:block"))
            self.add_item(BlockedListButton())
            if not targets:
                for item in self.children:
                    if isinstance(item, ActionButton):
                        item.disabled = True

    @classmethod
    def for_members(cls, voice: discord.VoiceChannel, owner_id: int) -> TargetActionView:
        targets = [(m.id, m.display_name) for m in voice.members if _is_targetable(m, owner_id)]
        return cls(targets, blocked_mode=False)

    @classmethod
    async def for_blocked(cls, voice: discord.VoiceChannel, room_id: int, services: Any) -> TargetActionView | None:
        user_ids: list[int] = await services.blocked.list_user_ids(room_id)
        if not user_ids:
            return None
        targets: list[tuple[int, str]] = []
        for uid in user_ids[:MAX_OPTIONS]:
            member = voice.guild.get_member(uid)
            targets.append((uid, member.display_name if member else f"ID {uid}"))
        return cls(targets, blocked_mode=True)

    @guarded
    async def run(self, interaction: discord.Interaction, kind: str) -> None:
        if self.selected_id is None:
            raise RoomActionError("Сначала выберите пользователя.")
        ctx = await resolve_room(interaction)
        if ctx is None:
            return
        room, voice = ctx
        await interaction.response.defer()
        voice_service = _services(interaction).voice
        if kind == "kick":
            result = await voice_service.kick(room, voice, self.selected_id)
        elif kind == "block":
            result = await voice_service.block(room, voice, self.selected_id)
        else:
            result = await voice_service.unblock(room, voice, self.selected_id)
        await interaction.edit_original_response(content=result, view=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        room = await _services(interaction).rooms.get_by_channel(interaction.channel_id or 0)
        if room is None or not can_manage(interaction.user, room.owner_id):
            await reply(interaction, "❌ Управлять комнатой может только её владелец или администратор.")
            return False
        return True


# --------------------------------------------------------------------------- room: ownership


class TransferSelect(ui.Select["TransferView"]):
    def __init__(self, members: list[discord.Member]) -> None:
        options = [discord.SelectOption(label=m.display_name[:100], value=str(m.id)) for m in members[:MAX_OPTIONS]]
        super().__init__(placeholder="Выберите нового владельца", options=options, min_values=1, max_values=1)

    @guarded
    async def callback(self, interaction: discord.Interaction) -> None:
        ctx = await resolve_room(interaction)
        if ctx is None:
            return
        room, voice = ctx
        target_id = int(self.values[0])
        member = next((m for m in voice.members if m.id == target_id), None)
        if member is None:
            raise RoomActionError("Пользователь уже покинул комнату.")
        await interaction.response.defer()
        await _services(interaction).ownership.transfer(voice.guild, room, member)
        await interaction.edit_original_response(content=f"👑 Новый владелец комнаты: {member.mention}", view=None)


class TransferView(ui.View):
    def __init__(self, members: list[discord.Member]) -> None:
        super().__init__(timeout=120)
        self.add_item(TransferSelect(members))

    @classmethod
    def build(cls, voice: discord.VoiceChannel, owner_id: int) -> TransferView | None:
        members = [m for m in voice.members if not m.bot and m.id != owner_id]
        return cls(members) if members else None


# --------------------------------------------------------------------------- room: settings


class BitrateSelect(ui.Select["SettingsView"]):
    def __init__(self, max_bitrate_bps: int) -> None:
        options = [
            discord.SelectOption(label=f"{kbps} kbps", value=str(kbps))
            for kbps in BITRATE_VALUES_KBPS
            if kbps * 1000 <= max_bitrate_bps
        ] or [discord.SelectOption(label="64 kbps", value="64")]
        super().__init__(placeholder="Битрейт", options=options[:MAX_OPTIONS], min_values=1, max_values=1, row=0)

    @guarded
    async def callback(self, interaction: discord.Interaction) -> None:
        ctx = await resolve_room(interaction)
        if ctx is None:
            return
        room, voice = ctx
        kbps = int(self.values[0])
        await interaction.response.defer()
        await _services(interaction).voice.set_bitrate(room, voice, kbps * 1000)
        await interaction.edit_original_response(content=f"🎚 Битрейт установлен: {kbps} kbps", view=None)


class DeleteRoomButton(ui.Button["SettingsView"]):
    def __init__(self) -> None:
        super().__init__(label="Удалить комнату", emoji="🗑", style=discord.ButtonStyle.danger, row=1)

    @guarded
    async def callback(self, interaction: discord.Interaction) -> None:
        ctx = await resolve_room(interaction)
        if ctx is None:
            return
        room, _ = ctx
        await interaction.response.defer()
        await interaction.edit_original_response(content="🗑 Комната удаляется…", view=None)
        await _services(interaction).voice.destroy_room(room)


class SavePresetButton(ui.Button["SettingsView"]):
    """Store the room's current base name as the user's personal preset for future rooms."""

    def __init__(self) -> None:
        super().__init__(label="Сохранить название", emoji="💾", style=discord.ButtonStyle.secondary, row=2)

    @guarded
    async def callback(self, interaction: discord.Interaction) -> None:
        ctx = await resolve_room(interaction)
        if ctx is None:
            return
        _, voice = ctx
        base = clean_name(split_room_name(voice.name))
        if not base:
            raise RoomActionError("Сначала задайте комнате название.")
        await interaction.response.defer()
        await _services(interaction).presets.set(interaction.guild.id, interaction.user.id, base)  # type: ignore[union-attr]
        await interaction.edit_original_response(
            content=f"💾 Сохранено. Ваши новые комнаты будут называться «🔊・{base}».", view=None
        )


class ClearPresetButton(ui.Button["SettingsView"]):
    def __init__(self) -> None:
        super().__init__(label="Сбросить шаблон", emoji="♻️", style=discord.ButtonStyle.secondary, row=2)

    @guarded
    async def callback(self, interaction: discord.Interaction) -> None:
        ctx = await resolve_room(interaction)
        if ctx is None:
            return
        await interaction.response.defer()
        removed = await _services(interaction).presets.clear(interaction.guild.id, interaction.user.id)  # type: ignore[union-attr]
        text = "♻️ Личный шаблон удалён — используется шаблон сервера." if removed else "У вас нет сохранённого шаблона."
        await interaction.edit_original_response(content=text, view=None)


class SettingsView(ui.View):
    def __init__(self, guild_bitrate_limit: int) -> None:
        super().__init__(timeout=120)
        self.add_item(BitrateSelect(guild_bitrate_limit))
        self.add_item(DeleteRoomButton())
        self.add_item(SavePresetButton())
        self.add_item(ClearPresetButton())


# --------------------------------------------------------------------------- setup pickers

PickCallback = Callable[[discord.Interaction, Any], Awaitable[None]]
BackCallback = Callable[[discord.Interaction], Awaitable[None]]


class SetupChannelSelect(ui.ChannelSelect["PickerView"]):
    def __init__(self, channel_types: list[discord.ChannelType], placeholder: str, on_pick: PickCallback) -> None:
        super().__init__(channel_types=channel_types, placeholder=placeholder, min_values=1, max_values=1)
        self._on_pick = on_pick

    async def callback(self, interaction: discord.Interaction) -> None:
        await self._on_pick(interaction, self.values[0])


class SetupValueSelect(ui.Select["PickerView"]):
    def __init__(self, options: list[tuple[str, int]], placeholder: str, on_pick: PickCallback) -> None:
        super().__init__(
            placeholder=placeholder,
            options=[discord.SelectOption(label=label, value=str(value)) for label, value in options[:MAX_OPTIONS]],
            min_values=1,
            max_values=1,
        )
        self._on_pick = on_pick

    async def callback(self, interaction: discord.Interaction) -> None:
        await self._on_pick(interaction, int(self.values[0]))


class BackButton(ui.Button["PickerView"]):
    def __init__(self, back: BackCallback) -> None:
        super().__init__(label="Назад", emoji="⬅️", style=discord.ButtonStyle.secondary, row=1)
        self._back = back

    async def callback(self, interaction: discord.Interaction) -> None:
        await self._back(interaction)


class PickerView(ui.View):
    def __init__(self, select: ui.Item[Any], back: BackCallback, owner_id: int) -> None:
        super().__init__(timeout=300)
        self.owner_id = owner_id
        self.add_item(select)
        self.add_item(BackButton(back))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await reply(interaction, "❌ Это меню настройки открыто другим администратором.")
            return False
        return True
