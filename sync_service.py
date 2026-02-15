"""
Синхронизация товаров: CSV (Google Sheets export) -> SQLite.
Парсинг через pandas, умное кэширование фото в Telegram (file_id).
Одна ссылка на фото -> скачиваем один раз, получаем file_id -> для всех строк с этой ссылкой подставляем тот же file_id.
"""

import re
import asyncio
import hashlib
import logging
import os
from typing import List, Dict, Any, Optional, Callable

logger = logging.getLogger(__name__)

import aiosqlite
import pandas as pd
import aiohttp
from aiogram import Bot

from database import Database


async def _set_in_stock_zero_except(db_path: str, keep_sku_list: List[str]) -> None:
    """Выставить in_stock = 0 для всех товаров, кроме переданного списка SKU."""
    async with aiosqlite.connect(db_path) as conn:
        if not keep_sku_list:
            await conn.execute(
                "UPDATE products SET in_stock = 0, updated_at = datetime('now')"
            )
        else:
            placeholders = ",".join("?" * len(keep_sku_list))
            await conn.execute(
                f"UPDATE products SET in_stock = 0, updated_at = datetime('now') WHERE sku NOT IN ({placeholders})",
                tuple(keep_sku_list),
            )
        await conn.commit()


async def _delete_products_not_in_list(db_path: str, sku_list: List[str]) -> None:
    """Удалить из БД товары и позиции корзины по ним, которых нет в списке SKU."""
    if not sku_list:
        return
    async with aiosqlite.connect(db_path) as conn:
        placeholders = ",".join("?" * len(sku_list))
        await conn.execute(
            f"DELETE FROM cart WHERE sku NOT IN ({placeholders})",
            tuple(sku_list),
        )
        await conn.execute(
            f"DELETE FROM products WHERE sku NOT IN ({placeholders})",
            tuple(sku_list),
        )
        await conn.commit()


# Названия колонок из таблицы (нормализуем к нижнему регистру для поиска).
# Первая строка в таблице — заголовок "Складской учет", названия колонок — со второй строки.
# Обязательные: Артикул, Название, Цена продажи (€). Не отображаются: Артикул, Ссылка, Количество, Себест. (€), Маржа %.
COLUMN_MAP = {
    "артикул": "sku",
    "название": "group_name",
    "категория": "category",
    "объем": "volume",
    "объём": "volume",
    "крепость": "strength",
    "кол-во тяг": "puffs",
    "ссылка": "link",
    "количество": "stock_qty",
    "себест. (€)": "cost",
    "себест.": "cost",
    "цена продажи (€)": "price",
    "цена продажи (eur)": "price",
    "цена продажи": "price",
    "цена продажи(€)": "price",
    "маржа %": "margin",
    "маржа": "margin",
    "ссылка на фото": "image_url",
    "фото": "image_url",
    "photo": "image_url",
    "image": "image_url",
    "картинка": "image_url",
    "img": "image_url",
    "фото товара": "image_url",
    "описание": "description",
    "доступность": "availability",
}

# Нормализация категорий из CSV в единый вид
CATEGORY_MAP = {
    "жидкости": "liquids",
    "одноразки": "disposables",
    "поды": "pods",
    "под-системы": "pods",
    "картриджи": "cartridges",
}


def _normalize_column_name(name: str) -> str:
    if not isinstance(name, str):
        return ""
    # Убираем BOM и лишние пробелы (часто бывает в CSV из Google Sheets)
    s = name.strip().lower().replace("\ufeff", "").strip()
    return s


def _clean_price(value: Any) -> float:
    """Удалить €, пробелы, заменить запятую на точку. Вернуть float."""
    if pd.isna(value):
        return 0.0
    s = str(value).strip().replace("€", "").replace(" ", "").replace(",", ".")
    s = re.sub(r"[^\d.]", "", s)
    try:
        return float(s) if s else 0.0
    except ValueError:
        return 0.0


def _clean_puffs(value: Any) -> Optional[int]:
    """Кол-во тяг: пусто -> None, иначе int."""
    if pd.isna(value) or value == "":
        return None
    try:
        s = str(value).strip()
        s = re.sub(r"[^\d]", "", s)
        return int(s) if s else None
    except (ValueError, TypeError):
        return None


def _clean_stock_qty(value: Any) -> int:
    """stock_qty <= 0 или пусто -> in_stock = 0, иначе 1."""
    if pd.isna(value) or value == "":
        return 0
    try:
        n = int(float(value))
        return 1 if n > 0 else 0
    except (ValueError, TypeError):
        return 0


def _clean_availability(value: Any) -> int:
    """Колонка «Доступность» (чекбокс): галочка -> 1 (показывать), нет -> 0 (не показывать).
    В CSV из Google Sheets чекбокс обычно как TRUE/FALSE или TRUE/False."""
    if pd.isna(value):
        return 0
    s = str(value).strip().upper()
    if s in ("TRUE", "1", "YES", "ДА", "Д", "+", "X", "✓", "✔"):
        return 1
    return 0


def _normalize_category(cat: Any) -> str:
    """Привести категорию к одному из: liquids, disposables, pods, cartridges."""
    if pd.isna(cat):
        return "liquids"
    s = str(cat).strip().lower()
    return CATEGORY_MAP.get(s, "liquids")


def _fetch_csv_as_dataframe(url: str) -> pd.DataFrame:
    """Скачать CSV по URL. Первая строка — заголовок таблицы (Складской учет), вторая — названия колонок.
    Ссылка вида .../pub?gid=XXX&single=true&output=csv работает, если таблица «Опубликована в интернете»
    (Файл → Общий доступ → Опубликовать в интернете). Иначе используйте .../export?format=csv&gid=XXX"""
    df = pd.read_csv(url, header=1, encoding="utf-8")
    # Убираем BOM из названий колонок, если есть
    df.columns = [str(c).replace("\ufeff", "").strip() for c in df.columns]
    return df


def _map_and_clean(df: pd.DataFrame) -> tuple:
    """Маппинг колонок. Возвращает (rows, unavailable_skus).
    rows — только товары с включённой «Доступностью» (или все, если колонки нет).
    unavailable_skus — sku строк с выключенной «Доступностью», чтобы выставить в БД in_stock=0."""
    # Нормализованные имена колонок CSV -> исходное имя в DataFrame
    col_normalized = {_normalize_column_name(c): c for c in df.columns}
    mapped = {}
    for ru_name, en_name in COLUMN_MAP.items():
        if ru_name in col_normalized:
            mapped[en_name] = col_normalized[ru_name]
    # Fallback: колонка для фото — первая, в названии которой есть «фото» или «photo»
    if "image_url" not in mapped:
        for orig_name in df.columns:
            n = _normalize_column_name(str(orig_name))
            if "фото" in n or "photo" in n or "image" in n:
                mapped["image_url"] = orig_name
                break
    # Проверка обязательных: должны быть артикул, название, цена
    missing = []
    if "sku" not in mapped:
        missing.append("Артикул")
    if "group_name" not in mapped:
        missing.append("Название")
    if "price" not in mapped:
        missing.append("Цена продажи (€) или Цена продажи")
    if missing:
        found = list(df.columns) if hasattr(df.columns, "__iter__") else []
        raise ValueError(
            f"В таблице должны быть колонки: Артикул, Название, Цена продажи (€). "
            f"Не найдены: {', '.join(missing)}. "
            f"Сейчас в таблице: {', '.join(str(c) for c in found[:15])}{'...' if len(found) > 15 else ''}"
        )

    def _sanitize(s: str) -> str:
        """Убрать символы, мешающие использовать в ID."""
        return re.sub(r"[^\w\-.,%()]", "_", str(s).strip())[:80]

    has_availability = mapped.get("availability") is not None
    rows: List[Dict[str, Any]] = []
    unavailable_skus: List[str] = []

    for idx, row in df.iterrows():
        sku_val = row.get(mapped["sku"], "")
        if pd.isna(sku_val) or str(sku_val).strip() == "":
            continue
        sku_base = str(sku_val).strip()
        name_val = row.get(mapped["group_name"], "")
        if pd.isna(name_val) or str(name_val).strip() == "":
            continue
        group_name = str(name_val).strip()
        volume = str(row.get(mapped.get("volume"), "")).strip() if mapped.get("volume") else ""
        strength = str(row.get(mapped.get("strength"), "")).strip() if mapped.get("strength") else ""
        sku_unique = f"{_sanitize(sku_base)}_{_sanitize(volume)}_{_sanitize(strength)}"
        if not volume and not strength:
            sku_unique = f"{_sanitize(sku_base)}_{idx}"

        # Если есть «Доступность» и она выключена — не строим строку, не качаем фото; только запомним sku для in_stock=0 в БД
        if has_availability:
            in_stock = _clean_availability(row.get(mapped["availability"], ""))
            if in_stock == 0:
                unavailable_skus.append(sku_unique)
                continue

        price = _clean_price(row.get(mapped["price"], 0))
        if price <= 0:
            continue

        category = _normalize_category(row.get(mapped.get("category"), ""))
        puffs = _clean_puffs(row.get(mapped.get("puffs"), None)) if mapped.get("puffs") else None
        desc_raw = row.get(mapped.get("description"), "") if mapped.get("description") else ""
        if pd.isna(desc_raw) or str(desc_raw).strip().lower() in ("nan", "none", ""):
            description = ""
        else:
            description = str(desc_raw).strip()
        if has_availability:
            in_stock = 1  # уже проверили выше
        else:
            in_stock = _clean_stock_qty(row.get(mapped.get("stock_qty"), 1)) if mapped.get("stock_qty") else 1
        image_url = ""
        if mapped.get("image_url"):
            v = row.get(mapped["image_url"], "")
            if not pd.isna(v):
                image_url = str(v).strip().strip('"\'')
                if image_url.startswith("="):
                    image_url = ""

        rows.append({
            "sku": sku_unique,
            "category": category,
            "group_name": group_name,
            "volume": volume,
            "strength": strength,
            "puffs": puffs,
            "description": description,
            "price": round(price, 2),
            "image_url": image_url or "",
            "in_stock": in_stock,
        })
    # Имя колонки в таблице, из которой читаем ссылку на фото (для лога)
    image_column_name = mapped.get("image_url")
    return (rows, unavailable_skus, image_column_name)


async def _download_image(url: str) -> Optional[bytes]:
    """Скачать изображение по URL. User-Agent нужен для Supabase и других CDN."""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; AugsburgLiquidBot/1.0)"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=15), headers=headers
            ) as resp:
                if resp.status != 200:
                    logger.warning("Скачивание фото: URL вернул статус %s", resp.status)
                    return None
                return await resp.read()
    except Exception as e:
        logger.warning("Скачивание фото не удалось: %s", e)
        return None


def _photo_extension_from_url(url: str) -> str:
    """Расширение файла по URL (.webp или .jpg)."""
    u = (url or "").strip().lower()
    if ".webp" in u or u.endswith(".webp"):
        return "webp"
    return "jpg"


async def _upload_photo_to_telegram_and_get_file_id(
    bot: Bot, image_bytes: bytes, admin_chat_id: int, image_url: str = ""
) -> Optional[str]:
    """
    Отправить фото в чат админа и вернуть file_id. Этим file_id потом показываем фото в каталоге юзер-бота.
    Поддержка .webp. Без корректного chat_id фото в Telegram не загружаются.
    """
    if not admin_chat_id:
        logger.warning("Чат для загрузки фото не задан (ADMIN_CHAT_ID в .env или запуск синхронизации из чата с ботом).")
        return None
    ext = _photo_extension_from_url(image_url)
    filename = f"product.{ext}"
    try:
        from aiogram.types import BufferedInputFile
        file = BufferedInputFile(image_bytes, filename=filename)
        msg = await bot.send_photo(admin_chat_id, photo=file)
        if msg.photo:
            return msg.photo[-1].file_id
    except Exception as e:
        logger.warning(
            "Не удалось отправить фото в Telegram (chat_id=%s). Ошибка: %s. Убедитесь, что вы писали боту в личку /start.",
            admin_chat_id,
            repr(e),
        )
    return None


async def sync_products(
    db: Database,
    csv_url: str,
    bot: Bot,
    admin_chat_id: int,
    on_progress: Optional[Callable] = None,
    upload_chat_id: Optional[int] = None,
) -> tuple:
    """
    Синхронизация: скачать CSV, очистить данные, загрузить фото в Telegram (в чат админа),
    получить file_id, сохранить в БД и на диск. После этого фото отображаются в каталоге юзер-бота.
    Возвращает (количество товаров, количество товаров с загруженным фото).
    upload_chat_id: если admin_chat_id не задан, сюда отправляем фото (чат, откуда запущена синхронизация).
    """
    loop = asyncio.get_event_loop()
    df = await loop.run_in_executor(None, _fetch_csv_as_dataframe, csv_url)
    rows, unavailable_skus, image_column_name = _map_and_clean(df)
    if not rows and not unavailable_skus:
        return (0, 0)
    # Чат для загрузки фото: сначала ADMIN_CHAT_ID, иначе чат, откуда нажали «Обновить базу»
    effective_upload_chat = admin_chat_id or upload_chat_id
    rows_with_photo_url = sum(1 for r in rows if (r.get("image_url") or "").strip().startswith(("http://", "https://")))
    logger.info(
        "Синхронизация: колонка для фото=%s, товаров с ссылкой на фото=%s, чат для загрузки фото=%s",
        image_column_name or "не найдена",
        rows_with_photo_url,
        effective_upload_chat or "не задан (фото не будут загружены в Telegram)",
    )
    if rows_with_photo_url and rows:
        sample = (rows[0].get("image_url") or "").strip()[:100]
        logger.info("Пример ссылки на фото: %s", sample or "(пусто)")
    photos_uploaded = 0

    # Загружаем существующие товары для сравнения image_url, telegram_file_id, photo_path
    existing = {}
    for r in rows:
        sku = r["sku"]
        prod = await db.get_product_by_sku(sku)
        if prod:
            existing[sku] = {
                "image_url": (prod.get("image_url") or "").strip(),
                "telegram_file_id": (prod.get("telegram_file_id") or "").strip(),
                "photo_path": (prod.get("photo_path") or "").strip(),
            }

    # Кэш по URL: одна ссылка — одно скачивание, один file_id. Для всех строк с той же ссылкой подставляем уже известный file_id.
    url_cache: Dict[str, Dict[str, str]] = {}
    for sku, ex in existing.items():
        url = (ex.get("image_url") or "").strip()
        if url and ex.get("telegram_file_id") and url not in url_cache:
            url_cache[url] = {
                "file_id": ex.get("telegram_file_id", ""),
                "photo_path": ex.get("photo_path") or "",
            }

    # Сохраняем фото всегда в каталог проекта (относительно sync_service.py), независимо от cwd
    _sync_base = os.path.dirname(os.path.abspath(__file__))
    _photos_dir = os.path.join(_sync_base, "product_photos", "by_url")
    os.makedirs(_photos_dir, exist_ok=True)

    # Проверка: есть ли в CSV колонка для ссылки на фото
    has_image_col = any(r.get("image_url") for r in rows)
    if not has_image_col and rows:
        logger.warning(
            "В таблице не найдена колонка со ссылкой на фото (ожидаются: «Ссылка на фото», «Фото», «Photo», «Image»). "
            "Фото товаров не будут загружаться."
        )

    total = len(rows)
    for i, r in enumerate(rows):
        if on_progress and (i % 10 == 0 or i == total - 1):
            await on_progress(i + 1, total, "Обработка товаров...")

        sku = r["sku"]
        r["photo_path"] = ""
        r["telegram_file_id"] = ""

        # Доступность выключена — не скачиваем фото и не грузим в Telegram, только подставляем старые file_id/path при наличии
        if r.get("in_stock") == 0:
            r["telegram_file_id"] = existing.get(sku, {}).get("telegram_file_id") or ""
            r["photo_path"] = existing.get(sku, {}).get("photo_path") or ""
            continue

        image_url = (r.get("image_url") or "").strip().strip('"\'')
        if not image_url or not image_url.startswith(("http://", "https://")):
            r["telegram_file_id"] = existing.get(sku, {}).get("telegram_file_id") or ""
            r["photo_path"] = existing.get(sku, {}).get("photo_path") or ""
            continue

        if image_url in url_cache:
            r["telegram_file_id"] = url_cache[image_url]["file_id"]
            r["photo_path"] = url_cache[image_url]["photo_path"]
            continue

        img_bytes = await _download_image(image_url)
        if not img_bytes:
            if photos_uploaded == 0 and not url_cache:
                logger.warning("Первое фото не скачалось (sku=%s). URL: %s", sku, image_url[:100])
            r["telegram_file_id"] = existing.get(sku, {}).get("telegram_file_id") or ""
            r["photo_path"] = existing.get(sku, {}).get("photo_path") or ""
            continue

        file_id = await _upload_photo_to_telegram_and_get_file_id(
            bot, img_bytes, effective_upload_chat or 0, image_url
        )
        if not file_id:
            if photos_uploaded == 0 and not url_cache:
                logger.warning(
                    "Первое фото не отправилось в Telegram (sku=%s). Проверьте ADMIN_CHAT_ID и что админ-бот может писать в этот чат.",
                    sku,
                )
            r["telegram_file_id"] = existing.get(sku, {}).get("telegram_file_id") or ""
            r["photo_path"] = existing.get(sku, {}).get("photo_path") or ""
            continue
        photos_uploaded += 1

        url_hash = hashlib.md5(image_url.encode()).hexdigest()[:16]
        ext = _photo_extension_from_url(image_url)
        photo_filename = f"{url_hash}.{ext}"
        photo_path_abs = os.path.join(_photos_dir, photo_filename)
        photo_path_rel = os.path.join("product_photos", "by_url", photo_filename)
        try:
            with open(photo_path_abs, "wb") as f:
                f.write(img_bytes)
        except Exception as e:
            logger.warning("Не удалось сохранить файл фото %s: %s", photo_path_abs, e)
            photo_path_rel = ""

        url_cache[image_url] = {"file_id": file_id, "photo_path": photo_path_rel}
        r["telegram_file_id"] = file_id
        r["photo_path"] = photo_path_rel

    await db.upsert_products_batch(rows)
    available_skus = [r["sku"] for r in rows]
    db_path = db.db_path
    # Показывать ТОЛЬКО товары с галочкой «Доступность»: у остальных in_stock=0
    await _set_in_stock_zero_except(db_path, available_skus)
    # Удалить из БД товары, которых уже нет в таблице
    all_skus_from_csv = list(set(available_skus) | set(unavailable_skus))
    if all_skus_from_csv:
        await _delete_products_not_in_list(db_path, all_skus_from_csv)
    count_with_photo = sum(1 for r in rows if (r.get("telegram_file_id") or "").strip())
    return (len(rows), count_with_photo)
