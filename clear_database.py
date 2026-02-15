#!/usr/bin/env python3
"""
Полная очистка таблиц товаров и корзины.
После запуска нажмите в админ-боте «Обновить базу» или «Очистить и загрузить заново» —
данные подтянутся из таблицы (CSV) заново.

Использование: python3 clear_database.py
"""
import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

from database import Database


async def main():
    db_path = os.getenv("DATABASE_PATH", "augsburg_liquid.db")
    db = Database(db_path)
    await db.clear_products_and_cart()
    print("✅ База очищена: таблицы products и cart пусты.")
    print("   Дальше: в админ-боте нажмите «Обновить базу» или «Очистить и загрузить заново».")


if __name__ == "__main__":
    asyncio.run(main())
