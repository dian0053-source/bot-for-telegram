# ===============================
# Telegram-бот: 1 пост в день (Google Sheets + text всегда обязательный)
# ===============================

import os
import json
import csv
import random
from datetime import datetime, time
from zoneinfo import ZoneInfo
from typing import Dict, Any, List, Optional

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
    ContextTypes,
    filters,
)

# ===============================
# Конфиг
# ===============================
from config import (
    BOT_TOKEN, TARGET_CHAT_ID, SPREADSHEET_ID, POST_TIME, TZ,
    ADMIN_IDS, CREDENTIALS_FILE, POSTS_FILE, STATE_FILE, RANDOM_ORDER
)

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

SHEET_GIDS = {
    "Posts": "0",
    "Media": "854430773",
    "Ideas": "1938592340"
}
MEDIA_CSV = "media_store.csv"

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
    try:
        sheet = client.open_by_key(SPREADSHEET_ID).worksheet("Posts")
    except Exception:
        return []
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
# Queue
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
        dated_posts = [p for p in self.posts if p.get("datetime")]
        now = datetime.now(ZoneInfo(TZ))
        for p in dated_posts:
            try:
                dt = datetime.fromisoformat(p["datetime"])
                if now >= dt:
                    return p
            except Exception:
                continue
        if self.random:
            return random.choice(self.posts)
        idx = self.state["index"] % len(self.posts)
        post = self.posts[idx]
        self.state["index"] = idx + 1
        self.save()
        return post

def load_json(path: str, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

queue = Queue(POSTS_FILE, STATE_FILE, RANDOM_ORDER)

# ===============================
# Keyboard
# ===============================
def build_keyboard(post: Dict[str, Any]) -> Optional[InlineKeyboardMarkup]:
    btns = post.get("buttons")
    if not btns:
        return None
    rows = [[InlineKeyboardButton(text=b["text"], url=b["url"]) for b in btns]]
    return InlineKeyboardMarkup(rows)

# ===============================
# Send post
# ===============================
async def send_post(ctx: ContextTypes.DEFAULT_TYPE, post: Dict[str, Any]):
    chat_id = TARGET_CHAT_ID
    kb = build_keyboard(post)
    text = post.get("text", "")
    ptype = post.get("type")

    if ptype == "text":
        await ctx.bot.send_message(chat_id, text, reply_markup=kb, parse_mode=constants.ParseMode.HTML)
    elif ptype == "photo":
        await ctx.bot.send_photo(chat_id, photo=post["media"], caption=text, reply_markup=kb)
    elif ptype == "video":
        await ctx.bot.send_video(chat_id, video=post["media"], caption=text, reply_markup=kb)
    elif ptype == "audio":
        await ctx.bot.send_audio(chat_id, audio=post["media"], caption=text, reply_markup=kb)
    elif ptype == "voice":
        await ctx.bot.send_voice(chat_id, voice=post["media"], caption=text, reply_markup=kb)
    elif ptype == "document":
        await ctx.bot.send_document(chat_id, document=post["media"], caption=text, reply_markup=kb)
    elif ptype == "album":
        media_items = []
        for m in post.get("media", []):
            if m.get("type") == "photo":
                media_items.append(InputMediaPhoto(m["file"], caption=text))
            elif m.get("type") == "video":
                media_items.append(InputMediaVideo(m["file"], caption=text))
        if media_items:
            await ctx.bot.send_media_group(chat_id, media_items)
    elif ptype in ("poll", "image_poll"):
        await ctx.bot.send_poll(chat_id, question=text, options=post.get("options", []))
    else:
        await ctx.bot.send_message(chat_id, text=f"[Ошибка] Неизвестный тип: {ptype}")

# ===============================
# Admin commands
# ===============================
async def cmd_next(update: Update, context: ContextTypes.DEFAULT_TYPE):
    post = queue.next_post()
    if post:
        await send_post(context, post)
        await update.message.reply_text("Отправлено")
    else:
        await update.message.reply_text("Нет постов")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Бот работает. Постов: {len(queue.posts)}")

async def cmd_reload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    queue.reload()
    await update.message.reply_text("Посты перезагружены")

# ===============================
# Main
# ===============================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("next", cmd_next))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("reload", cmd_reload))

    # Polling запускает бота на бесплатном Render
    print(f"Bot started. Time: {POST_TIME} TZ={TZ} Chat={TARGET_CHAT_ID}")
    print("✅ main() дошёл до запуска")
    app.run_polling()

if __name__ == "__main__":
    main()
