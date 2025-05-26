from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy.exc import SQLAlchemyError
from config import DATABASE_URL

engine = create_async_engine(DATABASE_URL, echo=False)

AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)

Base = declarative_base()

async def get_async_db() -> AsyncSession:
    """
    Создает и предоставляет асинхронную сессию SQLAlchemy.
    Гарантирует закрытие сессии после использования.
    Пример использования: async with get_async_db() as session: ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except SQLAlchemyError as e:
            print(f"Ошибка сессии SQLAlchemy: {e}")
            raise

async def init_models():
    """
    Асинхронно создает все таблицы в базе данных, определенные в моделях, унаследованных от Base.
    """
    try:
        async with engine.begin() as conn:
            # Для удаления таблиц перед созданием
            # print("Удаление старых таблиц...")
            # await conn.run_sync(Base.metadata.drop_all)
            # print("Старые таблицы удалены.")

            print("Запуск Base.metadata.create_all...")
            await conn.run_sync(Base.metadata.create_all)
            print("Создание таблиц успешно завершено.")

    except SQLAlchemyError as e:
        print(f"Ошибка при инициализации БД: {e}")
        raise
    except Exception as e:
        print(f"Ошибка при инициализации БД: {e}")
        raise
