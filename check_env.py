from dotenv import load_dotenv
import os

def main():
    load_dotenv()

    vars_to_check = [
        "BOT_TOKEN",
        "TARGET_CHAT_ID",
        "SPREADSHEET_ID",
        "POST_TIME",
        "TZ",
        "ADMIN_IDS",
        "CREDENTIALS_FILE",
    ]

    for var in vars_to_check:
        val = os.getenv(var)
        if val is None:
            print(f"❌ {var} = НЕ НАЙДЕНО")
        else:
            print(f"✅ {var} = {val!r} (len={len(val)})")

if __name__ == "__main__":
    main()
