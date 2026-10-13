from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DEFAULT_ROOM_NAME = "🔊・{user}'s Room"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class GuildSettings(Base):
    __tablename__ = "guild_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    trigger_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    category_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    default_user_limit: Mapped[int] = mapped_column(Integer, default=0)
    default_channel_name: Mapped[str] = mapped_column(String(100), default=DEFAULT_ROOM_NAME)
    delete_delay: Mapped[int] = mapped_column(Integer, default=5)
    auto_transfer_owner: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class TemporaryChannel(Base):
    __tablename__ = "temporary_channels"
    __table_args__ = (Index("ix_temporary_channels_guild_owner", "guild_id", "owner_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    voice_channel_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    text_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, index=True)
    category_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    panel_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BlockedUser(Base):
    __tablename__ = "blocked_users"
    __table_args__ = (
        UniqueConstraint("temporary_channel_id", "user_id", name="uq_blocked_room_user"),
        Index("ix_blocked_users_guild_user", "guild_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    temporary_channel_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("temporary_channels.id", ondelete="CASCADE"), index=True
    )
    guild_id: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
