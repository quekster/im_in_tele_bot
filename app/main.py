from __future__ import annotations

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI, HTTPException, Request
from telegram import Update

from app.config import get_settings
from app.firestore_db import FirestoreDB
from app.telegram_app import build_application


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.telegram_application = None
    app.state.db = FirestoreDB(settings.google_cloud_project, settings.firestore_database)

    if settings.telegram_bot_token:
        telegram_application = build_application(settings)
        await telegram_application.initialize()
        await telegram_application.start()
        app.state.telegram_application = telegram_application
        app.state.db = telegram_application.bot_data["db"]
    else:
        logger.warning("TELEGRAM_BOT_TOKEN is not set; webhook endpoint is disabled.")

    try:
        yield
    finally:
        telegram_application = app.state.telegram_application
        if telegram_application:
            await telegram_application.stop()
            await telegram_application.shutdown()


app = FastAPI(title="ImInBot", lifespan=lifespan)


@app.get("/")
async def root() -> dict[str, str]:
    return {"status": "ImInBot is running"}


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


@app.get("/firestore-test")
async def firestore_test() -> dict:
    try:
        return await app.state.db.firestore_smoke_test()
    except Exception as exc:
        logger.exception("Firestore test failed")
        raise HTTPException(status_code=500, detail="Firestore test failed") from exc


@app.post("/telegram/{secret}")
async def telegram_webhook(secret: str, request: Request) -> dict[str, bool]:
    settings = app.state.settings
    if not settings.webhook_secret or secret != settings.webhook_secret:
        raise HTTPException(status_code=403, detail="Invalid webhook secret")

    telegram_application = app.state.telegram_application
    if telegram_application is None:
        raise HTTPException(status_code=503, detail="Telegram bot is not configured")

    try:
        payload = await request.json()
        update = Update.de_json(payload, telegram_application.bot)
        await telegram_application.process_update(update)
    except Exception as exc:
        logger.exception("Incoming webhook error")
        raise HTTPException(status_code=500, detail="Webhook processing failed") from exc

    return {"ok": True}
