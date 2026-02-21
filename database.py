"""
База данных для магазина Augsburg Liquid.
Асинхронный SQLite (aiosqlite), единая БД для User Bot и Admin Bot.
"""

import aiosqlite
import json
from typing import Optional, List, Dict, Any


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def init_db(self):
        """Инициализация БД: создание пустых таблиц. Товары в каталог не добавляются —
        только после нажатия «Обновить базу» в админ-боте (синхронизация из CSV/таблицы)."""
        async with aiosqlite.connect(self.db_path) as db:
            # Если таблица products со старой схемой (без sku/group_name) — пересоздаём
            try:
                async with db.execute("PRAGMA table_info(products)") as cur:
                    cols = await cur.fetchall()
                col_names = [c[1] for c in cols]
                if cols and "sku" not in col_names:
                    await db.execute("DROP TABLE IF EXISTS cart")
                    await db.execute("DROP TABLE IF EXISTS products")
                    await db.execute("DROP TABLE IF EXISTS orders")
            except Exception:
                pass

            # Товары (одна строка = один вариант; sku уникален для варианта: артикул_объём_крепость)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS products (
                    sku TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    group_name TEXT NOT NULL,
                    volume TEXT,
                    strength TEXT,
                    puffs INTEGER,
                    description TEXT,
                    price REAL NOT NULL,
                    image_url TEXT,
                    telegram_file_id TEXT,
                    photo_path TEXT,
                    in_stock INTEGER DEFAULT 1,
                    updated_at TEXT
                )
            """)

            # Пользователи
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    phone TEXT,
                    city TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            """)

            # Корзина (до оформления заказа)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS cart (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    sku TEXT NOT NULL,
                    quantity INTEGER DEFAULT 1,
                    FOREIGN KEY (user_id) REFERENCES users(user_id),
                    FOREIGN KEY (sku) REFERENCES products(sku),
                    UNIQUE(user_id, sku)
                )
            """)

            # Заказы
            await db.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    items_json TEXT NOT NULL,
                    total_amount REAL NOT NULL,
                    status TEXT DEFAULT 'new',
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                )
            """)

            await db.execute("CREATE INDEX IF NOT EXISTS idx_products_category ON products(category)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_products_group_name ON products(group_name)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_products_in_stock ON products(in_stock)")
            try:
                await db.execute("ALTER TABLE products ADD COLUMN photo_path TEXT")
            except Exception:
                pass
            # Миграция: добавить колонки в users, если таблица создана старой схемой
            for col in ("full_name", "phone", "city"):
                try:
                    await db.execute(f"ALTER TABLE users ADD COLUMN {col} TEXT")
                except Exception:
                    pass
            try:
                await db.execute("ALTER TABLE orders ADD COLUMN admin_note TEXT")
            except Exception:
                pass
            # Чёрный список (бан пользователей)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS blacklist (
                    user_id INTEGER PRIMARY KEY,
                    banned_at TEXT DEFAULT (datetime('now'))
                )
            """)
            await db.commit()

    # === USERS ===
    async def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Получить пользователя по user_id."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

    async def upsert_user(self, user_id: int, username: str = None, full_name: str = None,
                          phone: str = None, city: str = None):
        """Добавить или обновить пользователя."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO users (user_id, username, full_name, phone, city)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    full_name = COALESCE(excluded.full_name, full_name),
                    phone = COALESCE(excluded.phone, users.phone),
                    city = COALESCE(excluded.city, users.city)
            """, (user_id, username, full_name, phone or "", city or ""))
            await db.commit()

    # === PRODUCTS ===
    async def upsert_products_batch(self, rows: List[Dict[str, Any]]):
        """Атомарное обновление товаров (для синхронизации с CSV)."""
        if not rows:
            return
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN")
            try:
                for r in rows:
                    await db.execute("""
                        INSERT INTO products (
                            sku, category, group_name, volume, strength, puffs,
                            description, price, image_url, telegram_file_id, photo_path, in_stock, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                        ON CONFLICT(sku) DO UPDATE SET
                            category = excluded.category,
                            group_name = excluded.group_name,
                            volume = excluded.volume,
                            strength = excluded.strength,
                            puffs = excluded.puffs,
                            description = excluded.description,
                            price = excluded.price,
                            image_url = excluded.image_url,
                            telegram_file_id = COALESCE(excluded.telegram_file_id, products.telegram_file_id),
                            photo_path = COALESCE(excluded.photo_path, products.photo_path),
                            in_stock = excluded.in_stock,
                            updated_at = datetime('now')
                    """, (
                        r["sku"], r["category"], r["group_name"], r.get("volume") or "",
                        r.get("strength") or "", r.get("puffs"), r.get("description") or "",
                        r["price"], r.get("image_url") or "", r.get("telegram_file_id") or "",
                        r.get("photo_path") or "", r.get("in_stock", 1)
                    ))
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    async def update_product_telegram_file_id(self, sku: str, telegram_file_id: str):
        """Обновить кэшированный file_id фото после загрузки в Telegram."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE products SET telegram_file_id = ?, updated_at = datetime('now') WHERE sku = ?",
                (telegram_file_id, sku)
            )
            await db.commit()

    async def set_in_stock_for_skus(self, skus: List[str], in_stock: int):
        """Выставить in_stock для списка SKU (0 = скрыть, 1 = показывать)."""
        if not skus:
            return
        async with aiosqlite.connect(self.db_path) as db:
            placeholders = ",".join("?" * len(skus))
            await db.execute(
                f"UPDATE products SET in_stock = ?, updated_at = datetime('now') WHERE sku IN ({placeholders})",
                (in_stock, *skus),
            )
            await db.commit()

    async def set_in_stock_zero_except(self, keep_sku_list: List[str]):
        """Выставить in_stock = 0 для всех товаров, кроме переданного списка SKU.
        Показываются только товары из keep_sku_list; остальные скрываются."""
        async with aiosqlite.connect(self.db_path) as db:
            if not keep_sku_list:
                await db.execute(
                    "UPDATE products SET in_stock = 0, updated_at = datetime('now')"
                )
            else:
                placeholders = ",".join("?" * len(keep_sku_list))
                await db.execute(
                    f"UPDATE products SET in_stock = 0, updated_at = datetime('now') WHERE sku NOT IN ({placeholders})",
                    tuple(keep_sku_list),
                )
            await db.commit()

    async def delete_products_not_in_list(self, sku_list: List[str]):
        """Удалить из БД товары и позиции корзины по ним, которых нет в переданном списке SKU.
        sku_list — все SKU из текущей выгрузки таблицы (и с галочкой, и без)."""
        if not sku_list:
            return
        async with aiosqlite.connect(self.db_path) as db:
            placeholders = ",".join("?" * len(sku_list))
            await db.execute(
                f"DELETE FROM cart WHERE sku NOT IN ({placeholders})",
                tuple(sku_list),
            )
            await db.execute(
                f"DELETE FROM products WHERE sku NOT IN ({placeholders})",
                tuple(sku_list),
            )
            await db.commit()

    async def get_product_by_sku(self, sku: str) -> Optional[Dict[str, Any]]:
        """Получить товар по артикулу."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM products WHERE sku = ?", (sku,)) as cur:
                row = await cur.fetchone()
                return dict(row) if row else None

    async def get_products_by_category(self, category: str, in_stock_only: bool = True) -> List[Dict[str, Any]]:
        """Товары по категории. Опционально только в наличии."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if in_stock_only:
                async with db.execute(
                    "SELECT * FROM products WHERE category = ? AND in_stock = 1 ORDER BY group_name, sku",
                    (category,)
                ) as cur:
                    rows = await cur.fetchall()
            else:
                async with db.execute(
                    "SELECT * FROM products WHERE category = ? ORDER BY group_name, sku",
                    (category,)
                ) as cur:
                    rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def get_groups_by_category(self, category: str) -> List[str]:
        """Уникальные названия групп (group_name) по категории для списка товаров."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT DISTINCT group_name FROM products
                WHERE category = ? AND in_stock = 1
                ORDER BY group_name
            """, (category,)) as cur:
                rows = await cur.fetchall()
            return [r[0] for r in rows]

    async def get_products_by_group(self, category: str, group_name: str) -> List[Dict[str, Any]]:
        """Все варианты (SKU) одного товара по группе и категории."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM products
                WHERE category = ? AND group_name = ? AND in_stock = 1
                ORDER BY volume, strength
            """, (category, group_name)) as cur:
                rows = await cur.fetchall()
            return [dict(r) for r in rows]

    # === CART ===
    async def cart_add(self, user_id: int, sku: str, quantity: int = 1):
        """Добавить в корзину или увеличить количество."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO cart (user_id, sku, quantity) VALUES (?, ?, ?)
                ON CONFLICT(user_id, sku) DO UPDATE SET quantity = quantity + excluded.quantity
            """, (user_id, sku, quantity))
            await db.commit()

    async def cart_get(self, user_id: int) -> List[Dict[str, Any]]:
        """Корзина с данными товаров."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT c.sku, c.quantity, p.group_name, p.volume, p.strength, p.puffs, p.price
                FROM cart c
                JOIN products p ON c.sku = p.sku
                WHERE c.user_id = ?
            """, (user_id,)) as cur:
                rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def cart_clear(self, user_id: int):
        """Очистить корзину пользователя."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM cart WHERE user_id = ?", (user_id,))
            await db.commit()

    async def cart_remove_item(self, user_id: int, sku: str):
        """Удалить одну позицию из корзины."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM cart WHERE user_id = ? AND sku = ?", (user_id, sku))
            await db.commit()

    async def clear_products_and_cart(self):
        """Полностью очистить таблицы товаров и корзины. Заказы и пользователи не трогаем.
        После этого можно нажать «Обновить базу» / «Очистить и загрузить заново» — данные подтянутся из CSV заново."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM cart")
            await db.execute("DELETE FROM products")
            await db.commit()

    # === ORDERS ===
    async def create_order(self, user_id: int, items: List[Dict], total_amount: float) -> int:
        """Создать заказ. items: список dict с name, sku, quantity, price и т.д."""
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "INSERT INTO orders (user_id, items_json, total_amount, status) VALUES (?, ?, ?, 'new')",
                (user_id, json.dumps(items, ensure_ascii=False), total_amount)
            )
            await db.commit()
            return cur.lastrowid

    async def get_order(self, order_id: int) -> Optional[Dict[str, Any]]:
        """Получить заказ по ID."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)) as cur:
                row = await cur.fetchone()
                if not row:
                    return None
                d = dict(row)
                d["items"] = json.loads(d["items_json"])
                return d

    async def get_orders_by_status(self, status: str = "new") -> List[Dict[str, Any]]:
        """Список заказов по статусу (new, accepted, rejected)."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM orders WHERE status = ? ORDER BY order_id DESC",
                (status,),
            ) as cur:
                rows = await cur.fetchall()
                result = []
                for row in rows:
                    d = dict(row)
                    d["items"] = json.loads(d["items_json"])
                    result.append(d)
                return result

    async def update_order_status(self, order_id: int, status: str):
        """Обновить статус заказа (new, accepted, rejected)."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE orders SET status = ? WHERE order_id = ?",
                (status, order_id),
            )
            await db.commit()

    async def update_order_items_and_note(
        self, order_id: int, items: List[Dict], total_amount: float, admin_note: str
    ):
        """Обновить состав заказа и добавить пометку админа (изменено by admin_note)."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE orders SET items_json = ?, total_amount = ?, admin_note = ? WHERE order_id = ?",
                (json.dumps(items, ensure_ascii=False), total_amount, admin_note or "", order_id),
            )
            await db.commit()

    async def get_orders_by_statuses(self, statuses: List[str]) -> List[Dict[str, Any]]:
        """Список заказов с любым из статусов (например ['accepted','rejected'] для истории)."""
        if not statuses:
            return []
        placeholders = ",".join("?" * len(statuses))
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"SELECT * FROM orders WHERE status IN ({placeholders}) ORDER BY order_id DESC",
                tuple(statuses),
            ) as cur:
                rows = await cur.fetchall()
                result = []
                for row in rows:
                    d = dict(row)
                    d["items"] = json.loads(d["items_json"])
                    result.append(d)
                return result

    # === BLACKLIST ===
    async def is_banned(self, user_id: int) -> bool:
        """Проверить, забанен ли пользователь."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT 1 FROM blacklist WHERE user_id = ?", (user_id,)
            ) as cur:
                return (await cur.fetchone()) is not None

    async def add_to_blacklist(self, user_id: int):
        """Добавить пользователя в чёрный список."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO blacklist (user_id) VALUES (?)", (user_id,)
            )
            await db.commit()

    async def remove_from_blacklist(self, user_id: int):
        """Убрать пользователя из чёрного списка."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM blacklist WHERE user_id = ?", (user_id,))
            await db.commit()

    async def find_users_by_username(self, nick: str) -> List[Dict[str, Any]]:
        """Поиск пользователей по Telegram-нику (username). nick — с @ или без."""
        nick = (nick or "").strip().lstrip("@").lower()
        if not nick:
            return []
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM users WHERE LOWER(TRIM(username)) LIKE ? ORDER BY user_id",
                (f"%{nick}%",),
            ) as cur:
                rows = await cur.fetchall()
                return [dict(r) for r in rows]

    # === BROADCAST / EXPORT: все пользователи ===
    async def get_all_user_ids(self) -> List[int]:
        """Все user_id из users и из orders (объединение), для рассылки."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT DISTINCT user_id FROM (SELECT user_id FROM users UNION SELECT user_id FROM orders)"
            ) as cur:
                rows = await cur.fetchall()
                return [r[0] for r in rows]

    async def get_all_orders_for_export(self) -> List[Dict[str, Any]]:
        """Все заказы для выгрузки (все статусы)."""
        return await self.get_orders_by_statuses(["new", "accepted", "rejected"])

    async def get_all_users_for_export(self) -> List[Dict[str, Any]]:
        """Все пользователи для выгрузки."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM users ORDER BY user_id") as cur:
                rows = await cur.fetchall()
                return [dict(r) for r in rows]

    # === STATS (период: start_date, end_date в формате YYYY-MM-DD) ===
    async def get_stats_users_in_period(self, start_date: str, end_date: str) -> int:
        """Уникальных пользователей, оформивших заказ в указанный период."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """SELECT COUNT(DISTINCT user_id) FROM orders
                   WHERE date(created_at) >= ? AND date(created_at) <= ?""",
                (start_date, end_date),
            ) as cur:
                row = await cur.fetchone()
                return row[0] or 0

    async def get_stats_orders_in_period(self, start_date: str, end_date: str) -> tuple:
        """(количество заказов, сумма выручки) за период."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """SELECT COUNT(*), COALESCE(SUM(total_amount), 0) FROM orders
                   WHERE date(created_at) >= ? AND date(created_at) <= ?""",
                (start_date, end_date),
            ) as cur:
                row = await cur.fetchone()
                return (row[0] or 0, float(row[1] or 0))

    async def get_stats_top_products_in_period(
        self, start_date: str, end_date: str, limit: int = 10
    ) -> List[tuple]:
        """Топ продаваемых товаров за период: список (group_name, суммарное кол-во шт)."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """SELECT items_json FROM orders
                   WHERE date(created_at) >= ? AND date(created_at) <= ?""",
                (start_date, end_date),
            ) as cur:
                rows = await cur.fetchall()
        agg: Dict[str, int] = {}
        for (items_json,) in rows:
            try:
                items = json.loads(items_json)
                for it in items:
                    name = it.get("group_name") or it.get("name") or "—"
                    qty = int(it.get("quantity") or 0)
                    agg[name] = agg.get(name, 0) + qty
            except (json.JSONDecodeError, TypeError):
                continue
        sorted_agg = sorted(agg.items(), key=lambda x: -x[1])
        return sorted_agg[:limit]

    async def get_stats_ltv_in_period(self, start_date: str, end_date: str) -> float:
        """LTV за период: средняя выручка на одного пользователя в этом периоде."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """SELECT COUNT(DISTINCT user_id), COALESCE(SUM(total_amount), 0) FROM orders
                   WHERE date(created_at) >= ? AND date(created_at) <= ?""",
                (start_date, end_date),
            ) as cur:
                row = await cur.fetchone()
                users = row[0] or 0
                total = float(row[1] or 0)
                return round(total / users, 2) if users else 0.0

    async def get_stats_retention_in_period(self, start_date: str, end_date: str) -> tuple:
        """Retention за период: (пользователей с 2+ заказами в периоде, всего с 1+ заказом в периоде)."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """SELECT COUNT(*) FROM (
                     SELECT user_id FROM orders
                     WHERE date(created_at) >= ? AND date(created_at) <= ?
                     GROUP BY user_id HAVING COUNT(*) >= 2
                   )""",
                (start_date, end_date),
            ) as cur:
                repeat = (await cur.fetchone())[0] or 0
            async with db.execute(
                """SELECT COUNT(DISTINCT user_id) FROM orders
                   WHERE date(created_at) >= ? AND date(created_at) <= ?""",
                (start_date, end_date),
            ) as cur:
                total = (await cur.fetchone())[0] or 0
                return (repeat, total)

    async def get_stats_pending_carts(self) -> int:
        """Количество корзин (уникальных пользователей с непустой корзиной)."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(DISTINCT user_id) FROM cart"
            ) as cur:
                row = await cur.fetchone()
                return row[0] or 0

    async def get_stats_churn(self, start_date: str, end_date: str) -> tuple:
        """Churn: (пользователей, которые заказывали ДО периода, но не в периоде, всего кто заказывал до периода)."""
        async with aiosqlite.connect(self.db_path) as db:
            # Уникальные user_id, которые заказывали до начала периода
            async with db.execute(
                "SELECT DISTINCT user_id FROM orders WHERE date(created_at) < ?", (start_date,)
            ) as cur:
                before = set(r[0] for r in await cur.fetchall())
            # Кто заказывал в периоде
            async with db.execute(
                """SELECT DISTINCT user_id FROM orders
                   WHERE date(created_at) >= ? AND date(created_at) <= ?""",
                (start_date, end_date),
            ) as cur:
                in_period = set(r[0] for r in await cur.fetchall())
        churned = before - in_period
        return (len(churned), len(before))

    async def get_stats_dau_mau(self, start_date: str, end_date: str) -> tuple:
        """DAU/MAU: (среднее число уникальных пользователей в день в периоде, уникальных пользователей за весь период). По заказам."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                """SELECT date(created_at) as d, COUNT(DISTINCT user_id) as cnt FROM orders
                   WHERE date(created_at) >= ? AND date(created_at) <= ?
                   GROUP BY date(created_at)""",
                (start_date, end_date),
            ) as cur:
                rows = await cur.fetchall()
            if not rows:
                return (0.0, 0)
            dau_sum = sum(r[1] for r in rows)
            days = len(rows)
            avg_dau = round(dau_sum / days, 1)
            async with db.execute(
                """SELECT COUNT(DISTINCT user_id) FROM orders
                   WHERE date(created_at) >= ? AND date(created_at) <= ?""",
                (start_date, end_date),
            ) as cur:
                mau = (await cur.fetchone())[0] or 0
        return (avg_dau, mau)

    async def get_stats_total_users_with_orders(self) -> int:
        """Всего пользователей, когда-либо оформивших заказ (для конверсии в покупку)."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(DISTINCT user_id) FROM orders"
            ) as cur:
                row = await cur.fetchone()
                return row[0] or 0

    async def get_stats_total_users_registered(self) -> int:
        """Всего пользователей в таблице users (заходили в бота / оформили заказ)."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM users") as cur:
                row = await cur.fetchone()
                return row[0] or 0
