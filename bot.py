from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import discord
from aiohttp import web
from discord.ext import commands

from config import Config, load_config
from database.engine import Database
from database.migrations import run_migrations
from database.repositories import BlockedUserRepository, GuildSettingsRepository, TemporaryChannelRepository
from services.channel_service import ChannelService
from services.ownership_service import OwnershipService
from services.permission_service import PermissionService
from services.voice_service import VoiceService
from utils.helpers import LockRegistry
from utils.logging import setup_logging
from views.voice_panel import RoomPanelView

log = logging.getLogger("voice_bot")

EXTENSIONS = ("cogs.voice", "cogs.setup", "cogs.admin")


@dataclass(slots=True)
class Services:
    settings: GuildSettingsRepository
    rooms: TemporaryChannelRepository
    blocked: BlockedUserRepository
    permissions: PermissionService
    channels: ChannelService
    ownership: OwnershipService
    voice: VoiceService


class VoiceBot(commands.Bot):
    def __init__(self, config: Config) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.voice_states = True
        intents.members = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents, help_command=None)
        self.config = config
        self.db = Database(config.database_url)
        self.services = self._build_services()
        self._health_runner: web.AppRunner | None = None

    def _build_services(self) -> Services:
        sf = self.db.session_factory
        settings = GuildSettingsRepository(sf)
        rooms = TemporaryChannelRepository(sf)
        blocked = BlockedUserRepository(sf)
        permissions = PermissionService()
        room_locks = LockRegistry()
        channels = ChannelService(self, rooms, permissions)
        ownership = OwnershipService(self, rooms, permissions, channels, room_locks)
        voice = VoiceService(self, settings, rooms, blocked, permissions, channels, ownership, room_locks)
        return Services(settings, rooms, blocked, permissions, channels, ownership, voice)

    async def _start_health_server(self) -> None:
        if self.config.health_port <= 0:
            return

        async def health(_: web.Request) -> web.Response:
            return web.json_response({"status": "ok", "ready": self.is_ready(), "guilds": len(self.guilds)})

        app = web.Application()
        app.router.add_get("/health", health)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, self.config.health_host, self.config.health_port).start()
        self._health_runner = runner
        log.info("Health endpoint on %s:%d", self.config.health_host, self.config.health_port)

    async def setup_hook(self) -> None:
        await run_migrations(self.db.engine)
        await self._start_health_server()
        self.add_view(RoomPanelView())
        for extension in EXTENSIONS:
            await self.load_extension(extension)
        synced = await self.tree.sync()
        log.info("Synced %d application commands", len(synced))

    async def on_ready(self) -> None:
        log.info("Logged in as %s (%s), %d guilds", self.user, getattr(self.user, "id", "?"), len(self.guilds))

    async def close(self) -> None:
        if self._health_runner is not None:
            await self._health_runner.cleanup()
        await super().close()
        await self.db.dispose()


async def main() -> None:
    config = load_config()
    setup_logging(config.log_level)
    bot = VoiceBot(config)
    async with bot:
        try:
            await bot.start(config.token)
        except discord.PrivilegedIntentsRequired:
            log.critical(
                "Включите Server Members Intent: Developer Portal -> Bot -> Privileged Gateway Intents "
                "-> SERVER MEMBERS INTENT, затем перезапустите бота."
            )
            raise SystemExit(1) from None
        except discord.LoginFailure:
            log.critical("Неверный DISCORD_TOKEN. Сбросьте токен в Developer Portal и обновите .env.")
            raise SystemExit(1) from None


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Shutting down")
