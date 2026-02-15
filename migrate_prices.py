"""
Миграция БД: Добавление поддержки динамических цен
"""

import asyncio
import aiosqlite

async def migrate():
    db_path = "augsburg_liquid.db"
    
    async with aiosqlite.connect(db_path) as db:
        print("🔄 Начинаем миграцию...")
        
        # Добавляем колонку prices_matrix в products
        try:
            await db.execute("ALTER TABLE products ADD COLUMN prices_matrix TEXT")
            print("✅ Добавлена колонка prices_matrix в products")
        except Exception as e:
            print(f"⚠️  Колонка prices_matrix уже существует или ошибка: {e}")
        
        # Добавляем колонку price в cart
        try:
            await db.execute("ALTER TABLE cart ADD COLUMN price REAL")
            print("✅ Добавлена колонка price в cart")
        except Exception as e:
            print(f"⚠️  Колонка price уже существует или ошибка: {e}")
        
        await db.commit()
        print("✅ Миграция завершена!")

if __name__ == "__main__":
    asyncio.run(migrate())
