# ===============================
# Telegram-бот: 1 пост в день (Google Sheets + текст всегда обязательный)
# ===============================

import os
import json
import csv
import random
from datetime import datetime, time
from zoneinfo import ZoneInfo
from typing import Dict, Any, Optional, List
import threading

import gspread
from oauth2client.service_account import ServiceAccountCredentials

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    InputMediaVideo,
    Update,
    constants,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ✅ Берём все переменные из config.py
from config import (
    BOT_TOKEN, TARGET_CHAT_ID, SPREADSHEET_ID, POST_TIME, TZ,
    ADMIN_IDS, CREDENTIALS_FILE, POSTS_FILE, STATE_FILE, RANDOM_ORDER
)

print("🔥 bot.py запустился")

# ===============================
# Flask для Render Web Service
# ===============================
from flask import Flask
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "Bot is running!"

def run_flask():
    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port)

# Запускаем Flask в отдельном потоке сразу
threading.Thread(target=run_flask).start()

# ===============================
# Google Sheets
# ===============================
google_credentials = os.getenv("GOOGLE_CREDENTIALS")
if google_credentials:
    creds_dict = json.loads(google_credentials)
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
else:
    creds = None
    client = None
    print("⚠️ GOOGLE_CREDENTIALS не задан — доступ к Google Sheets отключён")

MEDIA_CSV = "media_store.csv"

SHEET_GIDS = {
    "Posts": "0",
    "Media": "854430773",
    "Ideas": "1938592340"
}

def get_sheet_url(sheet_name: str) -> str:
    gid = SHEET_GIDS.get(sheet_name)
    if gid:
        return f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit#gid={gid}"
    return f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit"

def load_json(path: str, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def parse_time(hhmm: str) -> time:
    hh, mm = [int(x) for x in hhmm.split(":")]
    return time(hour=hh, minute=mm, tzinfo=ZoneInfo(TZ))

def get_gs_client():
    if not SPREADSHEET_ID or not os.path.exists(CREDENTIALS_FILE):
        return None
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)
    return client

def fetch_posts_from_sheets() -> List[Dict[str, Any]]:
    client = get_gs_client()
    if not client:
        return []
    sheet = client.open_by_key(SPREADSHEET_ID).worksheet("Posts")
    rows = sheet.get_all_records()
    posts = []
    for row in rows:
        if not row.get("text"):
            continue
        post = {
            "type": row.get("type", "text"),
            "text": row.get("text"),
            "media": row.get("media", ""),
            "options": row.get("options", "").split(";") if row.get("options") else [],
            "datetime": row.get("datetime", ""),
            "slides": json.loads(row.get("slides")) if row.get("slides") else []
        }
        posts.append(post)
    return posts

# ===============================
# keyboard
# ===============================
def build_keyboard(post: Dict[str, Any]) -> Optional[InlineKeyboardMarkup]:
    btns = post.get("buttons")
    if not btns:
        return None
    rows = [[InlineKeyboardButton(text=b["text"], url=b["url"]) for b in btns]]
    return InlineKeyboardMarkup(rows)

# ===============================
# отправка поста
# ===============================
async def send_post(ctx: ContextTypes.DEFAULT_TYPE, post: Dict[str, Any]):
    chat_id = TARGET_CHAT_ID
    kb = build_keyboard(post)
    disable_notif = bool(post.get("disable_notification", False))
    ptype = post.get("type")
    text = post.get("text", "")

    if ptype == "text":
        await ctx.bot.send_message(chat_id=chat_id, text=text, reply_markup=kb,
                                   disable_notification=disable_notif, parse_mode=constants.ParseMode.HTML)
    elif ptype == "photo":
        await ctx.bot.send_photo(chat_id=chat_id, photo=post["media"], caption=text, reply_markup=kb,
                                 disable_notification=disable_notif, parse_mode=constants.ParseMode.HTML)
    elif ptype == "video":
        await ctx.bot.send_video(chat_id=chat_id, video=post["media"], caption=text, reply_markup=kb,
                                 disable_notification=disable_notif, parse_mode=constants.ParseMode.HTML)
    elif ptype == "audio":
        await ctx.bot.send_audio(chat_id=chat_id, audio=post["media"], caption=text, reply_markup=kb,
                                 disable_notification=disable_notif, parse_mode=constants.ParseMode.HTML)
    elif ptype == "voice":
        await ctx.bot.send_voice(chat_id=chat_id, voice=post["media"], caption=text, reply_markup=kb,
                                 disable_notification=disable_notif, parse_mode=constants.ParseMode.HTML)
    elif ptype == "document":
        await ctx.bot.send_document(chat_id=chat_id, document=post["media"], caption=text, reply_markup=kb,
                                    disable_notification=disable_notif, parse_mode=constants.ParseMode.HTML)
    # Дополнительные типы (album, poll и т.д.) можно добавить по аналогии

# ===============================
# очередь постов
# ===============================
class Queue:
    def __init__(self, posts_file: str, state_file: str, random_order: bool):
        self.posts_file = posts_file
        self.state_file = state_file
        self.random = random_order
        self.posts: List[Dict[str, Any]] = []
        self.state = {"index": 0}
        self.reload()

    def reload(self):
        sheet_posts = fetch_posts_from_sheets()
        if sheet_posts:
            self.posts = sheet_posts
        else:
            self.posts = load_json(self.posts_file, [])
        self.state = load_json(self.state_file, {"index": 0})
        if not isinstance(self.state.get("index"), int):
            self.state["index"] = 0

    def save(self):
        save_json(self.state_file, self.state)

    def next_post(self) -> Optional[Dict[str, Any]]:
        if not self.posts:
            return None
        idx = self.state["index"] % len(self.posts)
        post = self.posts[idx]
        self.state["index"] = idx + 1
        self.save()
        return post

queue = Queue(POSTS_FILE, STATE_FILE, RANDOM_ORDER)

# ===============================
# обработка файлов (file_id)
# ===============================
async def file_id_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg.photo:
        file_id = msg.photo[-1].file_id
    elif msg.video:
        file_id = msg.video.file_id
    elif msg.audio:
        file_id = msg.audio.file_id
    elif msg.voice:
        file_id = msg.voice.file_id
    elif msg.document:
        file_id = msg.document.file_id
    else:
        return
    await msg.reply_text(f"File ID: {file_id}")

# ===============================
# main
# ===============================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # команды
    app.add_handler(CommandHandler("next", lambda u, c: send_post(c, queue.next_post())))
    app.add_handler(CommandHandler("status", lambda u, c: c.bot.send_message(chat_id=TARGET_CHAT_ID, text="Bot работает")))
    app.add_handler(MessageHandler(filters.ALL, file_id_handler))

    print(f"Bot started. Time: {POST_TIME} TZ={TZ} Chat={TARGET_CHAT_ID}")
    app.run_polling()

# ===============================
# Запуск
# ===============================
if __name__ == "__main__":
    main()
