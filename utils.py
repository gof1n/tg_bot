"""
Утилиты для работы с ботами Augsburg Liquid
"""

import asyncio
import time
from database import Database

# Защита от повторной обработки одного и того же нажатия (один callback_query.id = один ответ)
_processed_callback_ids: dict = {}
CALLBACK_ID_TTL_SEC = 120
CALLBACK_ID_MAX = 1000


def register_callback_id_and_is_duplicate(callback_id: str) -> bool:
    """Вернуть True если этот callback уже обрабатывали (дубликат), False если первый раз. Id регистрируется."""
    now = time.time()
    if callback_id in _processed_callback_ids:
        return True
    _processed_callback_ids[callback_id] = now
    while len(_processed_callback_ids) > CALLBACK_ID_MAX:
        oldest = min(_processed_callback_ids, key=_processed_callback_ids.get)
        del _processed_callback_ids[oldest]
    cutoff = now - CALLBACK_ID_TTL_SEC
    for cid in list(_processed_callback_ids):
        if _processed_callback_ids[cid] < cutoff:
            del _processed_callback_ids[cid]
    return False


# Защита от случайного двойного нажатия (не блокируем надолго — иначе кажется, что "не открывается с первого раза")
_callback_throttle: dict = {}
THROTTLE_SEC = 0.4
THROTTLE_MAX_SIZE = 500


def throttle_callback(user_id: int, data: str) -> bool:
    """True если нажатие нужно игнорировать (слишком часто)."""
    key = (user_id, data)
    now = time.time()
    if key in _callback_throttle and (now - _callback_throttle[key]) < THROTTLE_SEC:
        return True
    _callback_throttle[key] = now
    if len(_callback_throttle) > THROTTLE_MAX_SIZE:
        cutoff = now - 60
        for k in list(_callback_throttle):
            if _callback_throttle[k] < cutoff:
                del _callback_throttle[k]
    return False


async def init_database():
    """Инициализация базы данных"""
    db = Database("augsburg_liquid.db")
    await db.init_db()
    print("✅ База данных успешно инициализирована!")


async def add_sample_products():
    """Добавление примеров товаров"""
    db = Database("augsburg_liquid.db")
    await db.init_db()
    
    # Пример 1: Одноразка
    await db.add_product(
        hidden_id="LM_BM600_SI",
        name="Lost Mary BM600 Strawberry Ice",
        price=8.50,
        category="disposables",
        volumes=["600 puffs"],
        strengths=["2%", "5%"],
        photo_id=None
    )
    print("✅ Добавлена: Lost Mary BM600 Strawberry Ice")
    
    # Пример 2: Одноразка
    await db.add_product(
        hidden_id="ELF_BC5000",
        name="Elf Bar BC5000 Blue Razz Ice",
        price=12.00,
        category="disposables",
        volumes=["5000 puffs"],
        strengths=["2%", "5%"],
        photo_id=None
    )
    print("✅ Добавлена: Elf Bar BC5000")
    
    # Пример 3: Жидкость
    await db.add_product(
        hidden_id="IVG_BLUE_RASP",
        name="IVG Blue Raspberry",
        price=15.99,
        category="liquids",
        volumes=["30ml", "60ml", "100ml"],
        strengths=["0mg", "3mg", "6mg", "12mg"],
        photo_id=None
    )
    print("✅ Добавлена: IVG Blue Raspberry")
    
    # Пример 4: Жидкость
    await db.add_product(
        hidden_id="NASTY_ASAP",
        name="Nasty Juice ASAP Grape",
        price=14.50,
        category="liquids",
        volumes=["50ml", "100ml"],
        strengths=["0mg", "3mg", "6mg"],
        photo_id=None
    )
    print("✅ Добавлена: Nasty Juice ASAP Grape")
    
    print("\n🎉 Все примеры товаров добавлены!")


async def clear_database():
    """Очистка базы данных"""
    import os
    db_path = "augsburg_liquid.db"
    
    if os.path.exists(db_path):
        os.remove(db_path)
        print("✅ База данных очищена!")
    else:
        print("ℹ️ База данных не найдена")


async def show_stats():
    """Показать статистику"""
    db = Database("augsburg_liquid.db")
    
    categories = ["disposables", "liquids", "pods", "cartridges"]
    category_names = {
        "disposables": "Одноразки",
        "liquids": "Жидкости",
        "pods": "Под-системы",
        "cartridges": "Картриджи"
    }
    
    print("\n📊 Статистика магазина:\n")
    total_products = 0
    
    for category in categories:
        products = await db.get_products_by_category(category)
        count = len(products)
        total_products += count
        print(f"{category_names[category]}: {count} шт.")
        
        if products:
            for product in products:
                print(f"  • {product['name']} - {product['price']}€")
    
    print(f"\nВсего товаров: {total_products} шт.")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Использование:")
        print("  python utils.py init          - Инициализировать БД")
        print("  python utils.py sample        - Добавить примеры товаров")
        print("  python utils.py clear         - Очистить БД")
        print("  python utils.py stats         - Показать статистику")
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "init":
        asyncio.run(init_database())
    elif command == "sample":
        asyncio.run(add_sample_products())
    elif command == "clear":
        asyncio.run(clear_database())
    elif command == "stats":
        asyncio.run(show_stats())
    else:
        print(f"❌ Неизвестная команда: {command}")
