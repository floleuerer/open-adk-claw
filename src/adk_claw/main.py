from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from adk_claw.agent import create_runner, create_curator_runner
from adk_claw.channels.gmail import GmailChannel
from adk_claw.channels.telegram import TelegramChannel
from adk_claw.config import Settings
from adk_claw.context import AppContext, set_context
from adk_claw.dispatcher import Dispatcher
from adk_claw.heartbeat import HeartbeatScheduler
from adk_claw.memory.service import MarkdownMemoryService
from adk_claw.queue import MessageQueue

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = Settings()

    # Set GOOGLE_API_KEY for the google-genai SDK
    os.environ.setdefault("GOOGLE_API_KEY", settings.google_api_key)

    # Initialize memory
    memory_service = MarkdownMemoryService(settings.base_dir)

    # Prepare workspace directories
    screenshots_dir = settings.base_dir / "browser_screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    files_dir = settings.base_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)

    skills_dir = settings.base_dir / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)

    agents_dir = settings.base_dir / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    # Initialize Gmail/Calendar services (if configured)
    gmail_svc = None
    calendar_svc = None
    gmail_channel: GmailChannel | None = None
    if settings.gmail_credentials_file:
        from adk_claw.channels.gmail.auth import get_gmail_service, get_calendar_service

        token_file = Path(settings.gmail_token_file)
        gmail_svc = get_gmail_service(settings.gmail_credentials_file, token_file)
        calendar_svc = get_calendar_service(settings.gmail_credentials_file, token_file)
        logger.info("Gmail and Calendar services initialized")

    # Set up application context (replaces per-module globals)
    set_context(AppContext(
        memory_service=memory_service,
        gmail_service=gmail_svc,
        calendar_service=calendar_svc,
        browser_url=settings.browser_service_url,
        sandbox_url=settings.sandbox_service_url,
        screenshots_dir=screenshots_dir,
        files_dir=files_dir,
        skills_dir=skills_dir,
        agents_dir=agents_dir,
        heartbeat_file=settings.base_dir / "CUSTOM_HEARTBEAT.md",
    ))

    # Initialize Langfuse tracing (if configured)
    if settings.langfuse_public_key and settings.langfuse_secret_key:
        os.environ.setdefault("LANGFUSE_PUBLIC_KEY", settings.langfuse_public_key)
        os.environ.setdefault("LANGFUSE_SECRET_KEY", settings.langfuse_secret_key)
        os.environ.setdefault("LANGFUSE_HOST", settings.langfuse_host)
        from langfuse import Langfuse
        from openinference.instrumentation.google_adk import GoogleADKInstrumentor

        Langfuse()
        GoogleADKInstrumentor().instrument()
        logger.info("Langfuse tracing enabled")

    # Create runners (curator shares session service to read conversation history)
    runner = create_runner(settings, memory_service)
    curator_runner = create_curator_runner(settings, runner.session_service)

    # Channels (created before dispatcher so we can pass send_reply)
    telegram: TelegramChannel | None = None

    def _is_email(chat_id: str) -> bool:
        return "@" in chat_id

    async def send_reply(chat_id: str, text: str) -> None:
        if _is_email(chat_id) and gmail_channel:
            await gmail_channel.send_reply(chat_id, text)
        elif telegram:
            await telegram.send_reply(chat_id, text)

    # Dispatcher with lane-based concurrency
    dispatcher = Dispatcher(runner, settings, memory_service, send_reply, curator_runner)

    # Build components
    queue = MessageQueue(
        debounce_seconds=settings.debounce_seconds,
        on_batch=dispatcher.enqueue_chat,
    )
    telegram = TelegramChannel(settings.telegram_bot_token, queue)

    if settings.gmail_credentials_file and settings.gmail_channel_enabled:
        gmail_channel = GmailChannel(
            service=gmail_svc,
            queue=queue,
            poll_interval=settings.gmail_poll_interval,
            label_filter=settings.gmail_label_filter,
        )

    heartbeat = HeartbeatScheduler(
        heartbeat_files=[
            settings.base_dir / "HEARTBEAT.md",
            settings.base_dir / "CUSTOM_HEARTBEAT.md",
        ],
        check_interval=settings.heartbeat_check_interval,
        on_heartbeat=dispatcher.enqueue_heartbeat,
    )

    # Start everything
    logger.info("Starting ADK-Claw...")
    await telegram.start()
    if gmail_channel:
        await gmail_channel.start()

    dispatcher_task = asyncio.create_task(dispatcher.run())
    heartbeat_task = asyncio.create_task(heartbeat.run())

    try:
        # Keep running until interrupted
        await asyncio.Event().wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Shutting down...")
    finally:
        heartbeat.stop()
        heartbeat_task.cancel()
        dispatcher_task.cancel()
        if gmail_channel:
            await gmail_channel.stop()
        await telegram.stop()
        logger.info("Shutdown complete")
