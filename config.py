import os
import dotenv

# Загружаем переменные из файла .env
dotenv.load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

if not BOT_TOKEN:
    raise ValueError("TELEGRAM_TOKEN не найден")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL не найден")
