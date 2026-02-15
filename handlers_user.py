"""
User Bot — клиентская логика: каталог, корзина, оформление заказа.
Тон: дружелюбный, премиальный. Проверка in_stock перед добавлением в корзину.
Фото: file_id → локальный файл → скачивание по ссылке из таблицы (image_url).
"""

import os
from typing import Optional

import aiohttp
from aiogram import Router, F
from aiogram.filters import CommandStart, StateFilter
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from database import Database
from keyboards import (
    get_user_main_keyboard,
    get_catalog_categories_keyboard,
    get_groups_keyboard,
    get_products_keyboard,
    get_product_detail_keyboard,
    get_cart_keyboard,
    get_cart_del_confirm_keyboard,
    get_after_add_keyboard,
    get_checkout_confirm_keyboard,
    get_channel_link_keyboard,
)
from states import CheckoutStates
from utils import throttle_callback, register_callback_id_and_is_duplicate
from user_bot_texts import (
    WELCOME_TEXT,
    DELIVERY_TEXT,
    PAYMENT_TEXT,
    CART_EMPTY_TEXT,
    CHECKOUT_NAME_TEXT,
    CHECKOUT_CONTACT_TEXT,
    CHECKOUT_CITY_TEXT,
    ORDER_SUCCESS_TEXT,
    CATEGORY_IN_DEVELOPMENT,
)

router = Router()

# Корень проекта — для абсолютных путей к фото (работают при любом текущем каталоге)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _resolve_photo_path(path: str) -> str:
    """Превратить относительный путь к фото в абсолютный (от корня проекта)."""
    if not path or not path.strip():
        return ""
    path = path.strip()
    if os.path.isabs(path):
        return path
    return os.path.join(BASE_DIR, path)


async def _download_image_from_url(url: str) -> Optional[bytes]:
    """Скачать фото по ссылке из таблицы (Supabase и др.). User-Agent для обхода блокировок."""
    if not url or not url.strip().startswith(("http://", "https://")):
        return None
    url = url.strip().strip('"\'')
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; AugsburgLiquidBot/1.0)"}
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=5), headers=headers
            ) as resp:
                if resp.status != 200:
                    return None
                return await resp.read()
    except Exception:
        return None


# Категории с заглушкой "в разработке"
CATEGORIES_UNDER_DEVELOPMENT = ("pods", "cartridges")
CATEGORY_NAMES = {
    "disposables": "Одноразки",
    "liquids": "Жидкости",
    "pods": "Под-системы",
    "cartridges": "Картриджи",
}


def _get_product_caption(product: dict) -> str:
    """Если есть Кол-во тяг — показываем только его; иначе — объём и крепость. Описание — только если есть (не nan)."""
    lines = [f"<b>{product['group_name']}</b>", ""]
    if product.get("puffs"):
        lines.append(f"💨 Количество тяг: {product['puffs']}")
    else:
        if product.get("volume"):
            lines.append(f"💧 Объём: {product['volume']}")
        if product.get("strength"):
            lines.append(f"⚡️ Крепость: {product['strength']}")
    desc = product.get("description")
    if desc is not None and str(desc).strip().lower() not in ("", "nan", "none"):
        lines.append(f"\n{desc}")
    lines.append(f"\n💰 Цена: <b>{product['price']}€</b>")
    return "\n".join(lines)


async def _send_product_card(message_or_callback, product: dict, db: Database, bot, category: str = "", group_index: int = 0):
    """Показать карточку товара: фото (сначала file_id из Telegram, иначе локальный файл) и описание."""
    caption = _get_product_caption(product)
    reply_markup = get_product_detail_keyboard(product["sku"], category=category, group_index=group_index)
    target = message_or_callback.message if isinstance(message_or_callback, CallbackQuery) else message_or_callback
    sent = False
    # Сначала file_id — не зависит от папки product_photos (даже если файлы удалили, фото показывается)
    if product.get("telegram_file_id"):
        try:
            await bot.send_photo(
                target.chat.id,
                photo=product["telegram_file_id"],
                caption=caption,
                reply_markup=reply_markup,
            )
            sent = True
        except Exception:
            pass
    if not sent:
        photo_path = _resolve_photo_path(product.get("photo_path") or "")
        if photo_path and os.path.isfile(photo_path):
            try:
                from aiogram.types import FSInputFile
                await bot.send_photo(
                    target.chat.id,
                    photo=FSInputFile(photo_path),
                    caption=caption,
                    reply_markup=reply_markup,
                )
                sent = True
            except Exception:
                pass
    # Если ни file_id, ни файл — показываем фото по ссылке из таблицы (как раньше)
    if not sent and product.get("image_url") and str(product.get("image_url", "")).strip().startswith(("http://", "https://")):
        img_bytes = await _download_image_from_url(product["image_url"])
        if img_bytes:
            try:
                from aiogram.types import BufferedInputFile
                ext = "webp" if ".webp" in (product.get("image_url") or "").lower() else "jpg"
                await bot.send_photo(
                    target.chat.id,
                    photo=BufferedInputFile(img_bytes, filename=f"product.{ext}"),
                    caption=caption,
                    reply_markup=reply_markup,
                )
                sent = True
            except Exception:
                pass
    if not sent:
        await bot.send_message(
            target.chat.id,
            text=caption,
            reply_markup=reply_markup,
        )


def register_user_handlers(router: Router, db: Database, bot, admin_bot=None, admin_chat_id: int = None):
    """Регистрация хендлеров User Bot. bot — юзер-бот; admin_bot + admin_chat_id — для уведомлений о заказах."""

    @router.message(CommandStart())
    async def cmd_start(message: Message):
        full_name = message.from_user.full_name or ""
        await db.upsert_user(
            user_id=message.from_user.id,
            username=message.from_user.username,
            full_name=full_name,
        )
        welcome_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "welcome_image.png"))
        try:
            if os.path.isfile(welcome_path):
                from aiogram.types import FSInputFile
                await message.answer_photo(
                    photo=FSInputFile(welcome_path),
                    caption="✨ <b>Добро пожаловать в Augsburg Liquid!</b> ✨",
                )
            await message.answer(WELCOME_TEXT, reply_markup=get_user_main_keyboard())
        except Exception:
            await message.answer(WELCOME_TEXT, reply_markup=get_user_main_keyboard())

    async def _delete_message_safe(msg):
        """Удалить сообщение (чтобы не дублировать — остаётся только новое). Приветственное не трогаем."""
        try:
            await msg.delete()
        except Exception:
            pass

    @router.message(F.text.in_({"🛍 Каталог", "📂 Каталог"}))
    async def catalog_menu(message: Message):
        await _delete_message_safe(message)
        await message.answer(
            "Выберите категорию:",
            reply_markup=get_catalog_categories_keyboard(),
        )

    @router.message(F.text == "🚚 Доставка")
    async def delivery_info(message: Message):
        await _delete_message_safe(message)
        await message.answer(DELIVERY_TEXT)

    @router.message(F.text == "💳 Оплата")
    async def payment_info(message: Message):
        await _delete_message_safe(message)
        await message.answer(PAYMENT_TEXT)

    @router.message(F.text == "📢 Наш канал")
    async def channel_link(message: Message):
        await _delete_message_safe(message)
        await message.answer(
            "Подписывайтесь на наш канал Augsburg Liquid:",
            reply_markup=get_channel_link_keyboard(),
        )

    # --- Каталог: категории -> группы -> товары -> карточка (в наличии — из таблицы) ---
    @router.callback_query(F.data == "back_to_main")
    async def back_to_main(callback: CallbackQuery):
        if register_callback_id_and_is_duplicate(callback.id):
            await callback.answer()
            return
        if throttle_callback(callback.from_user.id, callback.data):
            await callback.answer()
            return
        await callback.answer()
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer("Главное меню:", reply_markup=get_user_main_keyboard())

    @router.callback_query(F.data.startswith("cat:"))
    async def catalog_category(callback: CallbackQuery):
        if register_callback_id_and_is_duplicate(callback.id):
            await callback.answer()
            return
        if throttle_callback(callback.from_user.id, callback.data):
            await callback.answer()
            return
        await callback.answer()
        data = callback.data
        if data == "cat:back":
            try:
                await callback.message.edit_text(
                    "Выберите категорию:",
                    reply_markup=get_catalog_categories_keyboard(),
                )
            except Exception:
                try:
                    await callback.message.delete()
                except Exception:
                    pass
                await callback.message.answer(
                    "Выберите категорию:",
                    reply_markup=get_catalog_categories_keyboard(),
                )
            return
        _, category = data.split(":", 1)
        # Под-системы и Картриджи — пока недоступны
        if category in CATEGORIES_UNDER_DEVELOPMENT:
            try:
                await callback.message.answer(CATEGORY_IN_DEVELOPMENT.strip()[:500])
            except Exception:
                pass
            return
        # Только товары в наличии (in_stock) из таблицы
        groups = await db.get_groups_by_category(category)
        if not groups:
            try:
                await callback.message.edit_text(
                    "В этой категории пока нет товаров в наличии.",
                    reply_markup=get_catalog_categories_keyboard(),
                )
            except Exception:
                try:
                    await callback.message.delete()
                except Exception:
                    pass
                await callback.message.answer(
                    "В этой категории пока нет товаров в наличии.",
                    reply_markup=get_catalog_categories_keyboard(),
                )
            return
        text = f"Категория: {CATEGORY_NAMES.get(category, category)}\n\nВыберите товар:"
        markup = get_groups_keyboard(category, groups)
        try:
            await callback.message.edit_text(text, reply_markup=markup)
        except Exception:
            # Сообщение с фото нельзя edit_text — удаляем и отправляем новое
            try:
                await callback.message.delete()
            except Exception:
                pass
            await callback.message.answer(text, reply_markup=markup)

    @router.callback_query(F.data.startswith("grp:"))
    async def catalog_group(callback: CallbackQuery):
        if register_callback_id_and_is_duplicate(callback.id):
            await callback.answer()
            return
        if throttle_callback(callback.from_user.id, callback.data):
            await callback.answer()
            return
        await callback.answer()
        _, category, idx = callback.data.split(":", 2)
        idx = int(idx)
        groups = await db.get_groups_by_category(category)
        if idx < 0 or idx >= len(groups):
            return
        group_name = groups[idx]
        products = await db.get_products_by_group(category, group_name)
        if not products:
            try:
                await callback.message.answer("Нет доступных вариантов.")
            except Exception:
                pass
            return
        text = f"<b>{group_name}</b>\n\nВыберите вариант (объём / крепость — цена):"
        markup = get_products_keyboard(category, group_name, products)
        first = products[0]
        try:
            await callback.message.delete()
        except Exception:
            pass
        sent = False
        if first.get("telegram_file_id"):
            try:
                await callback.message.answer_photo(
                    photo=first["telegram_file_id"],
                    caption=text,
                    reply_markup=markup,
                )
                sent = True
            except Exception:
                pass
        if not sent:
            first_photo_path = _resolve_photo_path(first.get("photo_path") or "")
            if first_photo_path and os.path.isfile(first_photo_path):
                try:
                    from aiogram.types import FSInputFile
                    await callback.message.answer_photo(
                        photo=FSInputFile(first_photo_path),
                        caption=text,
                        reply_markup=markup,
                    )
                    sent = True
                except Exception:
                    pass
        # Фото по ссылке из таблицы, если ни file_id ни файл не сработали
        if not sent and first.get("image_url") and str(first.get("image_url", "")).strip().startswith(("http://", "https://")):
            img_bytes = await _download_image_from_url(first["image_url"])
            if img_bytes:
                try:
                    from aiogram.types import BufferedInputFile
                    ext = "webp" if ".webp" in (first.get("image_url") or "").lower() else "jpg"
                    await callback.message.answer_photo(
                        photo=BufferedInputFile(img_bytes, filename=f"product.{ext}"),
                        caption=text,
                        reply_markup=markup,
                    )
                    sent = True
                except Exception:
                    pass
        if not sent:
            await callback.message.answer(text, reply_markup=markup)

    @router.callback_query(F.data.startswith("sku:"))
    async def catalog_sku(callback: CallbackQuery):
        if register_callback_id_and_is_duplicate(callback.id):
            await callback.answer()
            return
        if throttle_callback(callback.from_user.id, callback.data):
            await callback.answer()
            return
        await callback.answer()
        sku = callback.data.replace("sku:", "", 1)
        product = await db.get_product_by_sku(sku)
        if not product:
            try:
                await callback.message.answer("Товар не найден.")
            except Exception:
                pass
            return
        if not product.get("in_stock", 1):
            try:
                await callback.message.answer("К сожалению, этого товара нет в наличии.")
            except Exception:
                pass
            return
        category = product.get("category") or ""
        group_name = product.get("group_name") or ""
        groups = await db.get_groups_by_category(category)
        try:
            group_index = groups.index(group_name) if group_name in groups else 0
        except ValueError:
            group_index = 0
        try:
            await callback.message.delete()
        except Exception:
            pass
        await _send_product_card(callback, product, db, bot, category=category, group_index=group_index)

    @router.callback_query(F.data.startswith("addcart:"))
    async def add_to_cart(callback: CallbackQuery):
        if register_callback_id_and_is_duplicate(callback.id):
            await callback.answer()
            return
        if throttle_callback(callback.from_user.id, callback.data):
            await callback.answer()
            return
        await callback.answer()
        sku = callback.data.replace("addcart:", "", 1).strip()
        if not sku:
            return
        product = await db.get_product_by_sku(sku)
        if not product:
            try:
                await callback.message.answer("Товар не найден.")
            except Exception:
                pass
            return
        if not product.get("in_stock", 1):
            try:
                await callback.message.answer("К сожалению, этого товара нет в наличии.")
            except Exception:
                pass
            return
        await db.cart_add(callback.from_user.id, sku, 1)
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(
            f"✅ <b>{product['group_name']}</b> добавлен в корзину.\n\nЧто дальше?",
            reply_markup=get_after_add_keyboard(),
        )

    @router.callback_query(F.data == "continue_shop")
    async def continue_shop(callback: CallbackQuery):
        if register_callback_id_and_is_duplicate(callback.id):
            await callback.answer()
            return
        if throttle_callback(callback.from_user.id, callback.data):
            await callback.answer()
            return
        await callback.answer()
        try:
            await callback.message.edit_text(
                "Выберите категорию:",
                reply_markup=get_catalog_categories_keyboard(),
            )
        except Exception:
            try:
                await callback.message.delete()
            except Exception:
                pass
            await callback.message.answer(
                "Выберите категорию:",
                reply_markup=get_catalog_categories_keyboard(),
            )

    @router.callback_query(F.data == "to_cart")
    async def to_cart(callback: CallbackQuery):
        if register_callback_id_and_is_duplicate(callback.id):
            await callback.answer()
            return
        if throttle_callback(callback.from_user.id, callback.data):
            await callback.answer()
            return
        await callback.answer()
        try:
            await callback.message.delete()
        except Exception:
            pass
        await _reply_cart(callback.message, callback.from_user.id, db, bot)

    @router.message(F.text == "🛒 Корзина")
    async def cart_menu(message: Message):
        await _delete_message_safe(message)
        await _reply_cart(message, message.from_user.id, db, bot)

    @router.callback_query(F.data == "cart_back")
    async def cart_back(callback: CallbackQuery):
        if register_callback_id_and_is_duplicate(callback.id):
            await callback.answer()
            return
        if throttle_callback(callback.from_user.id, callback.data):
            await callback.answer()
            return
        await callback.answer()
        await callback.message.delete()
        await callback.message.answer("Главное меню:", reply_markup=get_user_main_keyboard())

    @router.callback_query(F.data.startswith("cart_del:"))
    async def cart_del_ask(callback: CallbackQuery):
        if register_callback_id_and_is_duplicate(callback.id):
            await callback.answer()
            return
        if throttle_callback(callback.from_user.id, callback.data):
            await callback.answer()
            return
        await callback.answer()
        sku = callback.data.replace("cart_del:", "", 1)
        if not sku:
            return
        try:
            await callback.message.delete()
        except Exception:
            pass
        product = await db.get_product_by_sku(sku)
        name = product["group_name"] if product else sku
        await callback.message.answer(
            f"Удалить <b>{name}</b> из корзины?",
            reply_markup=get_cart_del_confirm_keyboard(sku),
        )

    @router.callback_query(F.data.startswith("cart_del_yes:"))
    async def cart_del_confirm(callback: CallbackQuery):
        if register_callback_id_and_is_duplicate(callback.id):
            await callback.answer()
            return
        if throttle_callback(callback.from_user.id, callback.data):
            await callback.answer()
            return
        await callback.answer()
        sku = callback.data.replace("cart_del_yes:", "", 1)
        if not sku:
            return
        await db.cart_remove_item(callback.from_user.id, sku)
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer("✅ Позиция удалена из корзины.")
        items = await db.cart_get(callback.from_user.id)
        if not items:
            await callback.message.answer(CART_EMPTY_TEXT, reply_markup=get_user_main_keyboard())
            return
        lines = ["🛒 <b>Ваша корзина</b>\n"]
        total = 0.0
        for it in items:
            name = it["group_name"]
            puffs = it.get("puffs")
            vol = it.get("volume") or ""
            strength = it.get("strength") or ""
            detail = f" (тяг: {puffs})" if puffs else f" ({vol}, {strength})".strip(" ,")
            price = float(it["price"])
            qty = int(it["quantity"])
            subtotal = price * qty
            total += subtotal
            lines.append(f"• {name}{detail} — {qty} шт × {price}€ = {subtotal}€")
        lines.append(f"\n💰 <b>Итого: {total:.2f}€</b>")
        lines.append("\n<i>Удалить позицию:</i>")
        await callback.message.answer("\n".join(lines), reply_markup=get_cart_keyboard(items))

    @router.callback_query(F.data == "cart_del_no")
    async def cart_del_cancel(callback: CallbackQuery):
        if register_callback_id_and_is_duplicate(callback.id):
            await callback.answer()
            return
        if throttle_callback(callback.from_user.id, callback.data):
            await callback.answer()
            return
        await callback.answer()
        try:
            await callback.message.edit_text("Отменено.")
        except Exception:
            try:
                await callback.message.delete()
            except Exception:
                pass
            await callback.message.answer("Отменено.")

    async def _reply_cart(msg, user_id: int, db: Database, bot):
        items = await db.cart_get(user_id)
        if not items:
            await msg.answer(CART_EMPTY_TEXT, reply_markup=get_user_main_keyboard())
            return
        lines = ["🛒 <b>Ваша корзина</b>\n"]
        total = 0.0
        for it in items:
            name = it["group_name"]
            vol = it.get("volume") or ""
            strength = it.get("strength") or ""
            puffs = it.get("puffs")
            if puffs:
                detail = f" (тяг: {puffs})"
            else:
                detail = f" ({vol}, {strength})".strip(" ,")
            price = float(it["price"])
            qty = int(it["quantity"])
            subtotal = price * qty
            total += subtotal
            lines.append(f"• {name}{detail} — {qty} шт × {price}€ = {subtotal}€")
        lines.append(f"\n💰 <b>Итого: {total:.2f}€</b>")
        lines.append("\n<i>Удалить позицию:</i>")
        await msg.answer("\n".join(lines), reply_markup=get_cart_keyboard(items))

    # --- Оформление заказа (FSM) ---
    @router.callback_query(F.data == "checkout")
    async def checkout_start(callback: CallbackQuery, state: FSMContext):
        if register_callback_id_and_is_duplicate(callback.id):
            await callback.answer()
            return
        if throttle_callback(callback.from_user.id, callback.data):
            await callback.answer()
            return
        items = await db.cart_get(callback.from_user.id)
        if not items:
            await callback.answer("Корзина пуста.", show_alert=True)
            return
        await callback.answer()
        await state.set_state(CheckoutStates.input_name)
        await callback.message.answer(CHECKOUT_NAME_TEXT)

    @router.message(CheckoutStates.input_name, F.text)
    async def checkout_name(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if not text:
            await message.answer("Введите имя текстом.")
            return
        await message.answer(CHECKOUT_CONTACT_TEXT)
        await state.update_data(full_name=text)
        await state.set_state(CheckoutStates.input_contact)

    @router.message(CheckoutStates.input_contact, F.text)
    async def checkout_contact(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if not text:
            await message.answer("Введите контакт текстом.")
            return
        await message.answer(CHECKOUT_CITY_TEXT)
        await state.update_data(contact=text)
        await state.set_state(CheckoutStates.input_city)

    @router.message(CheckoutStates.input_city, F.text)
    async def checkout_city(message: Message, state: FSMContext):
        text = (message.text or "").strip()
        if not text:
            await message.answer("Введите город текстом.")
            return
        await state.update_data(city=text)
        await state.set_state(CheckoutStates.confirm)
        data = await state.get_data()
        items = await db.cart_get(message.from_user.id)
        if not items:
            await message.answer("Корзина пуста. Начните заново.", reply_markup=get_user_main_keyboard())
            await state.clear()
            return
        total = sum(float(i["price"]) * int(i["quantity"]) for i in items)
        summary = (
            "📋 <b>Проверьте данные заказа</b>\n\n"
            f"👤 Имя: {data.get('full_name')}\n"
            f"📱 Контакт: {data.get('contact')}\n"
            f"🏙 Город: {data.get('city')}\n\n"
            "<b>Товары:</b>\n"
        )
        for it in items:
            summary += f"• {it['group_name']} — {it['quantity']} шт × {it['price']}€\n"
        summary += f"\n💰 <b>Итого: {total:.2f}€</b>"
        await message.answer(summary, reply_markup=get_checkout_confirm_keyboard())

    @router.callback_query(F.data == "order_confirm")
    async def order_confirm(callback: CallbackQuery, state: FSMContext):
        if register_callback_id_and_is_duplicate(callback.id):
            await callback.answer()
            return
        if throttle_callback(callback.from_user.id, callback.data):
            await callback.answer()
            return
        data = await state.get_data()
        if not data.get("full_name") or not data.get("contact") or not data.get("city"):
            await callback.answer("Сначала заполните все данные заказа.", show_alert=True)
            return
        user_id = callback.from_user.id
        items = await db.cart_get(user_id)
        if not items:
            await callback.answer("Корзина пуста.", show_alert=True)
            await state.clear()
            return
        await callback.answer()
        total = sum(float(i["price"]) * int(i["quantity"]) for i in items)
        order_items = [
            {
                "name": it["group_name"],
                "sku": it["sku"],
                "volume": it.get("volume"),
                "strength": it.get("strength"),
                "puffs": it.get("puffs"),
                "quantity": it["quantity"],
                "price": it["price"],
            }
            for it in items
        ]
        order_id = await db.create_order(user_id, order_items, round(total, 2))
        await db.upsert_user(
            user_id=user_id,
            username=callback.from_user.username,
            full_name=data.get("full_name"),
            phone=data.get("contact"),
            city=data.get("city"),
        )
        await db.cart_clear(user_id)
        if admin_bot and admin_chat_id:
            admin_text = (
                f"📦 <b>НОВЫЙ ЗАКАЗ #{order_id}</b>\n\n"
                f"👤 Клиент: {data.get('full_name')} (@{callback.from_user.username or '—'})\n"
                f"📱 Контакт: {data.get('contact')}\n"
                f"🏙 Город: {data.get('city')}\n\n"
                "<b>🛒 Товары:</b>\n"
            )
            for it in items:
                if it.get("puffs"):
                    detail = f"{it['puffs']} тяг"
                else:
                    detail = f"{it.get('volume') or '-'}, {it.get('strength') or '-'}"
                admin_text += f"• <b>Артикул:</b> {it['sku']} — {it['group_name']} ({detail}) — {it['quantity']} шт × {it['price']}€\n"
            admin_text += f"\n💰 <b>Итого: {total:.2f}€</b>"
            try:
                await admin_bot.send_message(admin_chat_id, admin_text)
            except Exception:
                try:
                    await bot.send_message(admin_chat_id, admin_text)
                except Exception:
                    pass
        try:
            await callback.message.edit_text("✅ Заказ оформлен.")
        except Exception:
            pass
        await callback.message.answer(
            ORDER_SUCCESS_TEXT.format(order_id=order_id),
            reply_markup=get_user_main_keyboard(),
        )
        await state.clear()

    @router.callback_query(F.data == "order_cancel")
    async def order_cancel(callback: CallbackQuery, state: FSMContext):
        if register_callback_id_and_is_duplicate(callback.id):
            await callback.answer()
            return
        if throttle_callback(callback.from_user.id, callback.data):
            await callback.answer()
            return
        await callback.answer()
        await state.clear()
        try:
            await callback.message.edit_text("Оформление заказа отменено.")
        except Exception:
            pass
        await callback.message.answer("Главное меню:", reply_markup=get_user_main_keyboard())

    @router.message(
        StateFilter(CheckoutStates.input_name, CheckoutStates.input_contact, CheckoutStates.input_city),
        ~F.text,
    )
    async def checkout_non_text(message: Message):
        await message.answer("Пожалуйста, введите ответ текстом (не фото и не стикер).")
