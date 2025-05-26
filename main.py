import asyncio
import logging
import sys

from telebot.async_telebot import AsyncTeleBot
from telebot.asyncio_helper import ApiTelegramException
from telebot.asyncio_storage.memory_storage import StateMemoryStorage

from config import BOT_TOKEN

from handlers import register_handlers

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', stream=sys.stdout)
logger = logging.getLogger(__name__)

if BOT_TOKEN is None:
    logger.critical("BOT_TOKEN не найден. Загрузить в env")
    sys.exit(1)

storage = StateMemoryStorage()
bot = AsyncTeleBot(BOT_TOKEN, state_storage=storage)
logger.info("Бот создан")

async def on_startup(bot_instance: AsyncTeleBot):
    logger.info("Бот успешно запущен")

async def on_shutdown(bot_instance: AsyncTeleBot):
    logger.info("Бот останавливается...")
    pass

async def main():
    register_handlers(bot)
    logger.info("Хендлеры зарегистрированы")

    await on_startup(bot)

    logger.info("Бот начинает polling...")
    await bot.infinity_polling(skip_pending=True)

    await on_shutdown(bot)

    logger.info("Бот завершил polling")

if __name__ == "__main__":
    logger.info("Начало запуска Telegram бота...")
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен вручную.")
    except ApiTelegramException as e:
         logger.error(f"Ошибка Telegram API: {e}", exc_info=True)
    except Exception as e:
        logger.critical(f"Непредвиденная критическая ошибка в боте: {e}", exc_info=True)

    logger.info("Работа Telegram бота завершена.")
    sys.exit(0)
