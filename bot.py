# ===============================
# Telegram-бот: 1 пост в день (Google Sheets + text всегда обязательный)
# ===============================
# Теперь умеет:
# - Брать посты из Google Sheets или posts.json
# - Поддержка: text, photo, video, audio, voice, document, album, poll, image_poll, carousel
# - Всегда обязательный текст в постах
# - Возвращать file_id для любых файлов, отправленных в бот
# - Автоматически сохранять file_id в Google Sheets (лист Media) или в CSV (media_store.csv)
# ===============================

import os
print("🔥 bot.py запустился")
import json
import csv
import random
from datetime import time, datetime
from zoneinfo import ZoneInfo
from typing import Dict, Any, Optional, List

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
    ContextTypes,
    CallbackContext,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

# ✅ Берём все переменные из config.py
from config import (
    BOT_TOKEN, TARGET_CHAT_ID, SPREADSHEET_ID, POST_TIME, TZ,
    ADMIN_IDS, CREDENTIALS_FILE, POSTS_FILE, STATE_FILE, RANDOM_ORDER
)

# Берём JSON из переменной окружения
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
app = ApplicationBuilder().token(BOT_TOKEN).build()

# 📌 gid для каждого листа (замени на реальные gid из URL)
SHEET_GIDS = {
    "Posts": "0",          # gid вкладки "Posts"
    "Media": "854430773",  # gid вкладки "Media"
    "Ideas": "1938592340"   # gid вкладки "Ideas"
}

MEDIA_CSV = "media_store.csv"

# 🔹 Функция для получения ссылки на конкретный лист
def get_sheet_url(sheet_name: str) -> str:
    gid = SHEET_GIDS.get(sheet_name)
    if gid:
        return f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit#gid={gid}"
    return f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit"


MEDIA_CSV = "media_store.csv"

# -----------------------
# utils
# -----------------------

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

# -----------------------
# Google Sheets
# -----------------------

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
    sheet = client.open_by_key(SPREADSHEET_ID).worksheet(RANGE.split("!")[0])
    rows = sheet.get_all_records()
    posts = []
    for row in rows:
        if not row.get("text"):
            continue  # пропускаем посты без текста (text обязателен)
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

# -----------------------
# keyboard
# -----------------------

def build_keyboard(post: Dict[str, Any]) -> Optional[InlineKeyboardMarkup]:
    btns = post.get("buttons")
    if not btns:
        return None
    rows = [[InlineKeyboardButton(text=b["text"], url=b["url"]) for b in btns]]
    return InlineKeyboardMarkup(rows)

# -----------------------
# отправка поста (text всегда обязательный)
# -----------------------
async def send_post(ctx: CallbackContext, post: Dict[str, Any]):
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

    elif ptype == "album":
        media_items = []
        for m in post.get("media", []):
            if m.get("type") == "photo":
                media_items.append(InputMediaPhoto(media=m["file"], caption=text))
            elif m.get("type") == "video":
                media_items.append(InputMediaVideo(media=m["file"], caption=text))
        if media_items:
            await ctx.bot.send_media_group(chat_id=chat_id, media=media_items)

    elif ptype == "poll":
        await ctx.bot.send_poll(chat_id=chat_id, question=text,
                                options=post.get("options", []),
                                allows_multiple_answers=bool(post.get("allows_multiple_answers", False)),
                                is_anonymous=False)

    elif ptype == "image_poll":
        await ctx.bot.send_photo(chat_id=chat_id, photo=post["media"], caption=text)
        await ctx.bot.send_poll(chat_id=chat_id, question=text,
                                options=post.get("options", []),
                                allows_multiple_answers=bool(post.get("allows_multiple_answers", False)),
                                is_anonymous=False)

    elif ptype == "carousel":
        slides = post.get("slides", [])
        if not slides:
            return
        first = slides[0]
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("➡", callback_data=f"carousel|{json.dumps(slides)}|1")]])
        await ctx.bot.send_photo(chat_id=chat_id, photo=first["media"], caption=f"{text}\n\n{first.get('text','')}", reply_markup=kb)

    else:
        await ctx.bot.send_message(chat_id=chat_id, text=f"[Ошибка] Неизвестный тип поста: {ptype}")

# -----------------------
# обработчик карусели
# -----------------------
async def carousel_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    data = query.data.split("|", 2)
    if len(data) < 3:
        return
    _, slides_json, idx_str = data
    slides = json.loads(slides_json)
    idx = int(idx_str)
    if idx >= len(slides):
        idx = 0
    slide = slides[idx]

    prev_idx = (idx - 1) % len(slides)
    next_idx = (idx + 1) % len(slides)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅", callback_data=f"carousel|{json.dumps(slides)}|{prev_idx}"),
         InlineKeyboardButton("➡", callback_data=f"carousel|{json.dumps(slides)}|{next_idx}")]
    ])

    await query.edit_message_media(media=InputMediaPhoto(slide["media"], caption=slide.get("text", "")),
                                   reply_markup=kb)

# -----------------------
# Очередь постов
# -----------------------
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

queue = Queue(POSTS_FILE, STATE_FILE, RANDOM_ORDER)

# -----------------------
# джоба
# -----------------------
async def daily_job(ctx: ContextTypes.DEFAULT_TYPE):
    post = queue.next_post()
    if not post:
        await ctx.bot.send_message(chat_id=TARGET_CHAT_ID, text="[Внимание] Нет постов в Google Sheets или posts.json")
        return
    await send_post(ctx, post)

# -----------------------
# команды админа
# -----------------------
async def cmd_next(update, context):
    post = queue.next_post()
    if not post:
        return await update.message.reply_text("Нет постов")
    await send_post(context, post)
    await update.message.reply_text("Отправлено")

async def cmd_status(update, context):
    await update.message.reply_text(f"Бот работает. Постов: {len(queue.posts)}")

async def cmd_reload(update, context):
    queue.reload()
    await update.message.reply_text("Посты перезагружены (Google Sheets + JSON)")

# -----------------------
# сохранение file_id
# -----------------------
def save_file_id_to_store(file_type: str, file_id: str, name: str = ""):
    now = datetime.now(ZoneInfo(TZ)).isoformat(timespec="seconds")
    row = [file_type, file_id, name, now]

    client = get_gs_client()
    if client:
        try:
            sheet = client.open_by_key(SPREADSHEET_ID)
            try:
                ws = sheet.worksheet("Media")
            except gspread.exceptions.WorksheetNotFound:
                ws = sheet.add_worksheet("Media", rows="100", cols="4")
                ws.append_row(["type", "file_id", "original_name", "datetime"])
            ws.append_row(row)
            return
        except Exception as e:
            print("[Sheets error]", e)

    # fallback: save to CSV
    new_file = not os.path.exists(MEDIA_CSV)
    with open(MEDIA_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(["type", "file_id", "original_name", "datetime"])
        writer.writerow(row)

# -----------------------
# обработчик file_id
# -----------------------
async def file_id_handler(update: Update, context: CallbackContext):
    msg = update.message

    if msg.photo:
        file_id = msg.photo[-1].file_id
        await msg.reply_text(f"📸 Photo file_id:\n{file_id}")
        save_file_id_to_store("photo", file_id, msg.photo[-1].file_unique_id)

    elif msg.video:
        await msg.reply_text(f"🎥 Video file_id:\n{msg.video.file_id}")
        save_file_id_to_store("video", msg.video.file_id, msg.video.file_name or "")

    elif msg.audio:
        await msg.reply_text(f"🎵 Audio file_id:\n{msg.audio.file_id}")
        save_file_id_to_store("audio", msg.audio.file_id, msg.audio.file_name or "")

    elif msg.voice:
        await msg.reply_text(f"🎙 Voice file_id:\n{msg.voice.file_id}")
        save_file_id_to_store("voice", msg.voice.file_id)

    elif msg.document:
        await msg.reply_text(f"📂 Document file_id:\n{msg.document.file_id}")
        save_file_id_to_store("document", msg.document.file_id, msg.document.file_name or "")

    else:
        await msg.reply_text("❌ Не могу распознать файл")

# -----------------------
# планирование
# -----------------------
async def schedule_daily(app):
    for job in app.job_queue.jobs():
        job.schedule_removal()
    hhmm = parse_time(DAILY_TIME)
    app.job_queue.run_daily(daily_job, time=hhmm)
# ===============================

# -----------------------
# main
# -----------------------

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("next", cmd_next))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("reload", cmd_reload))
    app.add_handler(CallbackQueryHandler(carousel_handler, pattern=r"^carousel\\|"))

    # 🎯 Обработчики для медиа
    app.add_handler(MessageHandler(filters.PHOTO, file_id_handler))
    app.add_handler(MessageHandler(filters.VIDEO, file_id_handler))
    app.add_handler(MessageHandler(filters.AUDIO, file_id_handler))
    app.add_handler(MessageHandler(filters.VOICE, file_id_handler))
    app.add_handler(MessageHandler(filters.Document.ALL, file_id_handler))

    # fallback — любые другие сообщения
    app.add_handler(MessageHandler(filters.ALL & (~filters.COMMAND), file_id_handler))

    # ✅ Запланировать ежедневный пост
    app.job_queue.run_daily(
        callback=lambda ctx: ctx.application.create_task(post_daily(ctx)),
        time=datetime.strptime(POST_TIME, "%H:%M").time(),
        days=(0, 1, 2, 3, 4, 5, 6),   # каждый день недели
    )

    print(f"Bot started. Time: {POST_TIME} TZ={TZ} Chat={TARGET_CHAT_ID}")
    print("✅ main() дошёл до запуска")
    app.run_polling()


if __name__ == "__main__":
    main()
    # --- Начало кода для Render Web Service ---
    from flask import Flask
    import threading
    import os

    app = Flask(__name__)

    @app.route("/")
    def home():
        return "Bot is running!"

    def run_flask():
        port = int(os.environ.get("PORT", 5000))
        app.run(host="0.0.0.0", port=port)

    # Запускаем Flask в отдельном потоке, чтобы бот продолжал работать
    threading.Thread(target=run_flask).start()
    # --- Конец кода для Render Web Service ---
# --- Основной код бота ---
def main():
    # Тут твой код для запуска бота
    pass

if __name__ == "__main__":
    main()