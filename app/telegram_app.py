from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from app.config import Settings
from app.firestore_db import FirestoreDB
from app.handlers import (
    add_user_handler,
    close_invite_handler,
    delete_invite_handler,
    end_event_handler,
    edit_invite_handler,
    invite_button_handler,
    open_invite_handler,
    remember_seen_user_handler,
    remove_user_handler,
    set_capacity_handler,
    set_tourneys_topic_handler,
    setup_flow_text_handler,
    start_handler,
    start_invite_handler,
)


def build_application(settings: Settings) -> Application:
    application = Application.builder().token(settings.telegram_bot_token).build()
    application.bot_data["db"] = FirestoreDB(settings.google_cloud_project, settings.firestore_database)
    application.bot_data["setup_flows"] = {}

    application.add_handler(MessageHandler(filters.ALL, remember_seen_user_handler), group=-1)
    application.add_handler(CallbackQueryHandler(remember_seen_user_handler), group=-1)

    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("settourneystopic", set_tourneys_topic_handler))
    application.add_handler(CommandHandler("createinvite", start_invite_handler))
    application.add_handler(CommandHandler("editinvite", edit_invite_handler))
    application.add_handler(CommandHandler("setcapacity", set_capacity_handler))
    application.add_handler(CommandHandler("openinvite", open_invite_handler))
    application.add_handler(CommandHandler("closeinvite", close_invite_handler))
    application.add_handler(CommandHandler("removeuser", remove_user_handler))
    application.add_handler(CommandHandler("adduser", add_user_handler))
    application.add_handler(CommandHandler("deleteinvite", delete_invite_handler))
    application.add_handler(CommandHandler("endevent", end_event_handler))
    application.add_handler(CallbackQueryHandler(invite_button_handler))
    application.add_handler(MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND, setup_flow_text_handler))

    return application
