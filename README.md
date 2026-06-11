# ImInBot

ImInBot is a Telegram bot for managing event attendance inside a Telegram group forum topic. It runs as a FastAPI webhook service for Google Cloud Run and stores event state in Google Firestore.

## Stack

- Python 3.11+
- FastAPI
- Uvicorn
- python-telegram-bot
- Google Cloud Firestore
- Google Cloud Run

## Project Structure

```text
app/
  main.py          FastAPI app and Telegram webhook endpoint
  config.py        Environment configuration
  telegram_app.py  python-telegram-bot application setup
  handlers.py      Telegram command, setup flow, and callback handlers
  firestore_db.py  Firestore data access and transactions
  render.py        Invite message rendering
  keyboards.py     Inline keyboards
  admin.py         Admin and topic validation helpers
```

## Environment

Create a local `.env` file from `.env.example`:

```env
TELEGRAM_BOT_TOKEN=
GOOGLE_CLOUD_PROJECT=
FIRESTORE_DATABASE=
WEBHOOK_SECRET=
```

`WEBHOOK_SECRET` is used in the webhook URL path:

`FIRESTORE_DATABASE` is optional for default Firestore databases. Set it when using a named database, for example `im-in-bot-db`.

```text
/telegram/<WEBHOOK_SECRET>
```

## Local Development

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Health endpoints:

```text
GET /
GET /health
GET /firestore-test
```

The root endpoint returns:

```json
{"status": "ImInBot is running"}
```

## Telegram Setup

1. Add the bot to the Telegram group.
2. Make the bot an admin with permission to delete messages, send messages, edit its own messages, read group/topic messages, and use inline keyboards.
3. In the `TOURNEYS` forum topic, an admin sends:

```text
/settourneystopic
```

After that, invite commands only work in the configured chat and topic.

## Admin Commands

Create an invite:

```text
/startinvite
```

`/createinvite` also works as an alias.

During the invite text step, admins can either paste text or send a poster image with the event details in the image caption. If the poster has no caption, the bot asks for the invite text next.

Reply to an invite message with:

```text
/closeinvite
/openinvite
/setcapacity 8
/editinvite
/removeuser @username
/adduser @username
/deleteinvite
/endevent
```

Manual add only works for users already known to that invite, because Telegram does not let bots reliably resolve arbitrary handles to numeric user IDs.

## User Buttons

Every invite message has:

```text
[I'm in!] [Waitlist me] [I'm out...]
```

Users must have a Telegram username to join or waitlist. The bot stores numeric `user_id` internally and displays the username captured at signup.

## Deploy To Cloud Run

Build and deploy with your preferred Google Cloud workflow. Cloud Run should use:

```text
Minimum instances: 0
Memory: 512 MiB
Region: asia-southeast1
Allow unauthenticated HTTP access: yes
```

The container listens on the `PORT` environment variable.

After deployment, register the Telegram webhook:

```text
https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook?url=<CLOUD_RUN_URL>/telegram/<WEBHOOK_SECRET>
```

Do not hardcode the Cloud Run URL, bot token, or webhook secret in source code.


## Deploying Code Changes

When you edit the code in VS Code, the online bot does not update automatically. You need to deploy the new version to Google Cloud Run.

Open PowerShell and run these commands one by one:

```powershell
cd C:\ImInBotProj
```

```powershell
.\.venv\Scripts\Activate.ps1
```

Check that the code has no obvious syntax errors:

```powershell
python -m compileall app scripts
```

Deploy the new version:

```powershell
gcloud.cmd run deploy iminbot --source . --region asia-southeast1 --project im-in-bot --allow-unauthenticated --memory 512Mi --min-instances 0
```

Check that the server is alive:

```powershell
Invoke-RestMethod -Uri "https://iminbot-oyrwtlt2za-as.a.run.app/health"
```

Expected result:

```text
ok
--
True
```

You usually do not need to reset the Telegram webhook after normal code changes.

Only reset the webhook if you change one of these:

```text
TELEGRAM_BOT_TOKEN
WEBHOOK_SECRET
Cloud Run service URL
```

If you add, remove, or rename slash commands, deployment is not enough. Telegram's visible command menu is managed separately through BotFather:

```text
/setcommands
```

The bot code is controlled by:

```text
app/telegram_app.py
```

The visible Telegram command menu is controlled by BotFather.