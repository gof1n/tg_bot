"""
Клавиатуры для User Bot и Admin Bot.
"""

from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder


# --- User Bot ---

def get_user_main_keyboard() -> ReplyKeyboardMarkup:
    """Главное меню: Каталог, Корзина, Доставка, Оплата, Наш канал."""
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="🛍 Каталог"))
    builder.row(KeyboardButton(text="🚚 Доставка"), KeyboardButton(text="💳 Оплата"))
    builder.row(KeyboardButton(text="🛒 Корзина"))
    builder.row(KeyboardButton(text="📢 Наш канал"))
    return builder.as_markup(resize_keyboard=True)


def get_channel_link_keyboard() -> InlineKeyboardMarkup:
    """Кнопка перехода в Telegram-канал."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📢 Перейти в канал", url="https://t.me/liquid_augsburg")
    )
    return builder.as_markup()


def get_catalog_categories_keyboard() -> InlineKeyboardMarkup:
    """Категории каталога: Жидкости, Одноразки, Под-системы, Картриджи (по одной в ряд, как раньше)."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🧪 Жидкости", callback_data="cat:liquids"))
    builder.row(InlineKeyboardButton(text="💨 Одноразки", callback_data="cat:disposables"))
    builder.row(InlineKeyboardButton(text="📱 Под-системы", callback_data="cat:pods"))
    builder.row(InlineKeyboardButton(text="🔋 Картриджи", callback_data="cat:cartridges"))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_main"))
    return builder.as_markup()


GROUPS_PER_PAGE = 7


def get_groups_keyboard(category: str, groups: list, page: int = 0) -> InlineKeyboardMarkup:
    """Список товарных групп по 7 на странице, кнопки вперёд/назад."""
    builder = InlineKeyboardBuilder()
    start = page * GROUPS_PER_PAGE
    end = min(start + GROUPS_PER_PAGE, len(groups))
    for i in range(start, end):
        g = groups[i]
        builder.add(
            InlineKeyboardButton(text=g[:60], callback_data=f"grp:{category}:{i}")
        )
    builder.adjust(2)
    # Навигация по страницам
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"catpg:{category}:{page - 1}"))
    if end < len(groups):
        nav.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data=f"catpg:{category}:{page + 1}"))
    if nav:
        builder.row(*nav)
    builder.row(InlineKeyboardButton(text="◀️ К категориям", callback_data="cat:back"))
    return builder.as_markup()


def get_products_keyboard(category: str, group_name: str, products: list) -> InlineKeyboardMarkup:
    """Список вариантов (объём/крепость) — по 2 кнопки в ряд."""
    builder = InlineKeyboardBuilder()
    for p in products:
        if p.get("puffs"):
            label = f"{p['puffs']} тяг — {p['price']}€"
        else:
            label = f"{p.get('volume') or '-'} / {p.get('strength') or '-'} — {p['price']}€"
        builder.add(InlineKeyboardButton(text=label, callback_data=f"sku:{p['sku']}"))
    builder.adjust(2)
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data=f"cat:{category}")
    )
    return builder.as_markup()


def get_product_detail_keyboard(sku: str, category: str = "", group_index: int = 0) -> InlineKeyboardMarkup:
    """Кнопки «Добавить в корзину» и «Назад» к выбору вариантов."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🛒 Добавить в корзину", callback_data=f"addcart:{sku}")
    )
    if category is not None and category != "":
        builder.row(
            InlineKeyboardButton(text="◀️ Назад к вариантам", callback_data=f"grp:{category}:{group_index}")
        )
    return builder.as_markup()


def get_cart_keyboard(items: list) -> InlineKeyboardMarkup:
    """Корзина: для каждой позиции кнопка удаления, затем Оформить заказ, Назад."""
    builder = InlineKeyboardBuilder()
    for it in items:
        label = (it.get("group_name") or "Товар")[:28]
        if it.get("puffs"):
            label += f" ({it['puffs']} тяг)"
        else:
            vol = (it.get("volume") or "").strip()
            st = (it.get("strength") or "").strip()
            if vol or st:
                label += f" ({vol}, {st})"
        label = label[:40]
        sku = str(it.get("sku", ""))[:50]
        builder.row(
            InlineKeyboardButton(text=f"🗑 {label}", callback_data=f"cart_del:{sku}")
        )
    builder.row(InlineKeyboardButton(text="✅ Оформить заказ", callback_data="checkout"))
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="cart_back"))
    return builder.as_markup()


def get_cart_del_confirm_keyboard(sku: str) -> InlineKeyboardMarkup:
    """Подтверждение удаления позиции из корзины."""
    sku = str(sku)[:50]
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"cart_del_yes:{sku}"),
        InlineKeyboardButton(text="❌ Нет", callback_data="cart_del_no"),
    )
    return builder.as_markup()


def get_after_add_keyboard() -> InlineKeyboardMarkup:
    """После добавления в корзину."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📂 Продолжить покупки", callback_data="continue_shop"))
    builder.row(InlineKeyboardButton(text="🛒 В корзину", callback_data="to_cart"))
    return builder.as_markup()


def get_checkout_confirm_keyboard() -> InlineKeyboardMarkup:
    """Подтверждение заказа: Все верно, отправить / Отмена."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✅ Всё верно, отправить", callback_data="order_confirm"))
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="order_cancel"))
    return builder.as_markup()


# --- Admin Bot ---

def get_admin_main_keyboard() -> ReplyKeyboardMarkup:
    """Главное меню админа."""
    builder = ReplyKeyboardBuilder()
    builder.row(KeyboardButton(text="📊 Статистика"))
    builder.row(KeyboardButton(text="📋 Заказы"))
    builder.row(KeyboardButton(text="🔄 Обновить базу"))
    builder.row(KeyboardButton(text="🗑 Очистить и загрузить заново"))
    return builder.as_markup(resize_keyboard=True)


def get_admin_orders_menu_keyboard() -> InlineKeyboardMarkup:
    """Меню заказов: Активные / История."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📥 Активные заказы", callback_data="orders:active"),
        InlineKeyboardButton(text="📜 История", callback_data="orders:history"),
    )
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back_to_main"))
    return builder.as_markup()


def get_order_actions_keyboard(order_id: int) -> InlineKeyboardMarkup:
    """Кнопки Принять / Отклонить / Редактировать у заказа."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Принять", callback_data=f"order_accept:{order_id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"order_reject:{order_id}"),
    )
    builder.row(
        InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"order_edit:{order_id}")
    )
    return builder.as_markup()


def get_admin_stats_back_keyboard() -> InlineKeyboardMarkup:
    """Кнопка «Назад» из экрана статистики в главное меню."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back_to_main"))
    return builder.as_markup()


def get_admin_stats_period_keyboard() -> InlineKeyboardMarkup:
    """Выбор периода для статистики: неделя, месяц, год, свой период, назад."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📅 Неделя", callback_data="stats_period:week"),
        InlineKeyboardButton(text="📅 Месяц", callback_data="stats_period:month"),
    )
    builder.row(
        InlineKeyboardButton(text="📅 Год", callback_data="stats_period:year"),
        InlineKeyboardButton(text="📅 Свой период", callback_data="stats_period:custom"),
    )
    builder.row(InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back_to_main"))
    return builder.as_markup()




def get_sync_result_delete_keyboard() -> InlineKeyboardMarkup:
    """Кнопка «Удалить» под сообщением об итогах синхронизации."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🗑 Удалить сообщение", callback_data="admin_delete_msg"))
    return builder.as_markup()
