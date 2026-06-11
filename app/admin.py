from __future__ import annotations

import logging

from telegram import Message, Update
from telegram.constants import ChatMemberStatus
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from app.firestore_db import FirestoreDB


logger = logging.getLogger(__name__)


async def delete_message_safely(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int) -> None:
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except TelegramError:
        logger.exception("Failed to delete Telegram message")


async def is_group_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return False

    try:
        member = await context.bot.get_chat_member(message.chat_id, user.id)
    except TelegramError:
        logger.exception("Failed to validate Telegram admin status")
        return False

    return member.status in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER}


async def ensure_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    message = update.effective_message
    if not message:
        return False

    is_admin = await is_group_admin(update, context)
    if not is_admin:
        logger.warning("Rejected non-admin command")
        try:
            await message.reply_text("Admin-only command.", disable_notification=True)
        except TelegramError:
            logger.exception("Failed to send admin rejection message")
        await delete_message_safely(context, message.chat_id, message.message_id)
        return False

    return True


async def ensure_allowed_topic(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    db: FirestoreDB,
    *,
    require_configured: bool = True,
) -> bool:
    message = update.effective_message
    if not message:
        return False

    settings = await db.get_topic_settings()
    if not settings:
        if require_configured:
            await _short_reply(message, "Run /settourneystopic in TOURNEYS first.")
            await delete_message_safely(context, message.chat_id, message.message_id)
            return False
        return True

    allowed_chat_id = settings.get("allowed_chat_id")
    allowed_thread_id = settings.get("tourneys_message_thread_id")
    if message.chat_id == allowed_chat_id and message.message_thread_id == allowed_thread_id:
        return True

    await _short_reply(message, "Use this command in the configured TOURNEYS topic.")
    await delete_message_safely(context, message.chat_id, message.message_id)
    return False


async def _short_reply(message: Message, text: str) -> None:
    try:
        await message.reply_text(text, disable_notification=True)
    except TelegramError:
        logger.exception("Failed to send validation reply")
