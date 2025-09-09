from dotenv import load_dotenv
import os

def clean(value: str) -> str:
    """Убирает пробелы и переводы строк вокруг значения"""
    if value is None:
        return None
    return value.strip()

# Загружаем .env
load_dotenv()

def get_env(name: str) -> str:
    """Читает переменную окружения и обрезает лишние пробелы/переводы 
строк"""
    val = os.getenv(name, "")
    return val.strip()

BOT_TOKEN = get_env("BOT_TOKEN")
TARGET_CHAT_ID = get_env("TARGET_CHAT_ID")
SPREADSHEET_ID = get_env("SPREADSHEET_ID")
POST_TIME = get_env("POST_TIME")
TZ = get_env("TZ")
ADMIN_IDS = get_env("ADMIN_IDS")
CREDENTIALS_FILE = get_env("CREDENTIALS_FILE")

if __name__ == "__main__":
    print("BOT_TOKEN:", repr(BOT_TOKEN), "len=", len(BOT_TOKEN))
POSTS_FILE = clean(os.getenv("POSTS_FILE") or "posts.json")
STATE_FILE = clean(os.getenv("STATE_FILE") or "state.json")
RANDOM_ORDER = clean(os.getenv("RANDOM_ORDER") or "false").lower() == "true"

