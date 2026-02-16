from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

from adk_claw.channels.base import BaseChannel
from adk_claw.queue import MessageQueue

logger = logging.getLogger(__name__)


class TelegramChannel(BaseChannel):
    def __init__(self, bot_token: str, queue: MessageQueue) -> None:
        self._queue = queue
        self._app = Application.builder().token(bot_token).build()
        self._app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_message)
        )

    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not update.message.text:
            return

        chat_id = str(update.effective_chat.id)
        user = update.effective_user
        user_name = user.full_name if user else "Unknown"
        text = update.message.text

        logger.info("Received message from %s (chat %s): %s", user_name, chat_id, text[:50])
        await self._queue.push(chat_id, text, user_name)

    async def send_reply(self, chat_id: str, text: str) -> None:
        if not text.strip():
            return
        # Telegram has a 4096 char limit per message
        for i in range(0, len(text), 4096):
            chunk = text[i:i + 4096]
            await self._app.bot.send_message(chat_id=int(chat_id), text=chunk)

    async def start(self) -> None:
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram polling started")

    async def stop(self) -> None:
        if self._app.updater.running:
            await self._app.updater.stop()
        if self._app.running:
            await self._app.stop()
        await self._app.shutdown()
        logger.info("Telegram stopped")
