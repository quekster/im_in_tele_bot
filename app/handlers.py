from __future__ import annotations

import logging
from typing import Any

from telegram import Message, Update
from telegram.constants import ChatMemberStatus
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from app.admin import delete_message_safely, ensure_admin_command, ensure_allowed_topic
from app.firestore_db import FirestoreDB
from app.keyboards import invite_keyboard
from app.render import render_event_message


logger = logging.getLogger(__name__)

Flow = dict[str, Any]


def _db(context: ContextTypes.DEFAULT_TYPE) -> FirestoreDB:
    return context.application.bot_data["db"]


def _flows(context: ContextTypes.DEFAULT_TYPE) -> dict[tuple[int, int], Flow]:
    return context.application.bot_data.setdefault("setup_flows", {})


def _flow_key(update: Update) -> tuple[int, int] | None:
    message = update.effective_message
    user = update.effective_user
    if not message or not user:
        return None
    return (message.chat_id, user.id)


async def _send_topic_message(
    context: ContextTypes.DEFAULT_TYPE,
    message: Message,
    text: str,
    **kwargs: Any,
) -> Message:
    kwargs.setdefault("disable_notification", True)
    return await context.bot.send_message(
        chat_id=message.chat_id,
        message_thread_id=message.message_thread_id,
        text=text,
        **kwargs,
    )


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message:
        await message.reply_text("ImInBot is running. Admins can use /settourneystopic in TOURNEYS to begin.")


async def remember_seen_user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat = update.effective_chat
    if not user or not chat or not user.username:
        return

    try:
        await _db(context).remember_user(chat.id, user.id, user.username, user.full_name)
        logger.info("Remembered user %s in chat %s", user.id, chat.id)
    except Exception:
        logger.exception("Failed to remember known Telegram user")


async def set_tourneys_topic_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message or not await ensure_admin_command(update, context):
        return

    db = _db(context)
    await db.set_topic_settings(message.chat_id, message.message_thread_id)
    await delete_message_safely(context, message.chat_id, message.message_id)
    await _send_topic_message(context, message, "TOURNEYS topic configured.")


async def start_invite_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    key = _flow_key(update)
    db = _db(context)
    if not message or not key:
        return
    if not await ensure_admin_command(update, context):
        return
    if not await ensure_allowed_topic(update, context, db):
        return

    await delete_message_safely(context, message.chat_id, message.message_id)
    prompt = await _send_topic_message(context, message, "Paste the invite text, or send a poster image with caption.")
    _flows(context)[key] = {
        "type": "start_invite",
        "step": "invite_text",
        "chat_id": message.chat_id,
        "message_thread_id": message.message_thread_id,
        "prompt_message_ids": [prompt.message_id],
    }


async def edit_invite_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    key = _flow_key(update)
    db = _db(context)
    if not message or not key:
        return
    if not await ensure_admin_command(update, context):
        return
    if not await ensure_allowed_topic(update, context, db):
        return

    event = await _event_from_reply(update, db)
    if not event:
        await _send_topic_message(context, message, "Reply to an invite message with /editinvite.")
        await delete_message_safely(context, message.chat_id, message.message_id)
        return

    await delete_message_safely(context, message.chat_id, message.message_id)
    prompt = await _send_topic_message(context, message, "Paste the new invite text.")
    _flows(context)[key] = {
        "type": "edit_invite",
        "event_id": event["id"],
        "chat_id": message.chat_id,
        "message_thread_id": message.message_thread_id,
        "prompt_message_ids": [prompt.message_id],
    }


async def setup_flow_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    key = _flow_key(update)
    if not message or not key:
        return

    flow = _flows(context).get(key)
    if not flow:
        return
    if message.chat_id != flow.get("chat_id") or message.message_thread_id != flow.get("message_thread_id"):
        return

    if flow["type"] == "start_invite":
        await _handle_start_invite_flow(update, context, flow, key)
    elif flow["type"] == "edit_invite":
        await _handle_edit_invite_flow(update, context, flow, key)


async def _handle_start_invite_flow(
    update: Update, context: ContextTypes.DEFAULT_TYPE, flow: Flow, key: tuple[int, int]
) -> None:
    message = update.effective_message
    user = update.effective_user
    db = _db(context)
    if not message or not user:
        return

    if flow["step"] == "invite_text":
        if message.photo:
            flow["poster_file_id"] = message.photo[-1].file_id
            invite_text = message.caption or ""
            await delete_message_safely(context, message.chat_id, message.message_id)
            if not invite_text.strip():
                flow["step"] = "poster_text"
                prompt = await _send_topic_message(context, message, "Paste the invite text for this poster.")
                flow.setdefault("prompt_message_ids", []).append(prompt.message_id)
                return
            flow["invite_text"] = invite_text
        else:
            flow["invite_text"] = message.text or ""
        flow["step"] = "capacity"
        await delete_message_safely(context, message.chat_id, message.message_id)
        prompt = await _send_topic_message(context, message, "Enter the max capacity.")
        flow.setdefault("prompt_message_ids", []).append(prompt.message_id)
        return

    if flow["step"] == "poster_text":
        flow["invite_text"] = message.text or ""
        flow["step"] = "capacity"
        await delete_message_safely(context, message.chat_id, message.message_id)
        prompt = await _send_topic_message(context, message, "Enter the max capacity.")
        flow.setdefault("prompt_message_ids", []).append(prompt.message_id)
        return

    try:
        max_capacity = int((message.text or "").strip())
        if max_capacity <= 0:
            raise ValueError
    except ValueError:
        await _send_topic_message(context, message, "Capacity must be a positive integer.")
        await delete_message_safely(context, message.chat_id, message.message_id)
        return

    await delete_message_safely(context, message.chat_id, message.message_id)
    await _delete_prompt_messages(context, flow)

    event_id = db.new_event_id()
    poster_message_id = None
    if flow.get("poster_file_id"):
        poster = await context.bot.send_photo(
            chat_id=message.chat_id,
            photo=flow["poster_file_id"],
            message_thread_id=message.message_thread_id,
        )
        poster_message_id = poster.message_id

    event = {
        "id": event_id,
        "invite_text": flow["invite_text"],
        "max_capacity": max_capacity,
        "is_open": True,
        "is_deleted": False,
    }
    sent = await context.bot.send_message(
        chat_id=message.chat_id,
        text=render_event_message(event, []),
        reply_markup=invite_keyboard(event_id),
        message_thread_id=message.message_thread_id,
    )
    await db.create_event(
        event_id,
        chat_id=message.chat_id,
        message_thread_id=message.message_thread_id,
        message_id=sent.message_id,
        invite_text=flow["invite_text"],
        max_capacity=max_capacity,
        created_by_user_id=user.id,
        poster_file_id=flow.get("poster_file_id"),
        poster_message_id=poster_message_id,
    )
    _flows(context).pop(key, None)


async def _handle_edit_invite_flow(
    update: Update, context: ContextTypes.DEFAULT_TYPE, flow: Flow, key: tuple[int, int]
) -> None:
    message = update.effective_message
    db = _db(context)
    if not message:
        return

    new_text = message.text or ""
    await delete_message_safely(context, message.chat_id, message.message_id)
    await _delete_prompt_messages(context, flow)
    result = await db.update_invite_text(flow["event_id"], new_text)
    if result.get("ok"):
        await refresh_event_message(context, db, flow["event_id"])
    else:
        await _send_topic_message(context, message, result.get("message", "Invite not found."))
    _flows(context).pop(key, None)


async def set_capacity_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    db = _db(context)
    if not message:
        return
    if not await ensure_admin_command(update, context):
        return
    if not await ensure_allowed_topic(update, context, db):
        return

    try:
        capacity = int(context.args[0])
        if capacity <= 0:
            raise ValueError
    except (IndexError, ValueError):
        await _send_topic_message(context, message, "Use /setcapacity <positive number> as a reply to an invite.")
        await delete_message_safely(context, message.chat_id, message.message_id)
        return

    event = await _event_from_reply(update, db)
    if not event:
        await _send_topic_message(context, message, "Reply to an invite message with /setcapacity.")
        await delete_message_safely(context, message.chat_id, message.message_id)
        return

    result = await db.set_capacity(event["id"], capacity)
    if result.get("ok"):
        await refresh_event_message(context, db, event["id"])
    else:
        await _send_topic_message(context, message, result.get("message", "Invite not found."))
    await delete_message_safely(context, message.chat_id, message.message_id)


async def open_invite_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _set_open_from_command(update, context, True)


async def close_invite_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _set_open_from_command(update, context, False)


async def _set_open_from_command(update: Update, context: ContextTypes.DEFAULT_TYPE, is_open: bool) -> None:
    message = update.effective_message
    db = _db(context)
    if not message:
        return
    if not await ensure_admin_command(update, context):
        return
    if not await ensure_allowed_topic(update, context, db):
        return

    event = await _event_from_reply(update, db)
    if not event:
        await _send_topic_message(context, message, "Reply to an invite message with this command.")
        await delete_message_safely(context, message.chat_id, message.message_id)
        return

    result = await db.set_event_open(event["id"], is_open)
    if result.get("ok"):
        await refresh_event_message(context, db, event["id"])
    else:
        await _send_topic_message(context, message, result.get("message", "Invite not found."))
    await delete_message_safely(context, message.chat_id, message.message_id)


async def remove_user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _manual_user_command(update, context, action="remove")


async def add_user_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _manual_user_command(update, context, action="add")


async def _manual_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE, *, action: str) -> None:
    message = update.effective_message
    db = _db(context)
    if not message:
        return
    if not await ensure_admin_command(update, context):
        return
    if not await ensure_allowed_topic(update, context, db):
        return

    try:
        username = context.args[0]
    except IndexError:
        await _send_topic_message(context, message, f"Use /{action}user @username as a reply to an invite.")
        await delete_message_safely(context, message.chat_id, message.message_id)
        return

    event = await _event_from_reply(update, db)
    if not event:
        await _send_topic_message(context, message, f"Reply to an invite message with /{action}user.")
        await delete_message_safely(context, message.chat_id, message.message_id)
        return

    if action == "remove":
        result = await db.remove_user_by_username(event["id"], username)
    else:
        known_user = await db.get_known_user_by_username(username, message.chat_id)
        if not known_user:
            await _send_topic_message(
                context,
                message,
                "I do not know that user yet. Ask them to press an invite button or send a message in this group first.",
            )
            await delete_message_safely(context, message.chat_id, message.message_id)
            return

        if not await _is_current_group_member(context, message.chat_id, int(known_user["user_id"])):
            await _send_topic_message(context, message, "That user is not currently in this group.")
            await delete_message_safely(context, message.chat_id, message.message_id)
            return

        result = await db.add_user_to_event(event["id"], int(known_user["user_id"]), str(known_user["username"]))

    if result.get("ok"):
        await refresh_event_message(context, db, event["id"])
    else:
        await _send_topic_message(context, message, result.get("message", "User update failed."))
    await delete_message_safely(context, message.chat_id, message.message_id)


async def delete_invite_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    db = _db(context)
    if not message:
        return
    if not await ensure_admin_command(update, context):
        return
    if not await ensure_allowed_topic(update, context, db):
        return

    event = await _event_from_reply(update, db)
    if not event:
        await _send_topic_message(context, message, "Reply to an invite message with /deleteinvite.")
        await delete_message_safely(context, message.chat_id, message.message_id)
        return

    result = await db.delete_event(event["id"])
    if result.get("ok"):
        await _delete_poster_message(context, event)
        try:
            await _edit_event_text(context, event, "This invite has been deleted.", reply_markup=None)
        except TelegramError:
            logger.exception("Failed to edit deleted invite message")
    else:
        await _send_topic_message(context, message, result.get("message", "Invite not found."))
    await delete_message_safely(context, message.chat_id, message.message_id)


async def end_event_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    db = _db(context)
    if not message:
        return
    if not await ensure_admin_command(update, context):
        return
    if not await ensure_allowed_topic(update, context, db):
        return

    event = await _event_from_reply(update, db)
    if not event:
        await _send_topic_message(context, message, "Reply to an invite message with /endevent.")
        await delete_message_safely(context, message.chat_id, message.message_id)
        return

    signups = await db.list_signups(event["id"])
    ended_event = {**event, "status": "ended", "is_open": False, "is_deleted": False}
    try:
        await _edit_event_text(context, event, render_event_message(ended_event, signups), reply_markup=None)
    except TelegramError:
        logger.exception("Failed to edit ended event message")

    result = await db.end_event(event["id"])
    if not result.get("ok"):
        await _send_topic_message(context, message, result.get("message", "Invite not found."))
    await delete_message_safely(context, message.chat_id, message.message_id)


async def invite_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    db = _db(context)
    if not query or not user or not query.data:
        return

    try:
        _, action, event_id = query.data.split(":", 2)
    except ValueError:
        await query.answer("Unsupported button.", show_alert=False)
        return

    if action in {"join", "waitlist"} and not user.username:
        await query.answer("Please set a Telegram username before joining this invite.", show_alert=False)
        return

    try:
        if action == "join":
            result = await db.join_event(event_id, user.id, user.username or "")
        elif action == "waitlist":
            result = await db.waitlist_event(event_id, user.id, user.username or "")
        elif action == "leave":
            result = await db.leave_event(event_id, user.id)
        else:
            result = {"ok": False, "message": "Unsupported button."}
    except Exception:
        logger.exception("Invite button transaction failed")
        await query.answer("Something went wrong. Please try again.", show_alert=False)
        return

    await query.answer(result.get("message", "Done."), show_alert=False)
    if result.get("changed"):
        await refresh_event_message(context, db, event_id)


async def refresh_event_message(context: ContextTypes.DEFAULT_TYPE, db: FirestoreDB, event_id: str) -> None:
    event = await db.get_event(event_id)
    if not event:
        return

    signups = await db.list_signups(event_id)
    try:
        await _edit_event_text(
            context,
            event,
            render_event_message(event, signups),
            reply_markup=None if event.get("is_deleted") else invite_keyboard(event_id),
        )
    except TelegramError:
        logger.exception("Failed to edit invite message")


async def _edit_event_text(
    context: ContextTypes.DEFAULT_TYPE,
    event: dict[str, Any],
    text: str,
    **kwargs: Any,
) -> None:
    await context.bot.edit_message_text(
        chat_id=event["chat_id"],
        message_id=event["message_id"],
        text=text,
        **kwargs,
    )


async def _delete_poster_message(context: ContextTypes.DEFAULT_TYPE, event: dict[str, Any]) -> None:
    poster_message_id = event.get("poster_message_id")
    if poster_message_id:
        await delete_message_safely(context, event["chat_id"], int(poster_message_id))


async def _is_current_group_member(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
    except TelegramError:
        logger.exception("Failed to validate adduser target membership")
        return False
    return member.status not in {ChatMemberStatus.LEFT, ChatMemberStatus.BANNED}


async def _event_from_reply(update: Update, db: FirestoreDB) -> dict[str, Any] | None:
    message = update.effective_message
    if not message or not message.reply_to_message:
        return None
    return await db.get_event_by_message(message.chat_id, message.reply_to_message.message_id)


async def _delete_prompt_messages(context: ContextTypes.DEFAULT_TYPE, flow: Flow) -> None:
    chat_id = flow.get("chat_id")
    if not chat_id:
        return
    for message_id in flow.get("prompt_message_ids", []):
        await delete_message_safely(context, chat_id, message_id)
