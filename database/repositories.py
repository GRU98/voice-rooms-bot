from __future__ import annotations

from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from database.models import BlockedUser, GuildSettings, TemporaryChannel, utcnow

SessionFactory = async_sessionmaker[AsyncSession]


class GuildSettingsRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._sf = session_factory

    async def get(self, guild_id: int) -> GuildSettings | None:
        async with self._sf() as session:
            return await session.scalar(select(GuildSettings).where(GuildSettings.guild_id == guild_id))

    async def get_or_create(self, guild_id: int) -> GuildSettings:
        return await self.update(guild_id)

    async def update(self, guild_id: int, **fields: Any) -> GuildSettings:
        for attempt in range(2):
            try:
                async with self._sf() as session, session.begin():
                    row = await session.scalar(select(GuildSettings).where(GuildSettings.guild_id == guild_id))
                    if row is None:
                        row = GuildSettings(
                            guild_id=guild_id,
                            enabled=True,
                            default_user_limit=0,
                            default_channel_name="🔊・{user}'s Room",
                            delete_delay=5,
                            auto_transfer_owner=True,
                        )
                        session.add(row)
                    for key, value in fields.items():
                        setattr(row, key, value)
                    row.updated_at = utcnow()
                return row
            except IntegrityError:
                if attempt:
                    raise
        raise RuntimeError("unreachable")


class TemporaryChannelRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._sf = session_factory

    async def add(
        self,
        *,
        guild_id: int,
        voice_channel_id: int,
        text_channel_id: int | None,
        owner_id: int,
        category_id: int | None,
    ) -> TemporaryChannel:
        async with self._sf() as session, session.begin():
            row = TemporaryChannel(
                guild_id=guild_id,
                voice_channel_id=voice_channel_id,
                text_channel_id=text_channel_id,
                owner_id=owner_id,
                category_id=category_id,
            )
            session.add(row)
        return row

    async def get_by_voice(self, voice_channel_id: int) -> TemporaryChannel | None:
        async with self._sf() as session:
            return await session.scalar(
                select(TemporaryChannel).where(TemporaryChannel.voice_channel_id == voice_channel_id)
            )

    async def get_by_channel(self, channel_id: int) -> TemporaryChannel | None:
        async with self._sf() as session:
            return await session.scalar(
                select(TemporaryChannel).where(
                    or_(
                        TemporaryChannel.voice_channel_id == channel_id,
                        TemporaryChannel.text_channel_id == channel_id,
                    )
                )
            )

    async def list_by_owner(self, guild_id: int, owner_id: int) -> list[TemporaryChannel]:
        async with self._sf() as session:
            result = await session.scalars(
                select(TemporaryChannel)
                .where(TemporaryChannel.guild_id == guild_id, TemporaryChannel.owner_id == owner_id)
                .order_by(TemporaryChannel.id)
            )
            return list(result)

    async def list_all(self) -> list[TemporaryChannel]:
        async with self._sf() as session:
            return list(await session.scalars(select(TemporaryChannel).order_by(TemporaryChannel.id)))

    async def list_for_guild(self, guild_id: int) -> list[TemporaryChannel]:
        async with self._sf() as session:
            result = await session.scalars(select(TemporaryChannel).where(TemporaryChannel.guild_id == guild_id))
            return list(result)

    async def set_owner(self, voice_channel_id: int, owner_id: int) -> None:
        async with self._sf() as session, session.begin():
            row = await session.scalar(
                select(TemporaryChannel).where(TemporaryChannel.voice_channel_id == voice_channel_id)
            )
            if row is not None:
                row.owner_id = owner_id

    async def set_panel_message(self, voice_channel_id: int, message_id: int) -> None:
        async with self._sf() as session, session.begin():
            row = await session.scalar(
                select(TemporaryChannel).where(TemporaryChannel.voice_channel_id == voice_channel_id)
            )
            if row is not None:
                row.panel_message_id = message_id

    async def set_text_channel(self, voice_channel_id: int, text_channel_id: int | None) -> None:
        async with self._sf() as session, session.begin():
            row = await session.scalar(
                select(TemporaryChannel).where(TemporaryChannel.voice_channel_id == voice_channel_id)
            )
            if row is not None:
                row.text_channel_id = text_channel_id
                row.panel_message_id = None

    async def delete(self, voice_channel_id: int) -> None:
        """Delete a room together with its blocked users in one transaction."""
        async with self._sf() as session, session.begin():
            row = await session.scalar(
                select(TemporaryChannel).where(TemporaryChannel.voice_channel_id == voice_channel_id)
            )
            if row is None:
                return
            await session.execute(delete(BlockedUser).where(BlockedUser.temporary_channel_id == row.id))
            await session.delete(row)


class BlockedUserRepository:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._sf = session_factory

    async def add(self, temporary_channel_id: int, guild_id: int, user_id: int) -> None:
        try:
            async with self._sf() as session, session.begin():
                exists = await session.scalar(
                    select(BlockedUser.id).where(
                        BlockedUser.temporary_channel_id == temporary_channel_id, BlockedUser.user_id == user_id
                    )
                )
                if exists is None:
                    session.add(
                        BlockedUser(temporary_channel_id=temporary_channel_id, guild_id=guild_id, user_id=user_id)
                    )
        except IntegrityError:
            return

    async def remove(self, temporary_channel_id: int, user_id: int) -> None:
        async with self._sf() as session, session.begin():
            await session.execute(
                delete(BlockedUser).where(
                    BlockedUser.temporary_channel_id == temporary_channel_id, BlockedUser.user_id == user_id
                )
            )

    async def list_user_ids(self, temporary_channel_id: int) -> list[int]:
        async with self._sf() as session:
            result = await session.scalars(
                select(BlockedUser.user_id)
                .where(BlockedUser.temporary_channel_id == temporary_channel_id)
                .order_by(BlockedUser.id)
            )
            return list(result)
